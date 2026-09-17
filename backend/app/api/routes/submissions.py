"""Code submission API routes."""

from collections.abc import Callable
import logging
from uuid import UUID

from docker.errors import DockerException
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db_session
from app.core.security import get_current_active_user
from app.models.candidate import Candidate
from app.models.interview import InterviewSession
from app.models.submission import Submission
from app.models.user import User
from app.schemas.submission import (
    CodeSubmissionRequest,
    CodeSubmissionResponse,
    EvaluationResponse,
    EvaluationCaseResponse,
    SubmissionStatusResponse,
)
from app.services.sandbox_service import DockerSandboxService
from app.services.submission_service import enqueue_submission
from app.services.database_service import (
    DatabasePersistenceError,
    InactiveInterviewSessionError,
    InterviewSessionNotFoundError,
    QuestionNotFoundError,
    UnassignedQuestionError,
    SubmissionNotFoundError,
    get_evaluation_result,
    get_submission_for_evaluation,
    get_submission_with_job,
)
from app.services.evaluation_service import (
    evaluate_submission,
    SubmissionExecutionIncompleteError,
)

router = APIRouter(prefix="/api/v1/submissions", tags=["submissions"])
logger = logging.getLogger(__name__)


async def _ensure_submission_access(
    session: AsyncSession,
    current_user: User | None,
    interview_session_id: UUID,
) -> None:
    if not settings.jwt_secret or current_user is None:
        return
    if current_user.role in {"admin", "interviewer"}:
        return
    interview = await session.get(InterviewSession, interview_session_id)
    if interview is None:
        raise HTTPException(status_code=404, detail="Interview session not found")
    candidate = await session.scalar(select(Candidate).where(Candidate.id == interview.candidate_id))
    if candidate is None or candidate.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")


def get_sandbox_service() -> Callable[[], DockerSandboxService]:
    """Provide a lazy Docker sandbox factory for a request."""
    return DockerSandboxService


def _evaluation_response(result) -> EvaluationResponse:
    return EvaluationResponse(
        submission_id=result.submission_id,
        evaluation_result_id=result.id,
        status=result.status,
        total_test_cases=result.total_test_cases,
        passed_test_cases=result.passed_test_cases,
        failed_test_cases=result.failed_test_cases,
        score=result.score,
        test_cases=[
            EvaluationCaseResponse(**case) for case in (result.case_results or [])
        ],
        created_at=result.created_at,
    )


@router.post(
    "",
    response_model=CodeSubmissionResponse,
    status_code=status.HTTP_200_OK,
)
async def submit_code(
    request: CodeSubmissionRequest,
    session: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_active_user),
) -> CodeSubmissionResponse:
    """Validate and enqueue a submission without executing Docker inline."""
    await _ensure_submission_access(session, current_user, request.interview_session_id)
    try:
        submission_id, job_id = await enqueue_submission(request, session)
    except InterviewSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    except QuestionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Question not found") from exc
    except InactiveInterviewSessionError as exc:
        raise HTTPException(
            status_code=409, detail="Interview session is not active"
        ) from exc
    except UnassignedQuestionError as exc:
        raise HTTPException(
            status_code=409, detail="Question is not assigned to this interview session"
        ) from exc
    except DatabasePersistenceError as exc:
        raise HTTPException(
            status_code=500, detail="Submission persistence failed."
        ) from exc
    return CodeSubmissionResponse(
        submission_id=submission_id,
        job_id=job_id,
        job_status="queued",
        interview_session_id=request.interview_session_id,
        question_id=request.question_id,
        status="queued",
        message="Submission queued for execution.",
        execution_time_ms=None,
    )


@router.get(
    "/{submission_id}/status",
    response_model=SubmissionStatusResponse,
)
async def get_submission_status_route(
    submission_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_active_user),
) -> SubmissionStatusResponse:
    try:
        submission, job = await get_submission_with_job(session, submission_id)
    except SubmissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Submission not found") from exc
    await _ensure_submission_access(session, current_user, submission.interview_session_id)
    return SubmissionStatusResponse(
        submission_id=submission.id,
        job_id=job.id,
        job_status=job.status,
        submission_status=submission.status,
        stdout=submission.stdout if job.status == "succeeded" else None,
        stderr=submission.stderr if job.status == "succeeded" else None,
        exit_code=submission.exit_code if job.status == "succeeded" else None,
        execution_time_ms=(
            submission.execution_time_ms if job.status == "succeeded" else None
        ),
        timed_out=submission.timed_out if job.status == "succeeded" else None,
    )


@router.post(
    "/{submission_id}/evaluate",
    response_model=EvaluationResponse,
)
async def evaluate_submission_route(
    submission_id: UUID,
    sandbox_factory: Callable[[], DockerSandboxService] = Depends(get_sandbox_service),
    session: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_active_user),
) -> EvaluationResponse:
    try:
        submission = await session.get(Submission, submission_id)
        if submission is not None:
            await _ensure_submission_access(session, current_user, submission.interview_session_id)
        result = await evaluate_submission(
            session, submission_id, sandbox_factory()
        )
    except SubmissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Submission not found") from exc
    except SubmissionExecutionIncompleteError as exc:
        raise HTTPException(
            status_code=409, detail="Submission execution is not complete"
        ) from exc
    except DockerException as exc:
        logger.exception("Sandbox evaluation failed")
        raise HTTPException(
            status_code=500, detail="Sandbox evaluation failed."
        ) from exc
    return _evaluation_response(result)


@router.get(
    "/{submission_id}/evaluation",
    response_model=EvaluationResponse,
)
async def get_evaluation_route(
    submission_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User | None = Depends(get_current_active_user),
) -> EvaluationResponse:
    try:
        submission = await get_submission_for_evaluation(session, submission_id)
    except SubmissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Submission not found") from exc
    await _ensure_submission_access(session, current_user, submission.interview_session_id)
    result = await get_evaluation_result(session, submission_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return _evaluation_response(result)
