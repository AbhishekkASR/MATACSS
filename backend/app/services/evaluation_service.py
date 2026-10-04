"""Deterministic test-case evaluation for persisted submissions."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import EvaluationResult
from app.models.question import Question
from app.models.question_test_case import QuestionTestCase
from app.models.submission import Submission
from app.question_bank.functional import (
    FunctionalFormatError,
    functional_results_equal,
    parse_expected_result,
    solution_method,
)
from app.schemas.execution import ExecutionResult
from app.services.database_service import (
    DatabasePersistenceError,
    QuestionNotFoundError,
    get_evaluation_result,
    get_submission_for_evaluation,
    SubmissionExecutionIncompleteError,
)
from app.services.sandbox_service import DockerSandboxService


def normalize_output(value: str) -> str:
    """Normalize line endings and only trailing whitespace differences."""
    return value.replace("\r\n", "\n").replace("\r", "\n").rstrip()


def _case_detail(
    test_case: QuestionTestCase,
    execution: ExecutionResult,
    passed: bool,
) -> dict[str, Any]:
    return {
        "test_case_id": str(test_case.id),
        "description": test_case.description,
        "passed": passed,
        "status": execution.status,
        "stdout": execution.stdout,
        "stderr": execution.stderr
        if execution.status != "sandbox_error"
        else "Test execution could not be completed.",
    }


async def evaluate_submission(
    session: AsyncSession,
    submission_id: UUID,
    sandbox_service: DockerSandboxService,
) -> EvaluationResult:
    existing = await get_evaluation_result(session, submission_id)
    if existing is not None:
        return existing

    submission = await get_submission_for_evaluation(session, submission_id)
    if submission.status in {"queued", "running", "pending"}:
        raise SubmissionExecutionIncompleteError
    test_cases = list(
        await session.scalars(
            select(QuestionTestCase)
            .where(QuestionTestCase.question_id == submission.question_id)
            .order_by(QuestionTestCase.created_at.asc(), QuestionTestCase.id.asc())
        )
    )
    if not test_cases:
        result = EvaluationResult(
            submission_id=submission.id,
            total_test_cases=0,
            passed_test_cases=0,
            failed_test_cases=0,
            score=None,
            status="not_scored",
            case_results=[],
        )
        session.add(result)
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise DatabasePersistenceError from exc
        await session.refresh(result)
        return result

    question = await session.get(Question, submission.question_id)
    functional_method = None
    if any(test_case.is_functional for test_case in test_cases) and question is not None:
        try:
            functional_method = solution_method(question.starter_code).name
        except FunctionalFormatError:
            pass

    details: list[dict[str, Any]] = []
    passed_count = 0
    for index, test_case in enumerate(test_cases):
        if test_case.is_functional and (
            submission.language != "python" or functional_method is None
        ):
            execution = ExecutionResult(
                status="runtime_error",
                stderr="Unsupported functional execution format.",
                exit_code=1,
                execution_time_ms=0,
            )
        else:
            execution = await asyncio.to_thread(
                sandbox_service.execute,
                language=submission.language,
                source_code=submission.source_code,
                stdin=test_case.stdin,
                **(
                    {"functional_method": functional_method}
                    if test_case.is_functional
                    else {}
                ),
            )

        if test_case.is_functional:
            try:
                actual = parse_expected_result(execution.stdout)
                expected = parse_expected_result(test_case.expected_stdout)
                output_matches = functional_results_equal(actual, expected)
            except FunctionalFormatError:
                output_matches = False
        else:
            output_matches = (
                normalize_output(execution.stdout)
                == normalize_output(test_case.expected_stdout)
            )
        passed = (
            execution.status == "success"
            and output_matches
            and (
                test_case.time_limit_ms is None
                or execution.execution_time_ms <= test_case.time_limit_ms
            )
        )
        if passed:
            passed_count += 1
        details.append(_case_detail(test_case, execution, passed))
        if execution.status == "sandbox_error":
            for remaining_case in test_cases[index + 1 :]:
                details.append(
                    {
                        "test_case_id": str(remaining_case.id),
                        "description": remaining_case.description,
                        "passed": False,
                        "status": "sandbox_error",
                        "stdout": "",
                        "stderr": "Test execution could not be completed.",
                    }
                )
            break

    result = EvaluationResult(
        submission_id=submission.id,
        total_test_cases=len(test_cases),
        passed_test_cases=passed_count,
        failed_test_cases=len(test_cases) - passed_count,
        score=passed_count / len(test_cases) * 100,
        status="scored",
        case_results=details,
    )
    session.add(result)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        raise DatabasePersistenceError from exc
    await session.refresh(result)
    return result
