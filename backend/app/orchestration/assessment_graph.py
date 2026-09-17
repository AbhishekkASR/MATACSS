"""Side-effect-free LangGraph entry point for an AssessmentState snapshot."""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

from app.core.logging import sanitize_exception_message
from app.schemas.assessment_state import AssessmentState
from app.orchestration.interviewer import (
    DeterministicInterviewerProvider,
    InterviewerAgent,
    InterviewerDecision,
    InterviewerProvider,
)
from app.orchestration.code_reviewer import (
    CodeReviewInput,
    CodeReviewResult,
    CodeReviewerAgent,
    CodeReviewerProvider,
    DeterministicCodeReviewerProvider,
    validate_code_review_input,
    validate_code_review_result,
)
from app.orchestration.edge_case_generator import (
    DeterministicEdgeCaseGeneratorProvider,
    EdgeCaseGenerationResult,
    EdgeCaseGeneratorAgent,
    EdgeCaseGeneratorInput,
    EdgeCaseGeneratorProvider,
)
from app.orchestration.feedback_aggregator import (
    DeterministicFeedbackAggregator,
    FeedbackAggregationResult,
    FeedbackAggregator,
    FeedbackAggregatorProvider,
)
from app.orchestration.multi_agent_orchestrator import (
    MultiAgentOrchestrationResult,
)
from app.orchestration.state_adapter import (
    AssessmentGraphValidationError,
    validate_assessment_state,
)

logger = logging.getLogger(__name__)


class AssessmentGraphState(TypedDict):
    """Internal LangGraph state; AssessmentState remains the domain contract."""

    assessment_state: AssessmentState
    context_initialized: bool
    interviewer_decision: InterviewerDecision | None
    review_input: CodeReviewInput | None
    real_context_prepared: bool
    prepared_review_input: CodeReviewInput | None
    code_review: CodeReviewResult | None
    edge_case_input: EdgeCaseGeneratorInput | None
    prepared_edge_case_input: EdgeCaseGeneratorInput | None
    edge_case_generation: EdgeCaseGenerationResult | None
    orchestration_result: MultiAgentOrchestrationResult | None
    feedback_result: FeedbackAggregationResult | None


class AssessmentGraphResult(MultiAgentOrchestrationResult):
    """Backward-compatible typed result of the coordinated graph."""

    context_initialized: bool = True
    feedback_result: FeedbackAggregationResult | None = None


def assessment_context(state: AssessmentGraphState) -> dict[str, AssessmentState | bool]:
    """Validate and retain context without persistence, model calls, or side effects."""
    return {
        "assessment_state": validate_assessment_state(state["assessment_state"]),
        "context_initialized": True,
    }


def interviewer_node(provider: InterviewerProvider):
    """Create a LangGraph node with an injected, testable interviewer provider."""
    agent = InterviewerAgent(provider)

    def run(state: AssessmentGraphState) -> dict[str, InterviewerDecision]:
        return {"interviewer_decision": agent.decide(state["assessment_state"])}

    return run


def code_reviewer_node(provider: CodeReviewerProvider):
    """Create a LangGraph node with an injected static-review provider."""
    agent = CodeReviewerAgent(provider)

    def run(state: AssessmentGraphState) -> dict[str, CodeReviewResult]:
        return {
            "code_review": agent.review(
                state["assessment_state"], state.get("prepared_review_input")
            )
        }

    return run


def edge_case_generator_node(provider: EdgeCaseGeneratorProvider):
    """Create a node with explicitly prepared public generation context."""
    agent = EdgeCaseGeneratorAgent(provider)

    def run(state: AssessmentGraphState) -> dict[str, EdgeCaseGenerationResult]:
        return {
            "edge_case_generation": agent.generate(
                state["assessment_state"], state.get("prepared_edge_case_input")
            )
        }

    return run


def prepare_review_context(state: AssessmentGraphState) -> dict[str, CodeReviewInput | None]:
    """Validate that review input is explicitly for the interviewer-selected question."""
    decision = InterviewerDecision.model_validate(state.get("interviewer_decision"))
    review_input = validate_code_review_input(state.get("review_input"))
    if review_input is None or decision.question_id is None:
        return {"prepared_review_input": None}
    if review_input.question_id != decision.question_id:
        raise AssessmentGraphValidationError(
            "review input question must match the interviewer-selected question"
        )
    if (
        review_input.question_title != decision.question_title
        or review_input.question_prompt != decision.question_prompt
    ):
        raise AssessmentGraphValidationError(
            "review input public context must match the interviewer-selected question"
        )
    return {"prepared_review_input": review_input}


def prepare_real_assessment_context(
    state: AssessmentGraphState,
) -> dict[str, CodeReviewInput | bool | None]:
    """Validate application-prepared inputs after interviewer selection."""
    prepared = prepare_review_context(state)
    return {
        "prepared_review_input": prepared["prepared_review_input"],
        "real_context_prepared": True,
    }


def prepare_edge_case_context(
    state: AssessmentGraphState,
) -> dict[str, EdgeCaseGeneratorInput | None]:
    """Build edge-case context from the selected question and safe summaries only."""
    decision = InterviewerDecision.model_validate(state.get("interviewer_decision"))
    if decision.question_id is None:
        return {"prepared_edge_case_input": None}
    supplied = state.get("edge_case_input")
    if supplied is not None:
        supplied = EdgeCaseGeneratorInput.model_validate(supplied)
        if (
            supplied.question_id != decision.question_id
            or supplied.question_title != decision.question_title
            or supplied.question_prompt != decision.question_prompt
        ):
            raise AssessmentGraphValidationError(
                "edge-case context must match the interviewer-selected question"
            )
        return {"prepared_edge_case_input": supplied}
    assessment = validate_assessment_state(state["assessment_state"])
    selected = next(
        question for question in assessment.assigned_questions
        if question.question_id == decision.question_id
    )
    if selected.expected_language not in {"python", "cpp", "java"}:
        return {"prepared_edge_case_input": None}
    review = state.get("code_review")
    return {
        "prepared_edge_case_input": EdgeCaseGeneratorInput(
            question_id=decision.question_id,
            question_title=decision.question_title or selected.title,
            question_prompt=decision.question_prompt or selected.description,
            language=selected.expected_language,
            code_review_summary=(
                review.correctness_summary
                if review is not None and review.review_status != "not_run"
                else None
            ),
        )
    }


def orchestrator_node(state: AssessmentGraphState) -> dict[str, MultiAgentOrchestrationResult]:
    """Validate all completed handoffs and produce one final typed result."""
    assessment = validate_assessment_state(state["assessment_state"])
    decision = InterviewerDecision.model_validate(state.get("interviewer_decision"))
    review = validate_code_review_result(state.get("code_review"))
    edge_cases = EdgeCaseGenerationResult.model_validate(state.get("edge_case_generation"))
    return {
        "orchestration_result": MultiAgentOrchestrationResult.from_agents(
            assessment_state=assessment,
            interviewer_decision=decision,
            code_review=review,
            edge_case_generation=edge_cases,
        )
    }


def feedback_aggregator_node(provider: FeedbackAggregatorProvider):
    """Create a deterministic feedback node that keeps official evaluation authoritative."""
    aggregator = FeedbackAggregator(provider)

    def run(state: AssessmentGraphState) -> dict[str, FeedbackAggregationResult]:
        orchestration = state.get("orchestration_result")
        aggregation_input = {
            "assessment_state": validate_assessment_state(state["assessment_state"]),
            "interviewer_decision": state.get("interviewer_decision"),
            "code_review": validate_code_review_result(state.get("code_review")),
            "edge_case_generation": EdgeCaseGenerationResult.model_validate(
                state.get("edge_case_generation")
            ),
            "orchestration_result": MultiAgentOrchestrationResult.model_validate(orchestration),
        }
        return {"feedback_result": aggregator.aggregate(aggregation_input)}

    return run


def build_assessment_graph(
    interviewer_provider: InterviewerProvider | None = None,
    code_reviewer_provider: CodeReviewerProvider | None = None,
    edge_case_generator_provider: EdgeCaseGeneratorProvider | None = None,
    feedback_aggregator_provider: FeedbackAggregatorProvider | None = None,
) -> Any:
    """Compile START -> assessment_context -> interviewer -> code_reviewer -> edge_case_generator -> orchestrator -> feedback_aggregator -> END."""
    builder = StateGraph(AssessmentGraphState)
    builder.add_node("assessment_context", assessment_context)
    builder.add_node(
        "interviewer",
        interviewer_node(interviewer_provider or DeterministicInterviewerProvider()),
    )
    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node(
        "code_reviewer",
        code_reviewer_node(
            code_reviewer_provider or DeterministicCodeReviewerProvider()
        ),
    )
    builder.add_node("prepare_real_assessment_context", prepare_real_assessment_context)
    builder.add_node("prepare_edge_case_context", prepare_edge_case_context)
    builder.add_node(
        "edge_case_generator",
        edge_case_generator_node(
            edge_case_generator_provider or DeterministicEdgeCaseGeneratorProvider()
        ),
    )
    builder.add_node(
        "feedback_aggregator",
        feedback_aggregator_node(
            feedback_aggregator_provider or DeterministicFeedbackAggregator()
        ),
    )
    builder.add_edge(START, "assessment_context")
    builder.add_edge("assessment_context", "interviewer")
    builder.add_edge("interviewer", "prepare_real_assessment_context")
    builder.add_edge("prepare_real_assessment_context", "code_reviewer")
    builder.add_edge("code_reviewer", "prepare_edge_case_context")
    builder.add_edge("prepare_edge_case_context", "edge_case_generator")
    builder.add_edge("edge_case_generator", "orchestrator")
    builder.add_edge("orchestrator", "feedback_aggregator")
    builder.add_edge("feedback_aggregator", END)
    return builder.compile()


def invoke_assessment_graph(
    assessment_state: AssessmentState | object,
    interviewer_provider: InterviewerProvider | None = None,
    code_reviewer_provider: CodeReviewerProvider | None = None,
    review_input: CodeReviewInput | object | None = None,
    edge_case_generator_provider: EdgeCaseGeneratorProvider | None = None,
    edge_case_input: EdgeCaseGeneratorInput | object | None = None,
    feedback_aggregator_provider: FeedbackAggregatorProvider | None = None,
) -> AssessmentGraphResult:
    """Run the coordinated graph from a validated snapshot without side effects."""
    try:
        validated_state = validate_assessment_state(assessment_state)
        validated_review_input = validate_code_review_input(review_input)
        validated_edge_case_input = (
            EdgeCaseGeneratorInput.model_validate(edge_case_input)
            if edge_case_input is not None
            else None
        )
        result = build_assessment_graph(
            interviewer_provider,
            code_reviewer_provider,
            edge_case_generator_provider,
            feedback_aggregator_provider,
        ).invoke(
            {
                "assessment_state": validated_state,
                "context_initialized": False,
                "interviewer_decision": None,
                "review_input": validated_review_input,
                "prepared_review_input": None,
                "real_context_prepared": False,
                "code_review": None,
                "edge_case_input": validated_edge_case_input,
                "prepared_edge_case_input": None,
                "edge_case_generation": None,
                "orchestration_result": None,
                "feedback_result": None,
            }
        )
        if result.get("context_initialized") is not True:
            raise AssessmentGraphValidationError(
                "assessment graph did not initialize assessment context"
            )
        orchestration = MultiAgentOrchestrationResult.model_validate(
            result.get("orchestration_result")
        )
        feedback_result = None
        if result.get("feedback_result") is not None:
            feedback_result = FeedbackAggregationResult.model_validate(result.get("feedback_result"))
        logger.info(
            "Assessment graph completed",
            extra={
                "event": "assessment_graph_completed",
                "status": orchestration.status,
                "question_id": str(orchestration.interviewer_decision.question_id)
                if orchestration.interviewer_decision and orchestration.interviewer_decision.question_id
                else None,
            },
        )
        return AssessmentGraphResult(
            assessment_state=validate_assessment_state(result.get("assessment_state")),
            interviewer_decision=InterviewerDecision.model_validate(
                result.get("interviewer_decision")
            ),
            code_review=validate_code_review_result(result.get("code_review")),
            edge_case_generation=EdgeCaseGenerationResult.model_validate(
                result.get("edge_case_generation")
            ),
            execution=orchestration.execution,
            status=orchestration.status,
            reason=orchestration.reason,
            context_initialized=True,
            feedback_result=feedback_result,
        )
    except Exception as exc:
        logger.exception(
            "Assessment graph failed",
            extra={
                "event": "assessment_graph_failed",
                "error": sanitize_exception_message(exc),
            },
        )
        raise
