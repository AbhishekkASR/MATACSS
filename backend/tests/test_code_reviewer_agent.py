"""Focused coverage for the bounded deterministic Code Reviewer Agent."""

from datetime import datetime, timezone
import socket
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.interview import InterviewStatus
from app.orchestration.assessment_graph import build_assessment_graph, invoke_assessment_graph
from app.orchestration.code_reviewer import (
    CodeReviewInput,
    CodeReviewResult,
    CodeReviewerAgent,
    CodeReviewerAgentError,
    CodeReviewerProvider,
    DeterministicCodeReviewerProvider,
    ReviewStatus,
)
from app.schemas.assessment_state import (
    AssessmentProgressState,
    AssessmentQuestionState,
    AssessmentState,
)
from app.services import database_service
from app.services.sandbox_service import DockerSandboxService


def make_state(status: InterviewStatus = InterviewStatus.ACTIVE) -> AssessmentState:
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


def make_review_input(
    state: AssessmentState,
    source_code: str,
    language: str = "python",
) -> CodeReviewInput:
    question = state.assigned_questions[0]
    return CodeReviewInput(
        question_id=question.question_id,
        question_title=question.title,
        question_prompt=question.description,
        language=language,
        source_code=source_code,
    )


class RecordingProvider:
    def __init__(self) -> None:
        self.inputs: list[CodeReviewInput] = []
        self._provider = DeterministicCodeReviewerProvider()

    def review(self, review_input: CodeReviewInput) -> CodeReviewResult:
        self.inputs.append(review_input)
        return self._provider.review(review_input)


class MalformedProvider:
    def review(self, review_input: CodeReviewInput) -> CodeReviewResult:
        return CodeReviewResult.model_construct(
            review_status=ReviewStatus.COMPLETED,
            question_id=None,
            correctness_summary="Malformed result.",
            observations=(),
            improvement_suggestions=(),
            reason="Malformed provider output.",
        )


def test_static_reviewer_handles_valid_python_without_claiming_correctness() -> None:
    state = make_state()
    result = CodeReviewerAgent(DeterministicCodeReviewerProvider()).review(
        state, make_review_input(state, "def solve():\n    return 1\n")
    )
    assert result.review_status == ReviewStatus.COMPLETED
    assert result.question_id == state.current_question_id
    assert "cannot establish runtime correctness" in result.correctness_summary.lower()


@pytest.mark.parametrize(
    ("language", "source_code"),
    [
        ("cpp", "#include <iostream>\nint main() { return 0; }\n"),
        ("java", "public class Main { public static void main(String[] args) {} }\n"),
    ],
)
def test_static_reviewer_handles_supported_nonpython_sources(
    language: str, source_code: str
) -> None:
    state = make_state()
    result = CodeReviewerAgent(DeterministicCodeReviewerProvider()).review(
        state, make_review_input(state, source_code, language)
    )
    assert result.review_status == ReviewStatus.COMPLETED
    assert result.question_id == state.current_question_id


def test_empty_and_python_parse_error_sources_are_reported_safely() -> None:
    state = make_state()
    agent = CodeReviewerAgent(DeterministicCodeReviewerProvider())
    empty = agent.review(state, make_review_input(state, ""))
    invalid_python = agent.review(state, make_review_input(state, "def broken(:\n"))
    assert empty.review_status == ReviewStatus.PARSE_ERROR
    assert invalid_python.review_status == ReviewStatus.PARSE_ERROR
    assert any(item.severity == "error" for item in invalid_python.observations)


def test_review_is_deterministic_and_needs_no_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    connect = Mock(side_effect=AssertionError("network must not be called"))
    monkeypatch.setattr(socket, "create_connection", connect)
    state = make_state()
    review_input = make_review_input(state, "print('safe static review')\n")
    provider = DeterministicCodeReviewerProvider()
    assert isinstance(provider, CodeReviewerProvider)
    first = CodeReviewerAgent(provider).review(state, review_input)
    second = CodeReviewerAgent(provider).review(state, review_input)
    assert first == second
    connect.assert_not_called()


def test_provider_output_and_review_input_are_strictly_validated() -> None:
    state = make_state()
    review_input = make_review_input(state, "print(1)\n")
    with pytest.raises(CodeReviewerAgentError, match="invalid code review result"):
        CodeReviewerAgent(MalformedProvider()).review(state, review_input)
    payload = review_input.model_dump()
    for unsafe_field in (
        "hidden_test_cases",
        "expected_outputs",
        "credentials",
        "docker_internals",
        "candidate_email",
    ):
        with pytest.raises(ValidationError):
            CodeReviewInput.model_validate({**payload, unsafe_field: "not allowed"})
    result_json = CodeReviewerAgent(DeterministicCodeReviewerProvider()).review(
        state, review_input
    ).model_dump_json()
    assert "print(1)" not in result_json
    assert "hidden_test_cases" not in result_json


def test_reviewer_does_not_execute_docker_or_write_persistence(monkeypatch) -> None:
    docker_execute = Mock(side_effect=AssertionError("Docker must not be called"))
    persist_submission = Mock(side_effect=AssertionError("Persistence must not be called"))
    monkeypatch.setattr(DockerSandboxService, "execute", docker_execute)
    monkeypatch.setattr(database_service, "create_submission", persist_submission)
    state = make_state()
    CodeReviewerAgent(DeterministicCodeReviewerProvider()).review(
        state, make_review_input(state, "print('do not execute')\n")
    )
    docker_execute.assert_not_called()
    persist_submission.assert_not_called()


@pytest.mark.parametrize("status", [InterviewStatus.COMPLETED, InterviewStatus.CANCELLED])
def test_closed_assessment_does_not_run_provider(status: InterviewStatus) -> None:
    provider = Mock(side_effect=AssertionError("provider must not run"))
    state = make_state(status)
    result = CodeReviewerAgent(provider).review(
        state, make_review_input(state, "print(1)\n")
    )
    assert result.review_status == ReviewStatus.NOT_RUN
    provider.assert_not_called()


def test_no_review_input_returns_explicit_not_run_result() -> None:
    result = CodeReviewerAgent(DeterministicCodeReviewerProvider()).review(make_state(), None)
    assert result.review_status == ReviewStatus.NOT_RUN
    assert result.question_id is None


def test_graph_preserves_interviewer_and_runs_explicit_review_input() -> None:
    state = make_state()
    provider = RecordingProvider()
    graph = build_assessment_graph(code_reviewer_provider=provider)
    graph_definition = graph.get_graph()
    assert {"__start__", "assessment_context", "interviewer", "code_reviewer", "__end__"} <= set(
        graph_definition.nodes
    )
    assert len(graph_definition.edges) == 4
    result = invoke_assessment_graph(
        state,
        code_reviewer_provider=provider,
        review_input=make_review_input(state, "print('review')\n"),
    )
    assert result.interviewer_decision.question_id == state.current_question_id
    assert result.code_review.review_status == ReviewStatus.COMPLETED
    assert provider.inputs[0].question_id == state.current_question_id
