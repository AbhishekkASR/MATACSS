"""Bounded generation, adaptation, validation, and retrieval for Question Bank."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_provider import (
    LLMFailureKind,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    OpenAILLMProvider,
)
from app.models.interview import InterviewSession
from app.models.interview_question import InterviewQuestion
from app.models.question import Question, QuestionStatus
from app.models.question_llm_lineage import QuestionLlmLineage
from app.models.question_provenance import QuestionProvenance
from app.models.question_test_case import QuestionTestCase

MAX_PROMPT_CHARS = 4_000
MAX_MODEL_OUTPUT_BYTES = 16_000
MAX_TITLE_CHARS = 200
MAX_DESCRIPTION_CHARS = 12_000
MAX_FIELD_CHARS = 8_000
MAX_SUPPORTED_LANGUAGES = 5
MAX_DRAFT_SKILLS = 20
MAX_DRAFT_CONCEPTS = 20
MAX_DRAFT_TEST_CASES = 10
MAX_DRAFT_ITEM_CHARS = 120
MAX_DRAFT_CASE_FIELD_CHARS = 4_000
MAX_DRAFT_REFERENCE_CHARS = 8_000
MAX_RETRIEVAL_LIMIT = 50
ALLOWED_LANGUAGES = frozenset({"python", "cpp", "java"})
ALLOWED_DIFFICULTIES = frozenset({"easy", "medium", "hard"})


class QuestionEngineError(ValueError):
    """Invalid provider content or unusable question-bank state."""


class DraftTestCaseCandidate(BaseModel):
    """Untrusted proposed example; never an official QuestionTestCase."""

    model_config = ConfigDict(extra="forbid", strict=True)

    input: str = Field(max_length=MAX_DRAFT_CASE_FIELD_CHARS)
    expected_output: str = Field(max_length=MAX_DRAFT_CASE_FIELD_CHARS)
    rationale: str | None = Field(default=None, max_length=500)


class QuestionEngineOutput(BaseModel):
    """Typed contract for question fields and explicitly unverified draft artifacts."""

    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    description: str = Field(min_length=1, max_length=MAX_DESCRIPTION_CHARS)
    difficulty: Literal["easy", "medium", "hard"]
    expected_language: Literal["python", "cpp", "java"] | None
    input_format: str | None = Field(default=None, max_length=MAX_FIELD_CHARS)
    output_format: str | None = Field(default=None, max_length=MAX_FIELD_CHARS)
    constraints_text: str | None = Field(default=None, max_length=MAX_FIELD_CHARS)
    supported_languages: list[Literal["python", "cpp", "java"]] = Field(
        default_factory=list, max_length=MAX_SUPPORTED_LANGUAGES
    )
    starter_code: str | None = Field(default=None, max_length=MAX_FIELD_CHARS)
    skills: list[str] = Field(min_length=1, max_length=MAX_DRAFT_SKILLS)
    concepts: list[str] = Field(min_length=1, max_length=MAX_DRAFT_CONCEPTS)
    complexity_expectations: dict[str, str] = Field(
        min_length=1, max_length=4
    )
    reference_solution: str = Field(
        min_length=1, max_length=MAX_DRAFT_REFERENCE_CHARS
    )
    test_case_candidates: list[DraftTestCaseCandidate] = Field(
        min_length=1, max_length=MAX_DRAFT_TEST_CASES
    )

    @field_validator("title", "description")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value.strip()

    @field_validator("input_format", "output_format", "constraints_text", "starter_code")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("supported_languages")
    @classmethod
    def languages_must_be_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("supported_languages must not contain duplicates")
        return value

    @field_validator("skills", "concepts")
    @classmethod
    def validate_artifact_terms(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item or len(item) > MAX_DRAFT_ITEM_CHARS for item in cleaned):
            raise ValueError("draft skill/concept entries must be non-empty and bounded")
        if len({item.casefold() for item in cleaned}) != len(cleaned):
            raise ValueError("draft skill/concept entries must be unique")
        return cleaned

    @field_validator("complexity_expectations")
    @classmethod
    def validate_complexity_expectations(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"time", "space", "notes", "expected"}
        if any(
            key not in allowed or not item.strip() or len(item) > 500
            for key, item in value.items()
        ):
            raise ValueError("complexity expectations contain invalid or oversized fields")
        return {key: item.strip() for key, item in value.items()}

    @field_validator("reference_solution")
    @classmethod
    def validate_reference_solution(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reference solution must not be empty")
        return value.strip()


class QuestionGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    topic: str | None = Field(default=None, max_length=100)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    expected_language: Literal["python", "cpp", "java"] | None = None

    @field_validator("prompt")
    @classmethod
    def prompt_must_not_be_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("prompt must not be empty")
        return value


class TrustedValidationRequest(BaseModel):
    """Admin attestation that expected outputs were checked outside the LLM."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    trusted_reference_verified: Literal[True]
    review_notes: str = Field(min_length=10, max_length=2_000)


def _messages(
    operation: str,
    prompt: str,
    parent: Question | None = None,
    *,
    topic: str | None = None,
    difficulty: str | None = None,
    expected_language: str | None = None,
) -> list[LLMMessage]:
    system = (
        "You create coding-question drafts for a question bank. Return exactly one JSON object "
        "matching the requested schema, without markdown or extra keys. Include draft skills, "
        "concepts, complexity expectations, a reference solution, and candidate test cases as "
        "unverified artifacts. These artifacts are not trusted: never claim they were verified, "
        "never treat their expected outputs as authoritative, never use them as official test "
        "cases, and never mark a question validated or active. "
        "All content requires independent review and execution against a trusted reference."
    )
    request: dict[str, object] = {
        "operation": operation,
        "request": prompt,
        "preferences": {
            "topic": topic,
            "difficulty": difficulty,
            "expected_language": expected_language,
        },
    }
    if parent is not None:
        request["parent_question"] = {
            "title": parent.title,
            "description": parent.description,
            "difficulty": parent.difficulty,
            "expected_language": parent.expected_language,
            "input_format": parent.input_format,
            "output_format": parent.output_format,
            "constraints_text": parent.constraints_text,
            "supported_languages": parent.supported_languages or [],
            "starter_code": parent.starter_code,
        }
    request["schema"] = {
        "title": "string",
        "description": "string",
        "difficulty": "easy|medium|hard",
        "expected_language": "python|cpp|java|null",
        "input_format": "string|null",
        "output_format": "string|null",
        "constraints_text": "string|null",
        "supported_languages": ["python|cpp|java"],
        "starter_code": "string|null",
        "skills": ["non-empty skill"],
        "concepts": ["non-empty concept"],
        "complexity_expectations": {
            "time": "string",
            "space": "string",
            "notes": "string",
            "expected": "string",
        },
        "reference_solution": "string (unverified draft only)",
        "test_case_candidates": [
            {
                "input": "string",
                "expected_output": "string (unverified draft only)",
                "rationale": "string|null",
            }
        ],
    }
    return [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=json.dumps(request, ensure_ascii=False)),
    ]


def _parse_output(content: str) -> QuestionEngineOutput:
    if not isinstance(content, str):
        raise QuestionEngineError("Provider output must be text.")
    if len(content.encode("utf-8")) > MAX_MODEL_OUTPUT_BYTES:
        raise QuestionEngineError("Provider output exceeds the permitted size.")
    try:
        payload = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        return QuestionEngineOutput.model_validate(payload)
    except (json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise QuestionEngineError("Provider output did not match the question schema.") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


async def _complete(provider: LLMProvider, messages: list[LLMMessage]) -> LLMResponse:
    try:
        response = await asyncio.to_thread(provider.complete, messages)
    except LLMProviderError:
        raise
    except Exception:
        raise LLMProviderError(
            LLMFailureKind.API, "The question generation provider failed."
        ) from None
    if (
        not isinstance(response, LLMResponse)
        or not isinstance(response.content, str)
        or not isinstance(response.model, str)
        or not response.model.strip()
        or len(response.model) > 100
        or (
            response.request_id is not None
            and not isinstance(response.request_id, str)
        )
    ):
        raise LLMProviderError(
            LLMFailureKind.INVALID_RESPONSE,
            "The question generation provider returned an invalid response.",
        )
    return response


async def generate_question(
    session: AsyncSession,
    request: QuestionGenerationRequest,
    provider: LLMProvider | None = None,
) -> tuple[Question, str | None]:
    """Call the configured LLM, validate its response, and atomically persist a draft."""
    provider = provider or OpenAILLMProvider()
    prompt = request.prompt
    messages = _messages(
        "generate",
        prompt,
        topic=request.topic,
        difficulty=request.difficulty,
        expected_language=request.expected_language,
    )
    try:
        response = await _complete(provider, messages)
        output = _parse_output(response.content)
        _validate_preferences(output, request)
    except Exception:
        await session.rollback()
        raise
    question = _question_from_output(output)
    await _persist_draft(
        session,
        question,
        origin="generated",
        model=response.model,
        parent=None,
        request_id=response.request_id,
        request_prompt=prompt,
        topic=request.topic,
        draft_artifacts=output,
    )
    return question, response.request_id


async def adapt_question(
    session: AsyncSession,
    parent_id: UUID,
    request: QuestionGenerationRequest,
    provider: LLMProvider | None = None,
) -> tuple[Question, str | None]:
    """Generate an adaptation from an existing question without copying its tests."""
    parent = await session.get(Question, parent_id)
    if parent is None:
        raise QuestionEngineError("Parent question was not found.")
    provider = provider or OpenAILLMProvider()
    messages = _messages(
        "adapt",
        request.prompt,
        parent,
        topic=request.topic,
        difficulty=request.difficulty,
        expected_language=request.expected_language,
    )
    try:
        response = await _complete(provider, messages)
        output = _parse_output(response.content)
        _validate_preferences(output, request)
    except Exception:
        await session.rollback()
        raise
    question = _question_from_output(output)
    await _persist_draft(
        session,
        question,
        origin="adapted",
        model=response.model,
        parent=parent,
        request_id=response.request_id,
        request_prompt=request.prompt,
        topic=request.topic,
        draft_artifacts=output,
    )
    return question, response.request_id


def _validate_preferences(
    output: QuestionEngineOutput, request: QuestionGenerationRequest
) -> None:
    if request.difficulty and output.difficulty != request.difficulty:
        raise QuestionEngineError("Provider output does not match requested difficulty.")
    if request.expected_language and output.expected_language != request.expected_language:
        raise QuestionEngineError("Provider output does not match requested language.")


def _question_from_output(output: QuestionEngineOutput) -> Question:
    return Question(
        title=output.title,
        description=output.description,
        difficulty=output.difficulty,
        expected_language=output.expected_language,
        input_format=output.input_format,
        output_format=output.output_format,
        constraints_text=output.constraints_text,
        supported_languages=output.supported_languages,
        starter_code=output.starter_code,
        status=QuestionStatus.DRAFT,
    )


async def _persist_draft(
    session: AsyncSession,
    question: Question,
    *,
    origin: str,
    model: str,
    parent: Question | None,
    request_id: str | None,
    request_prompt: str,
    topic: str | None,
    draft_artifacts: QuestionEngineOutput,
) -> None:
    lineage = QuestionLlmLineage(
        question=question,
        origin=origin,
        model=model,
        generation_timestamp=datetime.now(timezone.utc),
        parent_question_id=parent.id if parent else None,
        generation_metadata={
            "provider": "openai_compatible",
            "request_id": request_id,
            "prompt_sha256": hashlib.sha256(request_prompt.encode("utf-8")).hexdigest(),
            "topic": topic,
            "expected_outputs_authoritative": False,
            "draft_artifacts": {
                "verification_status": "unverified",
                "authoritative": False,
                "skills": draft_artifacts.skills,
                "concepts": draft_artifacts.concepts,
                "complexity_expectations": draft_artifacts.complexity_expectations,
                "reference_solution": draft_artifacts.reference_solution,
                "test_case_candidates": [
                    item.model_dump() for item in draft_artifacts.test_case_candidates
                ],
            },
        },
    )
    question.provenance = QuestionProvenance(
        source="question_engine",
        platform="llm",
        original_question_id=str(parent.id) if parent else None,
    )
    session.add_all([question, lineage])
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(
        question, attribute_names=["llm_lineage", "provenance", "test_cases"]
    )


async def validate_draft(
    session: AsyncSession,
    question: Question,
    request: TrustedValidationRequest,
    reviewer_id: UUID,
) -> None:
    if question.status != QuestionStatus.DRAFT:
        raise QuestionEngineError("Only draft questions can be validated.")
    if (
        not question.title.strip()
        or not question.description.strip()
        or question.difficulty not in ALLOWED_DIFFICULTIES
        or (
            question.expected_language is not None
            and question.expected_language not in ALLOWED_LANGUAGES
        )
    ):
        raise QuestionEngineError("Question failed structural validation.")
    cases = await session.scalars(
        select(QuestionTestCase).where(QuestionTestCase.question_id == question.id)
    )
    test_cases = list(cases.all())
    if not test_cases or any(
        not case.expected_stdout.strip() for case in test_cases
    ):
        raise QuestionEngineError(
            "At least one non-empty, human-entered expected-output test case is required."
        )
    lineage = await session.scalar(
        select(QuestionLlmLineage).where(
            QuestionLlmLineage.question_id == question.id
        )
    )
    if lineage is None:
        raise QuestionEngineError("Question lineage is missing.")
    metadata = dict(lineage.generation_metadata or {})
    metadata["validation"] = {
        "reviewer_id": str(reviewer_id),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "trusted_reference_verified": True,
        "review_notes": request.review_notes,
        "test_case_count": len(test_cases),
    }
    lineage.generation_metadata = metadata
    question.status = QuestionStatus.VALIDATED
    await session.commit()


async def retrieve_active_questions(
    session: AsyncSession,
    *,
    topic: str | None = None,
    difficulty: str | None = None,
    language: str | None = None,
    interview_session_id: UUID | None = None,
    candidate_id: UUID | None = None,
    limit: int = 20,
) -> list[Question]:
    if difficulty is not None and difficulty not in ALLOWED_DIFFICULTIES:
        raise QuestionEngineError("Unsupported difficulty filter.")
    if language is not None and language not in ALLOWED_LANGUAGES:
        raise QuestionEngineError("Unsupported language filter.")
    if topic is not None and len(topic) > 100:
        raise QuestionEngineError("Topic filter exceeds the permitted size.")
    limit = min(max(limit, 1), MAX_RETRIEVAL_LIMIT)
    excluded_ids: set[UUID] = set()
    if interview_session_id is not None:
        interview = await session.get(InterviewSession, interview_session_id)
        if interview is None:
            raise QuestionEngineError("Interview session was not found.")
        if candidate_id is not None and candidate_id != interview.candidate_id:
            raise QuestionEngineError(
                "Interview session does not belong to the requested candidate."
            )
        candidate_id = interview.candidate_id
    if candidate_id is not None:
        previously_assigned = await session.scalars(
            select(InterviewQuestion.question_id)
            .join(
                InterviewSession,
                InterviewSession.id == InterviewQuestion.interview_session_id,
            )
            .where(InterviewSession.candidate_id == candidate_id)
        )
        excluded_ids = set(previously_assigned.all())

    statement = select(Question).where(Question.status == QuestionStatus.ACTIVE)
    if difficulty:
        statement = statement.where(Question.difficulty == difficulty)
    if excluded_ids:
        statement = statement.where(Question.id.not_in(excluded_ids))
    if topic:
        statement = statement.where(
            Question.title.ilike(f"%{topic}%")
            | Question.description.ilike(f"%{topic}%")
        )
    statement = statement.order_by(Question.created_at.desc(), Question.id)
    if language is None:
        return list((await session.scalars(statement.limit(limit))).all())

    matches: list[Question] = []
    batch_size = 200
    offset = 0
    while len(matches) < limit:
        batch = list(
            (
                await session.scalars(
                    statement.offset(offset).limit(batch_size)
                )
            ).all()
        )
        if not batch:
            break
        matches.extend(
            question
            for question in batch
            if question.expected_language == language
            or language in (question.supported_languages or [])
        )
        offset += len(batch)
        if len(batch) < batch_size:
            break
    return matches[:limit]


async def transition_question_status(
    session: AsyncSession,
    question: Question,
    expected: str,
    target: str,
    reviewer_id: UUID | None = None,
) -> None:
    if (expected, target) not in {
        (QuestionStatus.VALIDATED, QuestionStatus.APPROVED),
        (QuestionStatus.APPROVED, QuestionStatus.ACTIVE),
        (QuestionStatus.ACTIVE, QuestionStatus.DEPRECATED),
    }:
        raise QuestionEngineError(
            "Only validated->approved, approved->active, and active->deprecated "
            "transitions are allowed."
        )
    if question.status != expected:
        raise QuestionEngineError(
            f"Question must be {expected} before it can become {target}."
        )
    if reviewer_id is not None:
        lineage = await session.scalar(
            select(QuestionLlmLineage).where(
                QuestionLlmLineage.question_id == question.id
            )
        )
        if lineage is not None:
            metadata = dict(lineage.generation_metadata or {})
            reviews = list(metadata.get("lifecycle_reviews", []))
            reviews.append(
                {
                    "reviewer_id": str(reviewer_id),
                    "transition": f"{expected}->{target}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            metadata["lifecycle_reviews"] = reviews
            lineage.generation_metadata = metadata
    question.status = target
    await session.commit()
