"""Step 31 coverage for persisted-assessment orchestration preparation."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.interview import InterviewStatus
from app.orchestration.assessment_graph import invoke_assessment_graph
from app.services import assessment_orchestration_service as service
from app.services.assessment_orchestration_service import (
    AssessmentOrchestrationPreparationError,
    prepare_real_assessment_context,
    run_real_assessment_orchestration,
)
from app.schemas.assessment_state import (
    AssessmentProgressState,
    AssessmentQuestionState,
    AssessmentState,
)


def make_state(status: InterviewStatus = InterviewStatus.ACTIVE) -> AssessmentState:
    now = datetime.now(timezone.utc)
    question = AssessmentQuestionState(
        question_id=uuid4(),
        sequence_number=1,
        title="Array question",
        description="Given an array of integers, process the elements.",
        difficulty="easy",
        expected_language="python",
        evaluation_status="not_attempted",
    )
    active = status == InterviewStatus.ACTIVE
    return AssessmentState(
        interview_session_id=uuid4(),
        candidate_id=uuid4(),
        assessment_status=status,
        started_at=now if active else None,
        completed_at=None if active else now,
        created_at=now,
        generated_at=now,
        assigned_questions=(question,),
        current_question_id=question.question_id if active else None,
        progress=AssessmentProgressState(
            total_questions=1,
            attempted_questions=0,
            evaluated_questions=0,
            current_question_index=0 if active else None,
        ),
    )


def run(coro):
    return asyncio.run(coro)


def patch_state(monkeypatch, state: AssessmentState) -> None:
    async def build(_session, _id):
        return state

    monkeypatch.setattr(service, "build_assessment_state", build)


def test_active_assigned_question_prepares_public_context_and_no_submission(
    monkeypatch,
) -> None:
    state = make_state()
    patch_state(monkeypatch, state)

    async def no_submission(*_args):
        raise service.SubmissionAttemptNotFoundError

    monkeypatch.setattr(service, "get_latest_submission", no_submission)
    context = run(prepare_real_assessment_context(object(), state.interview_session_id))
    assert context.review_input is None
    assert context.edge_case_input.question_id == state.current_question_id
    assert context.edge_case_input.execution_summary.evaluation_status == "not_attempted"


@pytest.mark.parametrize(
    ("evaluation", "expected_status"),
    [
        (None, "attempted_not_evaluated"),
        (
            SimpleNamespace(
                score=80.0,
                passed_test_cases=4,
                total_test_cases=5,
            ),
            "evaluated",
        ),
    ],
)
def test_latest_submission_and_evaluation_summary_are_safe(
    monkeypatch, evaluation, expected_status
) -> None:
    state = make_state()
    question = state.assigned_questions[0]
    latest = SimpleNamespace(
        id=uuid4(),
        interview_session_id=state.interview_session_id,
        question_id=question.question_id,
        status="success",
        source_code="print('candidate')",
    )
    patch_state(monkeypatch, state)

    async def latest_submission(*_args):
        return latest

    async def evaluation_result(*_args):
        return evaluation

    monkeypatch.setattr(service, "get_latest_submission", latest_submission)
    monkeypatch.setattr(service, "get_evaluation_result", evaluation_result)
    context = run(prepare_real_assessment_context(object(), state.interview_session_id))
    assert context.review_input.source_code == latest.source_code
    assert context.review_input.execution_summary.evaluation_status == expected_status
    assert "source_code" not in context.edge_case_input.model_dump()
    assert "candidate" not in context.edge_case_input.model_dump_json()


def test_wrong_submission_boundary_is_rejected(monkeypatch) -> None:
    state = make_state()
    patch_state(monkeypatch, state)
    wrong = SimpleNamespace(
        id=uuid4(),
        interview_session_id=uuid4(),
        question_id=uuid4(),
        status="success",
        source_code="unsafe",
    )

    async def latest_submission(*_args):
        return wrong

    monkeypatch.setattr(service, "get_latest_submission", latest_submission)
    with pytest.raises(AssessmentOrchestrationPreparationError, match="does not belong"):
        run(prepare_real_assessment_context(object(), state.interview_session_id))


@pytest.mark.parametrize("status", [InterviewStatus.COMPLETED, InterviewStatus.CANCELLED])
def test_inactive_assessment_does_not_load_submission_or_prepare_review(
    monkeypatch, status
) -> None:
    state = make_state(status)
    patch_state(monkeypatch, state)
    async def should_not_load(*_args):
        pytest.fail("latest submission must not be loaded")

    monkeypatch.setattr(service, "get_latest_submission", should_not_load)
    context = run(prepare_real_assessment_context(object(), state.interview_session_id))
    assert context.review_input is None
    assert context.edge_case_input is None


def test_real_context_runs_existing_graph_deterministically(monkeypatch) -> None:
    state = make_state()
    patch_state(monkeypatch, state)

    async def no_submission(*_args):
        raise service.SubmissionAttemptNotFoundError

    monkeypatch.setattr(service, "get_latest_submission", no_submission)
    first = run(run_real_assessment_orchestration(object(), state.interview_session_id))
    second = run(run_real_assessment_orchestration(object(), state.interview_session_id))
    assert first == second
    assert first.assessment_state == state
