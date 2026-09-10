"""Business logic for coordinating persistent code submissions."""

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.interview import InterviewSession
from app.models.question import Question
from app.schemas.execution import ExecutionResult
from app.schemas.submission import CodeSubmissionRequest, CodeSubmissionResponse
from app.services.database_service import (
    DatabasePersistenceError,
    InactiveInterviewSessionError,
    InterviewSessionNotFoundError,
    QuestionNotFoundError,
    ensure_question_assigned,
    create_submission,
)
from app.services.execution_queue import enqueue_job
from app.services.sandbox_service import DockerSandboxService


async def execute_submission(
    request: CodeSubmissionRequest,
    sandbox_service: DockerSandboxService,
    session: AsyncSession,
) -> CodeSubmissionResponse:
    """Persist, execute, and persist the result of a validated submission."""
    interview = await session.scalar(
        select(InterviewSession).where(
            InterviewSession.id == request.interview_session_id
        )
    )
    if interview is None:
        raise InterviewSessionNotFoundError
    candidate = await session.scalar(
        select(Candidate).where(Candidate.id == interview.candidate_id)
    )
    if candidate is None:
        raise InterviewSessionNotFoundError
    if interview.status != "active":
        raise InactiveInterviewSessionError
    question = await session.scalar(
        select(Question).where(Question.id == request.question_id)
    )
    if question is None:
        raise QuestionNotFoundError
    await ensure_question_assigned(session, interview.id, question.id)

    try:
        submission = await create_submission(
            session,
            interview.id,
            question.id,
            request.language,
            request.source_code,
            request.stdin,
        )
        execution = await asyncio.to_thread(
            sandbox_service.execute,
            language=request.language,
            source_code=request.source_code,
            stdin=request.stdin,
        )
        submission = await store_execution_result(session, submission, execution)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise DatabasePersistenceError from exc
    return _build_response(str(submission.id), request, execution)


async def enqueue_submission(
    request: CodeSubmissionRequest, session: AsyncSession
) -> tuple[str, str]:
    """Validate an assessment submission and persist it with one queued job."""
    interview = await session.scalar(
        select(InterviewSession).where(
            InterviewSession.id == request.interview_session_id
        )
    )
    if interview is None:
        raise InterviewSessionNotFoundError
    candidate = await session.scalar(
        select(Candidate).where(Candidate.id == interview.candidate_id)
    )
    if candidate is None:
        raise InterviewSessionNotFoundError
    if interview.status != "active":
        raise InactiveInterviewSessionError
    question = await session.scalar(
        select(Question).where(Question.id == request.question_id)
    )
    if question is None:
        raise QuestionNotFoundError
    await ensure_question_assigned(session, interview.id, question.id)

    submission = await create_submission(
        session,
        interview.id,
        question.id,
        request.language,
        request.source_code,
        request.stdin,
        commit=False,
        status="queued",
    )
    try:
        job = await enqueue_job(session, submission)
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise DatabasePersistenceError from exc
    return str(submission.id), str(job.id)


def _build_response(
    submission_id: str,
    request: CodeSubmissionRequest,
    execution: ExecutionResult,
) -> CodeSubmissionResponse:
    """Translate the internal execution result into the public response."""
    return CodeSubmissionResponse(
        submission_id=submission_id,
        job_id="",
        job_status="succeeded",
        interview_session_id=request.interview_session_id,
        question_id=request.question_id,
        status=execution.status,
        message=_message_for_status(execution.status),
        stdout=execution.stdout,
        stderr=execution.stderr,
        exit_code=execution.exit_code,
        execution_time_ms=execution.execution_time_ms,
        timed_out=execution.timed_out,
    )


def _message_for_status(status: str) -> str:
    if status == "success":
        return "Submission executed successfully."
    if status == "compilation_error":
        return "Submission failed to compile."
    if status == "runtime_error":
        return "Submission terminated with a runtime error."
    if status == "timeout":
        return "Submission exceeded the execution time limit."
    if status == "output_limit_exceeded":
        return "Submission exceeded the output limit."
    return "Sandbox execution failed."
