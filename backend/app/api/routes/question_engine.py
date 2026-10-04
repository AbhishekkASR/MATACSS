"""Question Engine authoring routes and candidate assessment start/resume."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.llm_provider import LLMProviderError
from app.core.security import require_roles
from app.models.candidate import Candidate
from app.models.assessment_feedback import AssessmentFeedback
from app.models.evaluation import EvaluationResult
from app.models.interview import InterviewSession, InterviewStatus
from app.models.interview_question import InterviewQuestion
from app.models.question import Question, QuestionStatus
from app.models.submission import Submission
from app.models.user import User
from app.orchestration.interviewer import (
    InterviewerDecision,
    InterviewerNextStepAction,
    InterviewerNextStepRecommendation,
)
from app.question_bank.engine import (
    MAX_PROMPT_CHARS,
    QuestionEngineError,
    QuestionGenerationRequest,
    TrustedValidationRequest,
    adapt_question,
    generate_question,
    retrieve_active_questions,
    transition_question_status,
    validate_draft,
)
from app.services.database_service import (
    CandidateNotFoundError,
    InactiveInterviewSessionError,
    InterviewSessionAlreadyClosedError,
    InterviewQuestionAssignmentConflictError,
    QuestionNotActiveError,
    assign_question,
    create_interview_session,
    transition_interview_session,
)

router = APIRouter(prefix="/api/v1/question-engine", tags=["question-engine"])


async def require_admin(
    current_user: User | None = Depends(require_roles("admin")),
) -> User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def require_candidate(
    current_user: User | None = Depends(require_roles("candidate")),
) -> User:
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Candidate authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


class AssessmentStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    topic: str | None = Field(default=None, max_length=100)
    difficulty: Literal["easy", "medium", "hard"] | None = None
    language: Literal["python", "cpp", "java"] | None = None


class QuestionEngineResponse(BaseModel):
    question_id: UUID
    title: str
    description: str
    difficulty: str
    expected_language: str | None
    status: str
    origin: str
    model: str | None
    request_id: str | None = None


class QuestionRetrievalResponse(BaseModel):
    question_id: UUID
    title: str
    description: str
    difficulty: str
    expected_language: str | None
    input_format: str | None
    output_format: str | None
    constraints_text: str | None
    supported_languages: list[str] | None
    starter_code: str | None
    status: str


class AssessmentStartResponse(BaseModel):
    interview_session_id: UUID
    candidate_id: UUID
    status: str
    current_question: QuestionRetrievalResponse | None


class QuestionLifecycleTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_status: Literal["approved", "active", "deprecated"]


def _response(question: Question, request_id: str | None) -> QuestionEngineResponse:
    lineage = question.llm_lineage
    return QuestionEngineResponse(
        question_id=question.id,
        title=question.title,
        description=question.description,
        difficulty=question.difficulty,
        expected_language=question.expected_language,
        status=question.status,
        origin=lineage.origin if lineage else "unknown",
        model=lineage.model if lineage else None,
        request_id=request_id,
    )


def _question_contract(question: Question) -> QuestionRetrievalResponse:
    return QuestionRetrievalResponse(
        question_id=question.id,
        title=question.title,
        description=question.description,
        difficulty=question.difficulty,
        expected_language=question.expected_language,
        input_format=question.input_format,
        output_format=question.output_format,
        constraints_text=question.constraints_text,
        supported_languages=question.supported_languages,
        starter_code=question.starter_code,
        status=question.status,
    )


async def _current_question(
    session: AsyncSession, interview: InterviewSession
) -> Question | None:
    attempted = exists(
        select(Submission.id).where(
            Submission.interview_session_id == interview.id,
            Submission.question_id == InterviewQuestion.question_id,
        )
    )
    row = await session.execute(
        select(Question)
        .join(InterviewQuestion, InterviewQuestion.question_id == Question.id)
        .where(
            InterviewQuestion.interview_session_id == interview.id,
            ~attempted,
        )
        .order_by(InterviewQuestion.sequence_number.asc())
        .limit(1)
    )
    return row.scalar_one_or_none()


async def _advance_assessment(
    session: AsyncSession,
    candidate: Candidate,
    interview: InterviewSession,
) -> AssessmentStartResponse:
    """Use a persisted advisory plan to assign the next active question once."""
    if interview.status != "active":
        return AssessmentStartResponse(
            interview_session_id=interview.id,
            candidate_id=candidate.id,
            status=interview.status,
            current_question=None,
        )

    current_question = await _current_question(session, interview)
    if current_question is not None:
        return AssessmentStartResponse(
            interview_session_id=interview.id,
            candidate_id=candidate.id,
            status=interview.status,
            current_question=_question_contract(current_question),
        )

    latest_submission = await session.scalar(
        select(Submission)
        .where(Submission.interview_session_id == interview.id)
        .order_by(Submission.created_at.desc(), Submission.id.desc())
        .limit(1)
    )
    if latest_submission is None or await session.scalar(
        select(EvaluationResult.id).where(
            EvaluationResult.submission_id == latest_submission.id
        )
    ) is None:
        raise HTTPException(
            status_code=409,
            detail="Evaluate the latest submission before requesting another question.",
        )

    recommendation = InterviewerNextStepRecommendation(
        action=InterviewerNextStepAction.CONTINUE
    )
    feedback = await session.scalar(
        select(AssessmentFeedback).where(
            AssessmentFeedback.submission_id == latest_submission.id,
            AssessmentFeedback.status == "completed",
        )
    )
    if feedback is not None and feedback.interviewer_feedback is not None:
        try:
            recommendation = InterviewerDecision.model_validate(
                feedback.interviewer_feedback
            ).next_step
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=500,
                detail="The saved interviewer recommendation is invalid.",
            ) from exc

    if recommendation.action == InterviewerNextStepAction.FINISH:
        try:
            completed = await transition_interview_session(
                session, interview.id, InterviewStatus.COMPLETED
            )
        except InterviewSessionAlreadyClosedError as exc:
            raise HTTPException(
                status_code=409, detail="Assessment is no longer active."
            ) from exc
        return AssessmentStartResponse(
            interview_session_id=completed.id,
            candidate_id=candidate.id,
            status=completed.status,
            current_question=None,
        )

    filters = {
        "topic": recommendation.topic,
        "difficulty": recommendation.difficulty,
        "language": recommendation.language,
        "candidate_id": candidate.id,
        "limit": 1,
    }
    available = await retrieve_active_questions(session, **filters)
    if not available and any(
        filters[key] is not None for key in ("topic", "difficulty", "language")
    ):
        available = await retrieve_active_questions(
            session,
            candidate_id=candidate.id,
            limit=1,
        )
    if not available:
        raise HTTPException(
            status_code=409,
            detail="No active, non-repeated question is available for this assessment.",
        )

    sequence_number = (
        await session.scalar(
            select(func.max(InterviewQuestion.sequence_number)).where(
                InterviewQuestion.interview_session_id == interview.id
            )
        )
        or 0
    ) + 1
    question = available[0]
    try:
        await assign_question(
            session,
            interview.id,
            question.id,
            sequence_number,
            commit=False,
        )
        await session.commit()
        await session.refresh(question)
    except (
        InactiveInterviewSessionError,
        QuestionNotActiveError,
        InterviewQuestionAssignmentConflictError,
    ) as exc:
        await session.rollback()
        current_question = await _current_question(session, interview)
        if current_question is not None:
            return AssessmentStartResponse(
                interview_session_id=interview.id,
                candidate_id=candidate.id,
                status=interview.status,
                current_question=_question_contract(current_question),
            )
        raise HTTPException(
            status_code=409,
            detail="The next question could not be assigned; please retry.",
        ) from exc
    except Exception:
        await session.rollback()
        raise
    return AssessmentStartResponse(
        interview_session_id=interview.id,
        candidate_id=candidate.id,
        status=interview.status,
        current_question=_question_contract(question),
    )


def _raise_provider_error(exc: Exception) -> None:
    if isinstance(exc, QuestionEngineError):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if isinstance(exc, LLMProviderError):
        raise HTTPException(
            status_code=502, detail="Question generation provider failed."
        ) from exc
    raise exc


@router.post("/assessments/start", response_model=AssessmentStartResponse, status_code=201)
async def start_assessment_route(
    request: AssessmentStartRequest,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    candidate_user: User = Depends(require_candidate),
) -> AssessmentStartResponse:
    candidate = await session.scalar(
        select(Candidate)
        .where(Candidate.user_id == candidate_user.id)
        .with_for_update()
    )
    if candidate is None:
        raise HTTPException(
            status_code=404,
            detail="No candidate profile is linked to the authenticated user.",
        )

    existing_interview = await session.scalar(
        select(InterviewSession)
        .where(
            InterviewSession.candidate_id == candidate.id,
            InterviewSession.status == "active",
        )
        .order_by(InterviewSession.created_at.desc(), InterviewSession.id.desc())
        .limit(1)
    )
    if existing_interview is not None:
        response.status_code = status.HTTP_200_OK
        return await _advance_assessment(session, candidate, existing_interview)

    try:
        available = await retrieve_active_questions(
            session,
            topic=request.topic,
            difficulty=request.difficulty,
            language=request.language,
            candidate_id=candidate.id,
            limit=1,
        )
    except QuestionEngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not available:
        raise HTTPException(
            status_code=409,
            detail="No active, non-repeated question matches the requested filters.",
        )

    question = available[0]
    try:
        interview = await create_interview_session(
            session, candidate.id, commit=False
        )
        await assign_question(
            session,
            interview.id,
            question.id,
            sequence_number=1,
            commit=False,
        )
        await session.commit()
        await session.refresh(interview)
    except (
        CandidateNotFoundError,
        QuestionNotActiveError,
        InterviewQuestionAssignmentConflictError,
    ) as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Assessment could not be started; please retry.",
        ) from exc
    except Exception:
        await session.rollback()
        raise

    return AssessmentStartResponse(
        interview_session_id=interview.id,
        candidate_id=candidate.id,
        status=interview.status,
        current_question=_question_contract(question),
    )


@router.get("/assessments/{interview_session_id}/resume", response_model=AssessmentStartResponse)
async def resume_assessment_route(
    interview_session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    candidate_user: User = Depends(require_candidate),
) -> AssessmentStartResponse:
    candidate = await session.scalar(
        select(Candidate).where(Candidate.user_id == candidate_user.id)
    )
    if candidate is None:
        raise HTTPException(
            status_code=404,
            detail="No candidate profile is linked to the authenticated user.",
        )
    interview = await session.scalar(
        select(InterviewSession).where(
            InterviewSession.id == interview_session_id,
            InterviewSession.candidate_id == candidate.id,
        )
    )
    if interview is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    if interview.status != "active":
        return AssessmentStartResponse(
            interview_session_id=interview.id,
            candidate_id=candidate.id,
            status=interview.status,
            current_question=None,
        )
    question = await _current_question(session, interview)
    if question is None:
        raise HTTPException(
            status_code=409, detail="Assessment has no unanswered assigned question."
        )
    return AssessmentStartResponse(
        interview_session_id=interview.id,
        candidate_id=candidate.id,
        status=interview.status,
        current_question=_question_contract(question),
    )


@router.post(
    "/assessments/{interview_session_id}/next",
    response_model=AssessmentStartResponse,
)
async def next_assessment_route(
    interview_session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    candidate_user: User = Depends(require_candidate),
) -> AssessmentStartResponse:
    candidate = await session.scalar(
        select(Candidate)
        .where(Candidate.user_id == candidate_user.id)
        .with_for_update()
    )
    if candidate is None:
        raise HTTPException(
            status_code=404,
            detail="No candidate profile is linked to the authenticated user.",
        )
    interview = await session.scalar(
        select(InterviewSession)
        .where(
            InterviewSession.id == interview_session_id,
            InterviewSession.candidate_id == candidate.id,
        )
        .with_for_update()
    )
    if interview is None:
        raise HTTPException(status_code=404, detail="Assessment not found.")
    return await _advance_assessment(session, candidate, interview)


@router.post("/generate", response_model=QuestionEngineResponse, status_code=201)
async def generate_question_route(
    request: QuestionGenerationRequest,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
) -> QuestionEngineResponse:
    if len(request.prompt) > MAX_PROMPT_CHARS:
        raise HTTPException(status_code=413, detail="Prompt exceeds the permitted size.")
    try:
        question, request_id = await generate_question(session, request)
    except (QuestionEngineError, LLMProviderError) as exc:
        _raise_provider_error(exc)
    return _response(question, request_id)


@router.post(
    "/questions/{parent_id}/adapt",
    response_model=QuestionEngineResponse,
    status_code=201,
)
async def adapt_question_route(
    parent_id: UUID,
    request: QuestionGenerationRequest,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
) -> QuestionEngineResponse:
    parent = await session.get(Question, parent_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Parent question not found.")
    try:
        question, request_id = await adapt_question(session, parent_id, request)
    except (QuestionEngineError, LLMProviderError) as exc:
        _raise_provider_error(exc)
    return _response(question, request_id)


@router.post("/questions/{question_id}/validate", status_code=204)
async def validate_question_route(
    question_id: UUID,
    request: TrustedValidationRequest,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(require_admin),
) -> None:
    question = await session.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    try:
        await validate_draft(session, question, request, admin.id)
    except QuestionEngineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/questions/{question_id}/transition", status_code=204)
async def transition_question_route(
    question_id: UUID,
    request: QuestionLifecycleTransitionRequest,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(require_admin),
) -> None:
    question = await session.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    required_predecessor = {
        QuestionStatus.APPROVED: QuestionStatus.VALIDATED,
        QuestionStatus.ACTIVE: QuestionStatus.APPROVED,
        QuestionStatus.DEPRECATED: QuestionStatus.ACTIVE,
    }[request.target_status]
    try:
        await transition_question_status(
            session,
            question,
            required_predecessor,
            request.target_status,
            admin.id,
        )
    except QuestionEngineError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/retrieve", response_model=list[QuestionRetrievalResponse])
async def retrieve_questions_route(
    topic: str | None = Query(default=None, max_length=100),
    difficulty: str | None = Query(default=None),
    language: str | None = Query(default=None),
    interview_session_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
) -> list[QuestionRetrievalResponse]:
    try:
        questions = await retrieve_active_questions(
            session,
            topic=topic,
            difficulty=difficulty,
            language=language,
            interview_session_id=interview_session_id,
            limit=limit,
        )
    except QuestionEngineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [
        QuestionRetrievalResponse(
            question_id=question.id,
            title=question.title,
            description=question.description,
            difficulty=question.difficulty,
            expected_language=question.expected_language,
            input_format=question.input_format,
            output_format=question.output_format,
            constraints_text=question.constraints_text,
            supported_languages=question.supported_languages,
            starter_code=question.starter_code,
            status=question.status,
        )
        for question in questions
    ]
