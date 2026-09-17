"""Side-effect-free LangGraph entry point for an AssessmentState snapshot."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict

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
from app.orchestration.state_adapter import (
    AssessmentGraphValidationError,
    validate_assessment_state,
)


class AssessmentGraphState(TypedDict):
    """Internal LangGraph state; AssessmentState remains the domain contract."""

    assessment_state: AssessmentState
    context_initialized: bool
    interviewer_decision: InterviewerDecision | None
    review_input: CodeReviewInput | None
    code_review: CodeReviewResult | None


class AssessmentGraphResult(BaseModel):
    """Typed result of the deterministic graph foundation."""

    model_config = ConfigDict(frozen=True)

    assessment_state: AssessmentState
    context_initialized: bool
    interviewer_decision: InterviewerDecision
    code_review: CodeReviewResult


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
                state["assessment_state"], state.get("review_input")
            )
        }

    return run


def build_assessment_graph(
    interviewer_provider: InterviewerProvider | None = None,
    code_reviewer_provider: CodeReviewerProvider | None = None,
) -> Any:
    """Compile START -> assessment_context -> interviewer -> code_reviewer -> END."""
    builder = StateGraph(AssessmentGraphState)
    builder.add_node("assessment_context", assessment_context)
    builder.add_node(
        "interviewer",
        interviewer_node(interviewer_provider or DeterministicInterviewerProvider()),
    )
    builder.add_node(
        "code_reviewer",
        code_reviewer_node(
            code_reviewer_provider or DeterministicCodeReviewerProvider()
        ),
    )
    builder.add_edge(START, "assessment_context")
    builder.add_edge("assessment_context", "interviewer")
    builder.add_edge("interviewer", "code_reviewer")
    builder.add_edge("code_reviewer", END)
    return builder.compile()


def invoke_assessment_graph(
    assessment_state: AssessmentState | object,
    interviewer_provider: InterviewerProvider | None = None,
    code_reviewer_provider: CodeReviewerProvider | None = None,
    review_input: CodeReviewInput | object | None = None,
) -> AssessmentGraphResult:
    """Run the graph from a validated snapshot without side effects."""
    validated_state = validate_assessment_state(assessment_state)
    validated_review_input = validate_code_review_input(review_input)
    result = build_assessment_graph(
        interviewer_provider, code_reviewer_provider
    ).invoke(
        {
            "assessment_state": validated_state,
            "context_initialized": False,
            "interviewer_decision": None,
            "review_input": validated_review_input,
            "code_review": None,
        }
    )
    if result.get("context_initialized") is not True:
        raise AssessmentGraphValidationError(
            "assessment graph did not initialize assessment context"
        )
    return AssessmentGraphResult(
        assessment_state=validate_assessment_state(result.get("assessment_state")),
        context_initialized=True,
        interviewer_decision=InterviewerDecision.model_validate(
            result.get("interviewer_decision")
        ),
        code_review=validate_code_review_result(result.get("code_review")),
    )
