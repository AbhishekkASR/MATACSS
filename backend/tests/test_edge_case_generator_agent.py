"""Focused coverage for the bounded Edge-Case Generator foundation."""

from datetime import datetime, timezone
import socket
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.interview import InterviewStatus
from app.orchestration.edge_case_generator import (
    MAX_GENERATED_CASES,
    MAX_INPUT_SIZE,
    EdgeCaseCategory,
    EdgeCaseGenerationResult,
    EdgeCaseGeneratorAgent,
    EdgeCaseGeneratorAgentError,
    EdgeCaseGeneratorInput,
    EdgeCaseGeneratorProvider,
    DeterministicEdgeCaseGeneratorProvider,
    GeneratedEdgeCase,
    VerificationStatus,
)
from app.orchestration.assessment_graph import invoke_assessment_graph
from app.schemas.assessment_state import (
    AssessmentProgressState,
    AssessmentQuestionState,
    AssessmentState,
)
from app.services import database_service
from app.services.sandbox_service import DockerSandboxService


def make_state(
    status: InterviewStatus = InterviewStatus.ACTIVE,
    prompt: str = "Given an array of integers, process the elements.",
    language: str | None = "python",
) -> AssessmentState:
    now = datetime.now(timezone.utc)
    question = AssessmentQuestionState(
        question_id=uuid4(),
        sequence_number=1,
        title="Public array question",
        description=prompt,
        difficulty="easy",
        expected_language=language,
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


def make_input(state: AssessmentState, language: str = "python") -> EdgeCaseGeneratorInput:
    question = state.assigned_questions[0]
    return EdgeCaseGeneratorInput(
        question_id=question.question_id,
        question_title=question.title,
        question_prompt=question.description,
        language=language,
    )


def test_deterministic_generation_is_bounded_and_unverified() -> None:
    state = make_state()
    agent = EdgeCaseGeneratorAgent(DeterministicEdgeCaseGeneratorProvider())
    first = agent.generate(state, make_input(state))
    second = agent.generate(state, make_input(state))
    assert first == second
    assert 0 < len(first.cases) <= MAX_GENERATED_CASES
    assert all(case.verification_status == VerificationStatus.UNVERIFIED for case in first.cases)
    assert {case.category for case in first.cases} >= {
        EdgeCaseCategory.EMPTY_INPUT,
        EdgeCaseCategory.MINIMUM_SIZE,
        EdgeCaseCategory.DUPLICATE_VALUES,
        EdgeCaseCategory.LARGE_BOUNDED_INPUT,
    }


def test_text_and_language_context_is_supported_without_language_specific_execution() -> None:
    state = make_state(prompt="Given a string, normalize its characters.", language="java")
    result = EdgeCaseGeneratorAgent(DeterministicEdgeCaseGeneratorProvider()).generate(
        state, make_input(state, "java")
    )
    assert {EdgeCaseCategory.REPEATED_TEXT, EdgeCaseCategory.WHITESPACE_SENSITIVE} <= {
        case.category for case in result.cases
    }


def test_insufficient_context_returns_no_cases_conservatively() -> None:
    state = make_state(prompt="Return the requested result.", language="python")
    result = EdgeCaseGeneratorAgent(DeterministicEdgeCaseGeneratorProvider()).generate(
        state, make_input(state)
    )
    assert result.cases == ()
    assert "not provide enough" in result.reason


def test_schema_rejects_oversized_input_duplicate_cases_and_verified_generation() -> None:
    state = make_state()
    with pytest.raises(ValidationError):
        GeneratedEdgeCase(
            case_id="too-large",
            category=EdgeCaseCategory.EMPTY_INPUT,
            input_data="x" * (MAX_INPUT_SIZE + 1),
            rationale="safe",
            confidence=0.5,
        )
    case = GeneratedEdgeCase(
        case_id="one",
        category=EdgeCaseCategory.EMPTY_INPUT,
        input_data="",
        rationale="safe",
        confidence=0.5,
    )
    with pytest.raises(ValidationError):
        EdgeCaseGenerationResult(
            question_id=state.current_question_id,
            cases=(case, case),
            reason="duplicate",
        )
    verified = case.model_copy(update={"verification_status": VerificationStatus.VERIFIED})
    provider = Mock()
    provider.generate.return_value = EdgeCaseGenerationResult(
        question_id=state.current_question_id, cases=(verified,), reason="bad"
    )
    with pytest.raises(EdgeCaseGeneratorAgentError, match="not unverified"):
        EdgeCaseGeneratorAgent(provider).generate(state, make_input(state))


def test_provider_protocol_and_dependency_injection() -> None:
    class Provider:
        def generate(self, generation_input: EdgeCaseGeneratorInput) -> EdgeCaseGenerationResult:
            return EdgeCaseGenerationResult(
                question_id=generation_input.question_id, reason="injected"
            )

    assert isinstance(Provider(), EdgeCaseGeneratorProvider)
    state = make_state()
    result = EdgeCaseGeneratorAgent(Provider()).generate(state, make_input(state))
    assert result.reason == "injected"


def test_no_api_key_network_docker_or_persistence_is_needed(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    network = Mock(side_effect=AssertionError("network must not be called"))
    docker = Mock(side_effect=AssertionError("Docker must not be called"))
    persistence = Mock(side_effect=AssertionError("Persistence must not be called"))
    monkeypatch.setattr(socket, "create_connection", network)
    monkeypatch.setattr(DockerSandboxService, "execute", docker)
    monkeypatch.setattr(database_service, "create_submission", persistence)
    state = make_state()
    EdgeCaseGeneratorAgent(DeterministicEdgeCaseGeneratorProvider()).generate(
        state, make_input(state)
    )
    network.assert_not_called()
    docker.assert_not_called()
    persistence.assert_not_called()


@pytest.mark.parametrize("status", [InterviewStatus.COMPLETED, InterviewStatus.CANCELLED])
def test_closed_assessment_does_not_invoke_provider(status: InterviewStatus) -> None:
    provider = Mock(side_effect=AssertionError("provider must not run"))
    state = make_state(status)
    result = EdgeCaseGeneratorAgent(provider).generate(state, make_input(state))
    assert result.cases == ()
    provider.assert_not_called()


def test_graph_returns_runtime_cases_without_changing_state_or_official_cases() -> None:
    state = make_state()
    before = state.model_dump()
    result = invoke_assessment_graph(state)
    assert result.assessment_state.model_dump() == before
    assert result.edge_case_generation.cases
    assert state.model_dump() == before
