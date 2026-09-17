"""Focused coverage for the bounded deterministic Interviewer Agent."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.models.interview import InterviewStatus
from app.orchestration.assessment_graph import (
    AssessmentGraphValidationError,
    build_assessment_graph,
    invoke_assessment_graph,
)
from app.orchestration.interviewer import (
    DeterministicInterviewerProvider,
    InterviewerAgent,
    InterviewerAgentError,
    InterviewerDecision,
    InterviewerDecisionType,
    InterviewerProvider,
    InterviewerProviderSelection,
)
from app.schemas.assessment_state import (
    AssessmentProgressState,
    AssessmentQuestionState,
    AssessmentState,
)


def make_state(
    *,
    status: InterviewStatus = InterviewStatus.ACTIVE,
    question_count: int = 2,
    first_attempted: bool = False,
) -> AssessmentState:
    now = datetime.now(timezone.utc)
    questions: list[AssessmentQuestionState] = []
    for index in range(question_count):
        attempted = first_attempted and index == 0
        questions.append(
            AssessmentQuestionState(
                question_id=uuid4(),
                sequence_number=index + 1,
                title=f"Question {index + 1}",
                description=f"Public prompt {index + 1}",
                difficulty="easy",
                expected_language="python",
                latest_submission_id=uuid4() if attempted else None,
                latest_submission_status="success" if attempted else None,
                latest_submission_created_at=now if attempted else None,
                evaluation_status="attempted_not_evaluated" if attempted else "not_attempted",
            )
        )
    active = status == InterviewStatus.ACTIVE
    current_index = next(
        (index for index, question in enumerate(questions) if question.latest_submission_id is None),
        None,
    ) if active else None
    return AssessmentState(
        interview_session_id=uuid4(),
        candidate_id=uuid4(),
        assessment_status=status,
        started_at=now if active else None,
        completed_at=None if active else now,
        created_at=now,
        generated_at=now,
        assigned_questions=tuple(questions),
        current_question_id=(questions[current_index].question_id if current_index is not None else None),
        progress=AssessmentProgressState(
            total_questions=len(questions),
            attempted_questions=sum(question.latest_submission_id is not None for question in questions),
            evaluated_questions=0,
            current_question_index=current_index,
        ),
    )


class RecordingProvider:
    def __init__(self) -> None:
        self.received: list[AssessmentState] = []

    def select_question(self, assessment_state: AssessmentState) -> InterviewerProviderSelection:
        self.received.append(assessment_state)
        return InterviewerProviderSelection(
            selected_question_id=assessment_state.current_question_id,
            reason="Recorded current-question selection.",
        )


class InventedQuestionProvider:
    def select_question(self, assessment_state: AssessmentState) -> InterviewerProviderSelection:
        return InterviewerProviderSelection(
            selected_question_id=uuid4(),
            reason="This selection must be rejected.",
        )


class NonCurrentAssignedProvider:
    def select_question(self, assessment_state: AssessmentState) -> InterviewerProviderSelection:
        return InterviewerProviderSelection(
            selected_question_id=assessment_state.assigned_questions[0].question_id,
            reason="This non-current selection must be rejected.",
        )


def test_active_agent_selects_only_current_assigned_question() -> None:
    state = make_state(first_attempted=True)
    provider = RecordingProvider()
    decision = InterviewerAgent(provider).decide(state)
    assert decision.decision_type == InterviewerDecisionType.PRESENT_QUESTION
    assert decision.question_id == state.current_question_id
    assert decision.question_id in {item.question_id for item in state.assigned_questions}
    assert decision.question_index == 1
    assert decision.question_title == "Question 2"
    assert decision.question_prompt == "Public prompt 2"
    assert provider.received == [state]


def test_deterministic_provider_requires_no_api_key_or_network(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    state = make_state()
    provider = DeterministicInterviewerProvider()
    assert isinstance(provider, InterviewerProvider)
    first = InterviewerAgent(provider).decide(state)
    second = InterviewerAgent(provider).decide(state)
    assert first == second
    assert first.question_id == state.current_question_id


def test_empty_active_assessment_returns_safe_non_question_decision() -> None:
    decision = InterviewerAgent(DeterministicInterviewerProvider()).decide(
        make_state(question_count=0)
    )
    assert decision.decision_type == InterviewerDecisionType.NO_ASSIGNED_QUESTIONS
    assert decision.question_id is None


def test_fully_attempted_active_assessment_returns_safe_non_question_decision() -> None:
    decision = InterviewerAgent(DeterministicInterviewerProvider()).decide(
        make_state(question_count=1, first_attempted=True)
    )
    assert decision.decision_type == InterviewerDecisionType.ALL_QUESTIONS_ATTEMPTED
    assert decision.question_id is None


@pytest.mark.parametrize("status", [InterviewStatus.COMPLETED, InterviewStatus.CANCELLED])
def test_closed_assessments_do_not_present_questions(status: InterviewStatus) -> None:
    decision = InterviewerAgent(DeterministicInterviewerProvider()).decide(
        make_state(status=status)
    )
    assert decision.decision_type == InterviewerDecisionType.ASSESSMENT_CLOSED
    assert decision.question_id is None


def test_provider_cannot_invent_or_select_unassigned_question() -> None:
    with pytest.raises(InterviewerAgentError, match="outside this assessment"):
        InterviewerAgent(InventedQuestionProvider()).decide(make_state())


def test_provider_cannot_select_an_assigned_but_noncurrent_question() -> None:
    with pytest.raises(InterviewerAgentError, match="other than the current question"):
        InterviewerAgent(NonCurrentAssignedProvider()).decide(make_state(first_attempted=True))


def test_invalid_state_and_invalid_structured_output_are_rejected() -> None:
    valid = make_state()
    invalid_values = {
        field_name: getattr(valid, field_name)
        for field_name in AssessmentState.model_fields
    }
    invalid_values["current_question_id"] = None
    invalid = AssessmentState.model_construct(**invalid_values)
    with pytest.raises(InterviewerAgentError, match="valid AssessmentState"):
        InterviewerAgent(DeterministicInterviewerProvider()).decide(invalid)
    with pytest.raises(ValidationError, match="complete question context"):
        InterviewerDecision(
            decision_type=InterviewerDecisionType.PRESENT_QUESTION,
            reason="Invalid incomplete decision.",
        )


def test_graph_flow_runs_context_then_injected_interviewer() -> None:
    provider = RecordingProvider()
    graph = build_assessment_graph(provider)
    graph_definition = graph.get_graph()
    assert {"__start__", "assessment_context", "interviewer", "code_reviewer", "__end__"} <= set(
        graph_definition.nodes
    )
    assert len(graph_definition.edges) == 4
    result = invoke_assessment_graph(make_state(), provider)
    assert result.context_initialized is True
    assert result.interviewer_decision.decision_type == InterviewerDecisionType.PRESENT_QUESTION
    assert len(provider.received) == 1


def test_graph_rejects_invalid_state_before_provider_execution() -> None:
    valid = make_state()
    invalid_values = {
        field_name: getattr(valid, field_name)
        for field_name in AssessmentState.model_fields
    }
    invalid_values["current_question_id"] = None
    invalid = AssessmentState.model_construct(**invalid_values)
    with pytest.raises(AssessmentGraphValidationError, match="valid AssessmentState"):
        invoke_assessment_graph(invalid)
