"""Bounded, non-executing edge-case generation contract and provider."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.models.interview import InterviewStatus
from app.orchestration.state_adapter import validate_assessment_state
from app.schemas.assessment_state import AssessmentState

EdgeCaseLanguage = Literal["python", "cpp", "java"]
MAX_GENERATED_CASES = 12
MAX_INPUT_SIZE = 4_000
MAX_EXPECTED_OUTPUT_SIZE = 2_000
MAX_RATIONALE_SIZE = 500
MAX_TOTAL_PAYLOAD_SIZE = 30_000


class EdgeCaseGeneratorAgentError(ValueError):
    """Raised when edge-case generation cannot be safely completed."""


class EdgeCaseCategory(StrEnum):
    EMPTY_INPUT = "empty_input"
    SINGLE_ELEMENT = "single_element"
    MINIMUM_SIZE = "minimum_size"
    MAXIMUM_BOUNDARY = "maximum_boundary"
    DUPLICATE_VALUES = "duplicate_values"
    SORTED_INPUT = "sorted_input"
    REVERSE_SORTED_INPUT = "reverse_sorted_input"
    NEGATIVE_VALUES = "negative_values"
    ZERO_VALUES = "zero_values"
    REPEATED_TEXT = "repeated_text"
    WHITESPACE_SENSITIVE = "whitespace_sensitive"
    LARGE_BOUNDED_INPUT = "large_bounded_input"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class EdgeCaseExecutionSummary(BaseModel):
    """Optional aggregate supplied by the caller; no test-case data is accepted."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluation_status: Literal["not_attempted", "attempted_not_evaluated", "evaluated"] | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    passed_test_cases: int | None = Field(default=None, ge=0)
    total_test_cases: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "EdgeCaseExecutionSummary":
        if (
            self.passed_test_cases is not None
            and self.total_test_cases is not None
            and self.passed_test_cases > self.total_test_cases
        ):
            raise ValueError("passed test cases cannot exceed total test cases")
        return self


class EdgeCaseGeneratorInput(BaseModel):
    """Explicit public context prepared for generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: UUID
    question_title: str = Field(min_length=1, max_length=500)
    question_prompt: str = Field(min_length=1, max_length=20_000)
    language: EdgeCaseLanguage
    code_review_summary: str | None = Field(default=None, max_length=500)
    execution_summary: EdgeCaseExecutionSummary | None = None


class GeneratedEdgeCase(BaseModel):
    """One candidate case; generated expected output is never authoritative."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(min_length=1, max_length=100)
    category: EdgeCaseCategory
    input_data: str = Field(max_length=MAX_INPUT_SIZE)
    expected_output: str | None = Field(default=None, max_length=MAX_EXPECTED_OUTPUT_SIZE)
    rationale: str = Field(min_length=1, max_length=MAX_RATIONALE_SIZE)
    confidence: float = Field(ge=0, le=1)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED


class EdgeCaseGenerationResult(BaseModel):
    """Bounded runtime output from an edge-case provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: UUID | None = None
    cases: tuple[GeneratedEdgeCase, ...] = Field(default=(), max_length=MAX_GENERATED_CASES)
    reason: str = Field(min_length=1, max_length=MAX_RATIONALE_SIZE)

    @model_validator(mode="after")
    def validate_payload(self) -> "EdgeCaseGenerationResult":
        if self.cases and self.question_id is None:
            raise ValueError("generated cases require a question id")
        identities = {(case.category, case.input_data, case.expected_output) for case in self.cases}
        if len(identities) != len(self.cases):
            raise ValueError("generated cases must be unique")
        payload_size = sum(
            len(case.case_id)
            + len(case.input_data)
            + len(case.expected_output or "")
            + len(case.rationale)
            for case in self.cases
        )
        if payload_size > MAX_TOTAL_PAYLOAD_SIZE:
            raise ValueError("generated edge-case payload exceeds the maximum size")
        return self


@runtime_checkable
class EdgeCaseGeneratorProvider(Protocol):
    """Provider boundary for a future real LLM integration."""

    def generate(self, generation_input: EdgeCaseGeneratorInput) -> EdgeCaseGenerationResult:
        """Generate only bounded candidates from explicitly supplied public context."""


class DeterministicEdgeCaseGeneratorProvider:
    """Conservative provider using prompt wording only; it never executes anything."""

    def generate(self, generation_input: EdgeCaseGeneratorInput) -> EdgeCaseGenerationResult:
        generation_input = EdgeCaseGeneratorInput.model_validate(generation_input)
        prompt = generation_input.question_prompt.lower()
        collection = any(
            word in prompt
            for word in ("array", "list", "sequence", "vector", "elements", "numbers", "integers")
        )
        text = any(word in prompt for word in ("string", "text", "characters", "substring"))
        if not collection and not text:
            return EdgeCaseGenerationResult(
                question_id=generation_input.question_id,
                reason="The public prompt does not provide enough input-shape evidence for safe edge cases.",
            )

        cases: list[GeneratedEdgeCase] = []

        def add(category: EdgeCaseCategory, input_data: str, rationale: str) -> None:
            cases.append(
                GeneratedEdgeCase(
                    case_id=f"edge-{len(cases) + 1:02d}-{category.value}",
                    category=category,
                    input_data=input_data,
                    rationale=rationale,
                    confidence=0.75,
                )
            )

        add(EdgeCaseCategory.EMPTY_INPUT, "", "Checks behavior when no input values are supplied.")
        if collection:
            add(EdgeCaseCategory.MINIMUM_SIZE, "0", "Checks the smallest bounded numeric input representation.")
            add(EdgeCaseCategory.SINGLE_ELEMENT, "1", "Checks the smallest non-empty collection shape.")
            add(EdgeCaseCategory.DUPLICATE_VALUES, "2 2", "Checks repeated values and duplicate handling.")
            add(EdgeCaseCategory.SORTED_INPUT, "1 2 3", "Checks an already ordered input.")
            add(EdgeCaseCategory.REVERSE_SORTED_INPUT, "3 2 1", "Checks the opposite ordering.")
            if any(word in prompt for word in ("negative", "integer", "number", "sum", "difference")):
                add(EdgeCaseCategory.NEGATIVE_VALUES, "-2 -1", "Checks signed values when numeric input is described.")
                add(EdgeCaseCategory.ZERO_VALUES, "0 0", "Checks zero values when numeric input is described.")
            if any(word in prompt for word in ("limit", "maximum", "at most", "up to", "n <=")):
                add(EdgeCaseCategory.MAXIMUM_BOUNDARY, "1 1 1", "Targets the stated public size boundary conservatively.")
            add(EdgeCaseCategory.LARGE_BOUNDED_INPUT, " ".join(["1"] * 100), "Checks a larger input without exceeding the generation bound.")
        if text:
            add(EdgeCaseCategory.SINGLE_ELEMENT, "a", "Checks the smallest non-empty text shape.")
            add(EdgeCaseCategory.REPEATED_TEXT, "aaaa", "Checks repeated characters and text.")
            add(EdgeCaseCategory.WHITESPACE_SENSITIVE, " a ", "Checks whether surrounding whitespace matters.")
        return EdgeCaseGenerationResult(
            question_id=generation_input.question_id,
            cases=tuple(cases),
            reason="Deterministic candidates were derived from public question wording only.",
        )


def validate_edge_case_generation_result(value: object) -> EdgeCaseGenerationResult:
    raw_value = value.model_dump(mode="python") if isinstance(value, EdgeCaseGenerationResult) else value
    try:
        return EdgeCaseGenerationResult.model_validate(raw_value)
    except ValidationError as exc:
        raise EdgeCaseGeneratorAgentError("provider returned invalid edge-case output") from exc


def validate_edge_case_generator_input(value: object) -> EdgeCaseGeneratorInput:
    """Validate explicitly prepared generation context without fetching data."""
    raw_value = value.model_dump(mode="python") if isinstance(value, EdgeCaseGeneratorInput) else value
    try:
        return EdgeCaseGeneratorInput.model_validate(raw_value)
    except ValidationError as exc:
        raise EdgeCaseGeneratorAgentError("edge-case generator requires valid prepared input") from exc


class EdgeCaseGeneratorAgent:
    """Candidate-generation agent with no persistence, execution, or Docker authority."""

    def __init__(self, provider: EdgeCaseGeneratorProvider) -> None:
        self._provider = provider

    def generate(
        self,
        assessment_state: AssessmentState | object,
        generation_input: EdgeCaseGeneratorInput | object | None,
    ) -> EdgeCaseGenerationResult:
        try:
            assessment = validate_assessment_state(assessment_state)
        except ValueError as exc:
            raise EdgeCaseGeneratorAgentError("edge-case generator requires a valid AssessmentState") from exc
        if generation_input is None:
            return EdgeCaseGenerationResult(reason="No prepared public question context was supplied.")
        prepared = validate_edge_case_generator_input(generation_input)
        if assessment.assessment_status != InterviewStatus.ACTIVE:
            return EdgeCaseGenerationResult(reason=f"Assessment is {assessment.assessment_status}.")
        question = next(
            (item for item in assessment.assigned_questions if item.question_id == prepared.question_id),
            None,
        )
        if question is None:
            raise EdgeCaseGeneratorAgentError("generation input question is not assigned to this assessment")
        if question.title != prepared.question_title or question.description != prepared.question_prompt:
            raise EdgeCaseGeneratorAgentError("generation input question context does not match AssessmentState")
        try:
            result = validate_edge_case_generation_result(self._provider.generate(prepared))
        except (TypeError, ValidationError, ValueError) as exc:
            raise EdgeCaseGeneratorAgentError("provider returned invalid edge-case output") from exc
        if result.question_id != prepared.question_id:
            raise EdgeCaseGeneratorAgentError("provider returned cases for a different question")
        if any(case.verification_status != VerificationStatus.UNVERIFIED for case in result.cases):
            raise EdgeCaseGeneratorAgentError("provider returned a case that is not unverified")
        return result
