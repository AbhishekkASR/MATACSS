"""Focused coverage for the deterministic LangGraph foundation."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.interview import InterviewStatus
from app.orchestration.assessment_graph import (
    AssessmentGraphValidationError,
    build_assessment_graph,
    invoke_assessment_graph,
)
from app.schemas.assessment_state import (
    AssessmentProgressState,
    AssessmentQuestionState,
    AssessmentState,
)


def assessment_state(status: InterviewStatus = InterviewStatus.ACTIVE) -> AssessmentState:
    now = datetime.now(timezone.utc)
    question = AssessmentQuestionState(
        question_id=uuid4(),
        sequence_number=1,
        title="Public question",
        description="Public prompt",
        difficulty="easy",
        expected_language="python",
        evaluation_status="not_attempted",
    )
    is_active = status == InterviewStatus.ACTIVE
    return AssessmentState(
        interview_session_id=uuid4(),
        candidate_id=uuid4(),
        assessment_status=status,
        started_at=now if is_active else None,
        completed_at=None if is_active else now,
        created_at=now,
        generated_at=now,
        assigned_questions=(question,),
        current_question_id=question.question_id if is_active else None,
        progress=AssessmentProgressState(
            total_questions=1,
            attempted_questions=0,
            evaluated_questions=0,
            current_question_index=0 if is_active else None,
        ),
    )


def test_graph_construction_has_generator_and_terminal_path() -> None:
    graph = build_assessment_graph()
    graph_definition = graph.get_graph()
    assert {"__start__", "assessment_context", "interviewer", "prepare_real_assessment_context",
            "code_reviewer", "prepare_edge_case_context", "edge_case_generator",
            "orchestrator", "feedback_aggregator", "__end__"} <= set(
        graph_definition.nodes
    )
    assert len(graph_definition.edges) == 9


def test_graph_preserves_valid_active_assessment_state() -> None:
    state = assessment_state()
    result = invoke_assessment_graph(state)
    assert result.context_initialized is True
    assert result.assessment_state == state
    assert result.assessment_state is not state
    assert result.assessment_state.current_question_id == state.current_question_id
    assert result.interviewer_decision.question_id == state.current_question_id
    assert result.code_review.review_status == "not_run"
    assert result.edge_case_generation.question_id == state.current_question_id


@pytest.mark.parametrize("status", [InterviewStatus.COMPLETED, InterviewStatus.CANCELLED])
def test_graph_supports_closed_assessment_states(status: InterviewStatus) -> None:
    state = assessment_state(status)
    result = invoke_assessment_graph(state)
    assert result.assessment_state.assessment_status == status
    assert result.assessment_state.current_question_id is None


def test_graph_rejects_invalid_assessment_state_at_boundary() -> None:
    valid = assessment_state()
    invalid_values = {
        field_name: getattr(valid, field_name)
        for field_name in AssessmentState.model_fields
    }
    invalid_values["current_question_id"] = None
    invalid = AssessmentState.model_construct(**invalid_values)
    with pytest.raises(AssessmentGraphValidationError, match="valid AssessmentState"):
        invoke_assessment_graph(invalid)


def test_graph_execution_is_deterministic_and_requires_no_external_agent() -> None:
    state = assessment_state()
    first = invoke_assessment_graph(state)
    second = invoke_assessment_graph(state)
    assert first == second
    assert first.assessment_state.model_dump() == state.model_dump()
