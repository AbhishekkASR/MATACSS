"""Boundary tests for structured LLM-backed assessment-agent providers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.llm_provider import (
    LLMFailureKind,
    LLMMessage,
    LLMProviderError,
    LLMResponse,
)
from app.models.interview import InterviewStatus
from app.orchestration.assessment_graph import invoke_assessment_graph
from app.orchestration.code_reviewer import CodeReviewInput, ReviewStatus
from app.orchestration.edge_case_generator import (
    EdgeCaseCategory,
    EdgeCaseGeneratorInput,
    VerificationStatus,
)
from app.orchestration.interviewer import InterviewerAgent
from app.orchestration.llm_agent_providers import (
    LLMCodeReviewerProvider,
    LLMEdgeCaseGeneratorProvider,
    LLMInterviewerProvider,
    MAX_AGENT_PAYLOAD_CHARS,
)
from app.schemas.assessment_state import (
    AssessmentProgressState,
    AssessmentQuestionState,
    AssessmentState,
)


class MockLLMProvider:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.requests: list[tuple[LLMMessage, ...]] = []

    def complete(self, messages: tuple[LLMMessage, ...]) -> LLMResponse:
        self.requests.append(messages)
        if self.error is not None:
            raise self.error
        assert self.content is not None
        return LLMResponse(content=self.content, model="mock-model")


def make_state() -> AssessmentState:
    now = datetime.now(timezone.utc)
    question = AssessmentQuestionState(
        question_id=uuid4(),
        sequence_number=1,
        title="Public array question",
        description="Given an array of integers, find the largest value.",
        difficulty="easy",
        expected_language="python",
        evaluation_status="not_attempted",
    )
    return AssessmentState(
        interview_session_id=uuid4(),
        candidate_id=uuid4(),
        assessment_status=InterviewStatus.ACTIVE,
        started_at=now,
        completed_at=None,
        created_at=now,
        generated_at=now,
        assigned_questions=(question,),
        current_question_id=question.question_id,
        progress=AssessmentProgressState(
            total_questions=1,
            attempted_questions=0,
            evaluated_questions=0,
            current_question_index=0,
        ),
    )


def make_state_with_evaluation_history() -> AssessmentState:
    now = datetime.now(timezone.utc)
    evaluated = AssessmentQuestionState(
        question_id=uuid4(),
        sequence_number=1,
        title="Completed array question",
        description="Process an array.",
        difficulty="easy",
        expected_language="python",
        latest_submission_id=uuid4(),
        latest_submission_status="success",
        latest_submission_created_at=now,
        evaluation_result_id=uuid4(),
        evaluation_status="evaluated",
        score=83,
        passed_test_cases=4,
        total_test_cases=5,
    )
    current = AssessmentQuestionState(
        question_id=uuid4(),
        sequence_number=2,
        title="Current string question",
        description="Process a string.",
        difficulty="medium",
        expected_language="java",
        evaluation_status="not_attempted",
    )
    return AssessmentState(
        interview_session_id=uuid4(),
        candidate_id=uuid4(),
        assessment_status=InterviewStatus.ACTIVE,
        started_at=now,
        completed_at=None,
        created_at=now,
        generated_at=now,
        assigned_questions=(evaluated, current),
        current_question_id=current.question_id,
        progress=AssessmentProgressState(
            total_questions=2,
            attempted_questions=1,
            evaluated_questions=1,
            current_question_index=1,
        ),
    )


def test_interviewer_uses_structured_prompt_and_current_question_guard() -> None:
    state = make_state_with_evaluation_history()
    provider = MockLLMProvider(
        json.dumps(
            {
                "selected_question_id": str(state.current_question_id),
                "reason": "This is the current assigned question.",
                "interviewer_message": "Please begin with the input constraints.",
                "next_step": {
                    "action": "continue",
                    "topic": "array boundaries",
                    "difficulty": "medium",
                    "language": "python",
                },
            }
        )
    )
    result = InterviewerAgent(LLMInterviewerProvider(provider)).decide(state)
    assert result.question_id == state.current_question_id
    assert result.next_step.action == "continue"
    assert result.next_step.topic == "array boundaries"
    assert result.next_step.difficulty == "medium"
    assert result.next_step.language == "python"
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert [message.role for message in request] == ["system", "user"]
    payload = json.loads(request[1].content)
    assert payload["allowed_question_id"] == str(state.current_question_id)
    summary = payload["assessment_summary"]
    assert summary["assessment_status"] == "active"
    assert summary["progress"]["total_questions"] == 2
    assert summary["progress"]["evaluated_questions"] == 1
    assert summary["question_outcomes"][0]["evaluation_status"] == "evaluated"
    assert summary["question_outcomes"][0]["submission_status"] == "success"
    assert summary["question_outcomes"][0]["passed_test_cases"] == 4
    assert summary["question_outcomes"][0]["total_test_cases"] == 5
    assert summary["question_outcomes"][1]["evaluation_status"] == "not_attempted"
    assert "question_id" not in summary["question_outcomes"][0]
    assert "score" not in request[1].content
    assert "hidden_test_cases" not in payload


def test_interviewer_recommends_continuation_without_selecting_a_question() -> None:
    state = make_state_with_evaluation_history()
    completed_question = state.assigned_questions[0]
    state = AssessmentState(
        interview_session_id=state.interview_session_id,
        candidate_id=state.candidate_id,
        assessment_status=state.assessment_status,
        started_at=state.started_at,
        completed_at=None,
        created_at=state.created_at,
        generated_at=state.generated_at,
        assigned_questions=(completed_question,),
        current_question_id=None,
        progress=AssessmentProgressState(
            total_questions=1,
            attempted_questions=1,
            evaluated_questions=1,
            current_question_index=None,
        ),
    )
    provider = MockLLMProvider(
        json.dumps(
            {
                "selected_question_id": None,
                "reason": "The completed question supports continuing.",
                "interviewer_message": "Continue with a related challenge.",
                "next_step": {
                    "action": "continue",
                    "topic": "graphs",
                    "difficulty": "medium",
                    "language": "python",
                },
            }
        )
    )

    result = InterviewerAgent(LLMInterviewerProvider(provider)).decide(state)
    assert result.decision_type.value == "all_questions_attempted"
    assert result.question_id is None
    assert result.next_step.topic == "graphs"
    payload = json.loads(provider.requests[0][1].content)
    assert payload["allowed_question_id"] is None


def test_graph_carries_interviewer_recommendation_without_changing_question_selection() -> None:
    state = make_state()
    provider = MockLLMProvider(
        json.dumps(
            {
                "selected_question_id": str(state.current_question_id),
                "reason": "Present the deterministic current question.",
                "interviewer_message": "Please begin.",
                "next_step": {
                    "action": "continue",
                    "topic": "array boundaries",
                    "difficulty": "medium",
                    "language": "python",
                },
            }
        )
    )
    before = state.model_dump()
    result = invoke_assessment_graph(
        state, interviewer_provider=LLMInterviewerProvider(provider)
    )

    assert result.interviewer_decision.question_id == state.current_question_id
    assert result.interviewer_decision.next_step.topic == "array boundaries"
    assert result.interviewer_decision.next_step.action == "continue"
    assert result.assessment_state.model_dump() == before


def test_reviewer_receives_bounded_public_code_without_score_and_returns_typed_advice() -> None:
    state = make_state()
    question = state.assigned_questions[0]
    provider = MockLLMProvider(
        json.dumps(
            {
                "review_status": "completed",
                "question_id": str(question.question_id),
                "correctness_summary": "Static review cannot establish runtime correctness.",
                "observations": [
                    {
                        "category": "code_quality",
                        "severity": "info",
                        "message": "Use a descriptive variable name.",
                    }
                ],
                "improvement_suggestions": ["Validate boundary cases with authorized tests."],
                "reason": "Reviewed the supplied code statically.",
            }
        )
    )
    review_input = CodeReviewInput(
        question_id=question.question_id,
        question_title=question.title,
        question_prompt=question.description,
        language="python",
        source_code="def solve(values): return max(values)",
        execution_summary={
            "submission_status": "success",
            "evaluation_status": "evaluated",
            "score": 97,
            "passed_test_cases": 9,
            "total_test_cases": 10,
        },
    )
    result = LLMCodeReviewerProvider(provider).review(review_input)
    assert result.review_status == ReviewStatus.COMPLETED
    payload = json.loads(provider.requests[0][1].content)
    assert payload["source_code"] == review_input.source_code
    assert payload["execution_summary"] == {
        "submission_status": "success",
        "evaluation_status": "evaluated",
        "passed_test_cases": 9,
        "total_test_cases": 10,
    }
    assert "score" not in provider.requests[0][1].content
    assert "hidden_test_cases" not in payload
    assert "expected_outputs" not in payload
    assert "score" not in result.model_dump()


def test_edge_cases_are_always_unverified_and_never_receive_official_score() -> None:
    state = make_state()
    question = state.assigned_questions[0]
    provider = MockLLMProvider(
        json.dumps(
            {
                "question_id": str(question.question_id),
                "cases": [
                    {
                        "case_id": "single-value",
                        "category": "single_element",
                        "input_data": "1 8",
                        "expected_output": "8",
                        "rationale": "Checks the smallest non-empty array.",
                        "confidence": 0.8,
                    }
                ],
                "reason": "Candidates are derived from the public prompt.",
            }
        )
    )
    generation_input = EdgeCaseGeneratorInput(
        question_id=question.question_id,
        question_title=question.title,
        question_prompt=question.description,
        language="python",
        execution_summary={
            "evaluation_status": "evaluated",
            "score": 100,
            "passed_test_cases": 10,
            "total_test_cases": 10,
        },
    )
    result = LLMEdgeCaseGeneratorProvider(provider).generate(generation_input)
    assert result.cases[0].category == EdgeCaseCategory.SINGLE_ELEMENT
    assert result.cases[0].verification_status == VerificationStatus.UNVERIFIED
    assert "confidence to a JSON number from 0 to 1 inclusive" in (
        provider.requests[0][0].content
    )
    payload = json.loads(provider.requests[0][1].content)
    assert payload["execution_summary"] == {
        "evaluation_status": "evaluated",
        "passed_test_cases": 10,
        "total_test_cases": 10,
    }
    assert "score" not in provider.requests[0][1].content
    assert "hidden_test_cases" not in payload
    assert "expected_outputs" not in payload


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        '{"selected_question_id":"id","reason":"first","reason":"second","interviewer_message":null}',
        '{"selected_question_id":"id","reason":"ok","interviewer_message":null,"next_step":{"action":"continue","topic":null,"difficulty":null,"language":null},"score":100}',
    ],
)
def test_malformed_or_unexpected_model_output_is_rejected(content: str) -> None:
    provider = MockLLMProvider(content)
    with pytest.raises(LLMProviderError) as error:
        LLMInterviewerProvider(provider).select_question(make_state())
    assert error.value.kind == LLMFailureKind.INVALID_RESPONSE
    assert "not json" not in str(error.value)


@pytest.mark.parametrize(
    "next_step",
    [
        {"action": "skip", "topic": None, "difficulty": None, "language": None},
        {
            "action": "continue",
            "topic": "x" * 101,
            "difficulty": "easy",
            "language": "python",
        },
        {
            "action": "continue",
            "topic": None,
            "difficulty": "expert",
            "language": "python",
        },
        {
            "action": "finish",
            "topic": None,
            "difficulty": None,
            "language": "rust",
        },
        {
            "action": "continue",
            "topic": None,
            "difficulty": None,
            "language": None,
            "question_id": str(uuid4()),
        },
    ],
)
def test_invalid_or_question_selecting_recommendations_are_rejected(next_step: dict) -> None:
    state = make_state()
    provider = MockLLMProvider(
        json.dumps(
            {
                "selected_question_id": str(state.current_question_id),
                "reason": "Bounded recommendation test.",
                "interviewer_message": None,
                "next_step": next_step,
            }
        )
    )
    with pytest.raises(LLMProviderError) as error:
        LLMInterviewerProvider(provider).select_question(state)
    assert error.value.kind == LLMFailureKind.INVALID_RESPONSE


def test_model_cannot_select_another_question_or_mark_candidates_verified() -> None:
    state = make_state()
    interviewer = MockLLMProvider(
        json.dumps(
            {
                "selected_question_id": str(uuid4()),
                "reason": "Select another question.",
                "interviewer_message": None,
                "next_step": {
                    "action": "continue",
                    "topic": None,
                    "difficulty": None,
                    "language": None,
                },
            }
        )
    )
    with pytest.raises(ValueError, match="outside this assessment"):
        InterviewerAgent(LLMInterviewerProvider(interviewer)).decide(state)

    question = state.assigned_questions[0]
    edge_output = {
        "question_id": str(question.question_id),
        "cases": [
            {
                "case_id": "bad",
                "category": "single_element",
                "input_data": "1",
                "expected_output": "1",
                "rationale": "Candidate.",
                "confidence": 1.0,
                "verification_status": "verified",
            }
        ],
        "reason": "Candidate.",
    }
    with pytest.raises(LLMProviderError) as error:
        LLMEdgeCaseGeneratorProvider(MockLLMProvider(json.dumps(edge_output))).generate(
            EdgeCaseGeneratorInput(
                question_id=question.question_id,
                question_title=question.title,
                question_prompt=question.description,
                language="python",
            )
        )
    assert error.value.kind == LLMFailureKind.INVALID_RESPONSE


def test_payload_limit_and_provider_failures_remain_explicit() -> None:
    state = make_state()
    question = state.assigned_questions[0]
    too_large = CodeReviewInput(
        question_id=question.question_id,
        question_title=question.title,
        question_prompt=question.description,
        language="python",
        source_code="x" * MAX_AGENT_PAYLOAD_CHARS,
    )
    provider = MockLLMProvider("{}")
    with pytest.raises(LLMProviderError) as error:
        LLMCodeReviewerProvider(provider).review(too_large)
    assert error.value.kind == LLMFailureKind.INVALID_REQUEST
    assert provider.requests == []

    failure = LLMProviderError(LLMFailureKind.TIMEOUT, "The LLM request timed out.")
    failing_provider = MockLLMProvider(error=failure)
    before = state.model_dump()
    with pytest.raises(LLMProviderError) as error:
        invoke_assessment_graph(
            state,
            interviewer_provider=LLMInterviewerProvider(failing_provider),
        )
    assert error.value is failure
    assert state.model_dump() == before
