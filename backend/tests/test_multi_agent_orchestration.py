"""Focused Step 30 coverage for explicit multi-agent handoffs."""

from datetime import datetime, timezone
import socket
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.models.interview import InterviewStatus
from app.orchestration.assessment_graph import (
    AssessmentGraphValidationError,
    build_assessment_graph,
    invoke_assessment_graph,
)
from app.orchestration.code_reviewer import (
    CodeReviewInput,
    CodeReviewResult,
    DeterministicCodeReviewerProvider,
)
from app.orchestration.edge_case_generator import (
    DeterministicEdgeCaseGeneratorProvider,
    EdgeCaseGenerationResult,
    EdgeCaseGeneratorInput,
)
from app.orchestration.multi_agent_orchestrator import (
    AgentExecutionStatus,
    OrchestrationStatus,
)
from app.services import database_service
from app.services.sandbox_service import DockerSandboxService
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


def review_input(state: AssessmentState, question_id=None) -> CodeReviewInput:
    question = state.assigned_questions[0]
    return CodeReviewInput(
        question_id=question_id or question.question_id,
        question_title=question.title,
        question_prompt=question.description,
        language="python",
        source_code="print(1)\n",
    )


def edge_input(state: AssessmentState, question_id=None) -> EdgeCaseGeneratorInput:
    question = state.assigned_questions[0]
    return EdgeCaseGeneratorInput(
        question_id=question_id or question.question_id,
        question_title=question.title,
        question_prompt=question.description,
        language="python",
    )


class RecordingReviewer:
    def __init__(self) -> None:
        self.inputs: list[CodeReviewInput] = []
        self.provider = DeterministicCodeReviewerProvider()

    def review(self, value: CodeReviewInput) -> CodeReviewResult:
        self.inputs.append(value)
        return self.provider.review(value)


class RecordingGenerator:
    def __init__(self) -> None:
        self.inputs: list[EdgeCaseGeneratorInput] = []
        self.provider = DeterministicEdgeCaseGeneratorProvider()

    def generate(self, value: EdgeCaseGeneratorInput) -> EdgeCaseGenerationResult:
        self.inputs.append(value)
        return self.provider.generate(value)


def test_complete_three_agent_happy_path_has_validated_handoffs() -> None:
    state = make_state()
    reviewer = RecordingReviewer()
    generator = RecordingGenerator()
    result = invoke_assessment_graph(
        state,
        code_reviewer_provider=reviewer,
        edge_case_generator_provider=generator,
        review_input=review_input(state),
        edge_case_input=edge_input(state),
    )
    assert result.status == OrchestrationStatus.COMPLETED
    assert result.execution.code_reviewer == AgentExecutionStatus.COMPLETED
    assert result.execution.edge_case_generator == AgentExecutionStatus.COMPLETED
    assert reviewer.inputs[0].question_id == result.interviewer_decision.question_id
    assert generator.inputs[0].question_id == result.interviewer_decision.question_id
    assert generator.inputs[0].code_review_summary is None


def test_reviewer_summary_is_safe_edge_case_handoff() -> None:
    state = make_state()
    reviewer = RecordingReviewer()
    generator = RecordingGenerator()
    result = invoke_assessment_graph(
        state,
        code_reviewer_provider=reviewer,
        edge_case_generator_provider=generator,
        review_input=review_input(state),
    )
    assert result.code_review is not None
    assert generator.inputs[0].code_review_summary == result.code_review.correctness_summary


def test_question_mismatch_is_rejected_before_provider_work() -> None:
    state = make_state()
    reviewer = RecordingReviewer()
    with pytest.raises(AssessmentGraphValidationError, match="review input question"):
        invoke_assessment_graph(
            state,
            code_reviewer_provider=reviewer,
            review_input=review_input(state, uuid4()),
        )
    assert reviewer.inputs == []

    with pytest.raises(AssessmentGraphValidationError, match="edge-case context"):
        invoke_assessment_graph(state, edge_case_input=edge_input(state, uuid4()))


def test_missing_review_input_skips_reviewer_provider_safely() -> None:
    state = make_state()
    reviewer = Mock(side_effect=AssertionError("reviewer must not run"))
    result = invoke_assessment_graph(state, code_reviewer_provider=reviewer)
    assert result.code_review is not None
    assert result.code_review.review_status == "not_run"
    assert result.execution.code_reviewer == AgentExecutionStatus.NOT_RUN
    reviewer.assert_not_called()


@pytest.mark.parametrize("status", [InterviewStatus.COMPLETED, InterviewStatus.CANCELLED])
def test_closed_assessments_gate_all_inappropriate_provider_work(status: InterviewStatus) -> None:
    state = make_state(status)
    interviewer = Mock(side_effect=AssertionError("interviewer must not run"))
    reviewer = Mock(side_effect=AssertionError("reviewer must not run"))
    generator = Mock(side_effect=AssertionError("generator must not run"))
    result = invoke_assessment_graph(
        state,
        interviewer_provider=interviewer,
        code_reviewer_provider=reviewer,
        edge_case_generator_provider=generator,
    )
    assert result.status == OrchestrationStatus.ASSESSMENT_CLOSED
    interviewer.assert_not_called()
    reviewer.assert_not_called()
    generator.assert_not_called()


def test_malformed_provider_output_is_rejected() -> None:
    class MalformedReviewer:
        def review(self, value: CodeReviewInput):
            return {"review_status": "completed"}

    state = make_state()
    with pytest.raises(ValueError, match="invalid code review"):
        invoke_assessment_graph(
            state,
            code_reviewer_provider=MalformedReviewer(),
            review_input=review_input(state),
        )


def test_repeated_orchestration_is_deterministic_and_state_is_unchanged() -> None:
    state = make_state()
    before = state.model_dump()
    first = invoke_assessment_graph(state, review_input=review_input(state))
    second = invoke_assessment_graph(state, review_input=review_input(state))
    assert first == second
    assert state.model_dump() == before


def test_orchestration_has_no_docker_database_or_network_authority(monkeypatch) -> None:
    network = Mock(side_effect=AssertionError("network must not be called"))
    docker = Mock(side_effect=AssertionError("Docker must not be called"))
    persistence = Mock(side_effect=AssertionError("persistence must not be called"))
    monkeypatch.setattr(socket, "create_connection", network)
    monkeypatch.setattr(DockerSandboxService, "execute", docker)
    monkeypatch.setattr(database_service, "create_submission", persistence)
    state = make_state()
    invoke_assessment_graph(state, review_input=review_input(state))
    network.assert_not_called()
    docker.assert_not_called()
    persistence.assert_not_called()


def test_graph_has_explicit_step_30_topology() -> None:
    nodes = set(build_assessment_graph().get_graph().nodes)
    assert {
        "__start__",
        "assessment_context",
        "interviewer",
        "prepare_real_assessment_context",
        "code_reviewer",
        "prepare_edge_case_context",
        "edge_case_generator",
        "orchestrator",
        "__end__",
    } <= nodes
