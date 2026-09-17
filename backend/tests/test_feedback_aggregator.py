"""Focused coverage for the deterministic feedback aggregator."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.models.interview import InterviewStatus
from app.orchestration.assessment_graph import build_assessment_graph, invoke_assessment_graph
from app.orchestration.code_reviewer import (
    CodeReviewInput,
    CodeReviewObservation,
    CodeReviewResult,
)
from app.orchestration.edge_case_generator import (
    EdgeCaseCategory,
    EdgeCaseGenerationResult,
    EdgeCaseGeneratorInput,
    GeneratedEdgeCase,
    VerificationStatus,
)
from app.orchestration.feedback_aggregator import (
    DeterministicFeedbackAggregator,
    FeedbackAggregationResult,
    FeedbackStatus,
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


def review_input(state: AssessmentState) -> CodeReviewInput:
    question = state.assigned_questions[0]
    return CodeReviewInput(
        question_id=question.question_id,
        question_title=question.title,
        question_prompt=question.description,
        language="python",
        source_code="print(1)\n",
    )


def edge_input(state: AssessmentState) -> EdgeCaseGeneratorInput:
    question = state.assigned_questions[0]
    return EdgeCaseGeneratorInput(
        question_id=question.question_id,
        question_title=question.title,
        question_prompt=question.description,
        language="python",
    )


class StubReviewProvider:
    def __init__(self) -> None:
        self.calls = 0

    def review(self, value: CodeReviewInput) -> CodeReviewResult:
        self.calls += 1
        return CodeReviewResult(
            review_status="completed",
            question_id=value.question_id,
            correctness_summary="The code is likely correct according to the static review.",
            observations=(
                    CodeReviewObservation(
                        category="code_quality",
                        severity="info",
                        message="The solution is concise and readable.",
                    ),
            ),
            improvement_suggestions=("Keep edge conditions explicit in the final implementation.",),
            reason="Static review completed without runtime execution.",
        )


class StubGeneratorProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, value: EdgeCaseGeneratorInput) -> EdgeCaseGenerationResult:
        self.calls += 1
        return EdgeCaseGenerationResult(
            question_id=value.question_id,
            cases=(
                GeneratedEdgeCase(
                    case_id="edge-01-empty_input",
                    category=EdgeCaseCategory.EMPTY_INPUT,
                    input_data="",
                    rationale="Checks empty input handling.",
                    confidence=0.8,
                    verification_status=VerificationStatus.UNVERIFIED,
                ),
                GeneratedEdgeCase(
                    case_id="edge-02-duplicate_values",
                    category=EdgeCaseCategory.DUPLICATE_VALUES,
                    input_data="1 1",
                    rationale="Checks duplicate values.",
                    confidence=0.7,
                    verification_status=VerificationStatus.UNVERIFIED,
                ),
            ),
            reason="Deterministic candidate edge cases were produced from the public prompt only.",
        )


def test_feedback_aggregator_combines_evaluation_and_agent_output() -> None:
    state = make_state()
    review_provider = StubReviewProvider()
    generator_provider = StubGeneratorProvider()
    result = invoke_assessment_graph(
        state,
        code_reviewer_provider=review_provider,
        edge_case_generator_provider=generator_provider,
        review_input=review_input(state),
        edge_case_input=edge_input(state),
    )

    assert result.feedback_result is not None
    assert result.feedback_result.status == FeedbackStatus.GENERATED
    assert "official evaluation" in result.feedback_result.assessment.summary.lower() or "No official evaluation" in result.feedback_result.assessment.summary
    assert result.feedback_result.code_quality is not None
    assert result.feedback_result.code_quality.status == FeedbackStatus.GENERATED
    assert result.feedback_result.edge_cases is not None
    assert result.feedback_result.edge_cases.unverified_count == 2
    assert result.feedback_result.edge_cases.categories == ("empty_input", "duplicate_values")
    assert review_provider.calls == 1
    assert generator_provider.calls == 1


def test_feedback_aggregator_preserves_official_evaluation_precedence() -> None:
    now = datetime.now(timezone.utc)
    first_question = AssessmentQuestionState(
        question_id=uuid4(),
        sequence_number=1,
        title="Past question",
        description="This question was already evaluated.",
        difficulty="easy",
        expected_language="python",
        latest_submission_id=uuid4(),
        latest_submission_status="completed",
        latest_submission_created_at=now,
        evaluation_result_id=uuid4(),
        evaluation_status="evaluated",
        score=10.0,
        passed_test_cases=1,
        total_test_cases=10,
    )
    second_question = AssessmentQuestionState(
        question_id=uuid4(),
        sequence_number=2,
        title="Current question",
        description="This question is active and not yet evaluated.",
        difficulty="easy",
        expected_language="python",
        evaluation_status="not_attempted",
    )
    state = AssessmentState(
        interview_session_id=uuid4(),
        candidate_id=uuid4(),
        assessment_status=InterviewStatus.ACTIVE,
        started_at=now,
        completed_at=None,
        created_at=now,
        generated_at=now,
        assigned_questions=(first_question, second_question),
        current_question_id=second_question.question_id,
        progress=AssessmentProgressState(
            total_questions=2,
            attempted_questions=1,
            evaluated_questions=1,
            current_question_index=1,
        ),
    )
    review_result = CodeReviewResult(
        review_status="completed",
        question_id=first_question.question_id,
        correctness_summary="This code is definitely correct and should pass all tests.",
        observations=(
            CodeReviewObservation(
                category="correctness",
                severity="warning",
                message="This is a static observation only.",
            ),
        ),
        improvement_suggestions=("Do not trust this as a correctness claim.",),
        reason="A static observation is being used to validate aggregation behavior.",
    )
    edge_result = EdgeCaseGenerationResult(
        question_id=first_question.question_id,
        cases=(
            GeneratedEdgeCase(
                case_id="edge-01-empty_input",
                category=EdgeCaseCategory.EMPTY_INPUT,
                input_data="",
                rationale="Checks empty input handling.",
                confidence=0.8,
                verification_status=VerificationStatus.UNVERIFIED,
            ),
        ),
        reason="Candidate cases are advisory only.",
    )
    decision = {
        "decision_type": "present_question",
        "question_id": first_question.question_id,
        "question_sequence_number": 1,
        "question_index": 0,
        "question_title": first_question.title,
        "question_prompt": first_question.description,
        "reason": "This evaluated question is the subject of the feedback aggregate.",
    }
    agg = DeterministicFeedbackAggregator()
    result = agg.aggregate(
        {
            "assessment_state": state,
            "interviewer_decision": decision,
            "code_review": review_result,
            "edge_case_generation": edge_result,
        }
    )
    assert "1/10" in result.assessment.summary
    assert "score 10.0/100" in result.assessment.summary
    assert "official evaluation" in result.assessment.summary.lower()
    assert result.edge_cases is not None
    assert result.edge_cases.unverified_count == 1


def test_feedback_aggregator_missing_outputs_are_marked_incomplete() -> None:
    state = make_state()
    result = invoke_assessment_graph(state)
    assert result.feedback_result is not None
    assert result.feedback_result.status in {FeedbackStatus.GENERATED, FeedbackStatus.INCOMPLETE}
    assert result.feedback_result.code_quality is not None
    assert result.feedback_result.code_quality.status == FeedbackStatus.INCOMPLETE
    assert result.feedback_result.edge_cases is not None
    assert result.feedback_result.edge_cases.status in {FeedbackStatus.GENERATED, FeedbackStatus.INCOMPLETE}


def test_feedback_aggregator_rejects_malformed_provider_output() -> None:
    class BadProvider:
        def aggregate(self, aggregation_input):
            return {"assessment": {"status": "generated"}}

    with pytest.raises(ValueError, match="rejected the provider output"):
        invoke_assessment_graph(
            make_state(),
            feedback_aggregator_provider=BadProvider(),
        )


@pytest.mark.parametrize("status", [InterviewStatus.COMPLETED, InterviewStatus.CANCELLED])
def test_feedback_aggregator_blocks_closed_assessments(status: InterviewStatus) -> None:
    state = make_state(status)
    result = invoke_assessment_graph(state)
    assert result.feedback_result is not None
    assert result.feedback_result.status == FeedbackStatus.BLOCKED
    assert result.feedback_result.question.status == FeedbackStatus.BLOCKED


def test_graph_has_feedback_node_at_end_of_topology() -> None:
    graph = build_assessment_graph()
    nodes = graph.get_graph().nodes
    assert "feedback_aggregator" in nodes
    assert len(graph.get_graph().edges) == 9
