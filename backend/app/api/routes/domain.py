"""Candidate, interview, and question API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.schemas.domain import (
    CandidateCreateRequest,
    CandidateResponse,
    InterviewCreateRequest,
    InterviewQuestionAssignmentRequest,
    InterviewQuestionBulkAssignmentRequest,
    InterviewQuestionResponse,
    InterviewProgressResponse,
    InterviewResponse,
    QuestionCreateRequest,
    QuestionResponse,
    QuestionTestCaseCreateRequest,
    QuestionTestCaseResponse,
)
from app.schemas.submission import SubmissionAttemptResponse
from app.schemas.results import AssessmentResultsResponse, QuestionResultResponse
from app.services.results_service import get_assessment_results
from app.services.database_service import (
    CandidateNotFoundError,
    DuplicateCandidateEmailError,
    create_candidate,
    create_interview_session,
    create_question,
    assign_question,
    assign_questions,
    get_interview_progress,
    transition_interview_session,
    InterviewSessionAlreadyClosedError,
    InterviewSessionNotFoundError,
    InterviewQuestionAssignmentConflictError,
    QuestionNotFoundError,
    list_assigned_questions,
    get_submission_attempts,
    get_latest_submission,
    SubmissionAttemptNotFoundError,
    UnassignedQuestionError,
    create_question_test_case,
    list_question_test_cases,
    TestCaseLimitExceededError,
)
from app.models.interview import InterviewStatus
from app.models.question import Question

router = APIRouter(prefix="/api/v1", tags=["domain"])


def _interview_response(interview) -> InterviewResponse:
    return InterviewResponse(
        interview_session_id=interview.id,
        candidate_id=interview.candidate_id,
        status=interview.status,
        started_at=interview.started_at,
        created_at=interview.created_at,
        completed_at=interview.completed_at,
    )


@router.post("/candidates", response_model=CandidateResponse, status_code=201)
async def create_candidate_route(
    request: CandidateCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> CandidateResponse:
    try:
        candidate = await create_candidate(session, request.name, request.email)
    except DuplicateCandidateEmailError as exc:
        raise HTTPException(status_code=409, detail="Candidate email already exists") from exc
    return CandidateResponse(
        candidate_id=candidate.id,
        name=candidate.name,
        email=candidate.email,
        created_at=candidate.created_at,
    )


@router.post("/interviews", response_model=InterviewResponse, status_code=201)
async def create_interview_route(
    request: InterviewCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> InterviewResponse:
    try:
        interview = await create_interview_session(
            session, request.candidate_id, status="active"
        )
    except CandidateNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Candidate not found") from exc
    return _interview_response(interview)


@router.get(
    "/interviews/{interview_session_id}",
    response_model=InterviewProgressResponse,
)
async def get_interview_route(
    interview_session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> InterviewProgressResponse:
    try:
        interview, total_questions, submitted_questions, submission_count = (
            await get_interview_progress(session, interview_session_id)
        )
    except InterviewSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    response = _interview_response(interview)
    return InterviewProgressResponse(
        **response.model_dump(),
        total_questions=total_questions,
        submitted_questions=submitted_questions,
        attempted_questions=submitted_questions,
        submission_count=submission_count,
    )


@router.get(
    "/interviews/{interview_session_id}/results",
    response_model=AssessmentResultsResponse,
)
async def get_interview_results_route(
    interview_session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> AssessmentResultsResponse:
    try:
        interview, question_results = await get_assessment_results(
            session, interview_session_id
        )
    except InterviewSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc

    total_passed = sum(item["passed_test_cases"] for item in question_results)
    total_cases = sum(item["total_test_cases"] for item in question_results)
    attempted = sum(
        item["latest_submission_id"] is not None for item in question_results
    )
    evaluated = sum(item["evaluation_status"] == "evaluated" for item in question_results)
    return AssessmentResultsResponse(
        interview_session_id=interview.id,
        interview_status=interview.status,
        total_questions=len(question_results),
        attempted_questions=attempted,
        evaluated_questions=evaluated,
        total_passed_test_cases=total_passed,
        total_test_cases=total_cases,
        overall_score=(
            total_passed / total_cases * 100 if total_cases else None
        ),
        status="scored" if total_cases else "not_scored",
        questions=[
            QuestionResultResponse(**item) for item in question_results
        ],
    )


async def _close_interview(
    interview_session_id: UUID,
    target_status: InterviewStatus,
    session: AsyncSession,
) -> InterviewResponse:
    try:
        interview = await transition_interview_session(
            session, interview_session_id, target_status
        )
    except InterviewSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    except InterviewSessionAlreadyClosedError as exc:
        raise HTTPException(
            status_code=409, detail="Interview session is already closed"
        ) from exc
    return _interview_response(interview)


@router.post(
    "/interviews/{interview_session_id}/complete",
    response_model=InterviewResponse,
)
async def complete_interview_route(
    interview_session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> InterviewResponse:
    return await _close_interview(interview_session_id, InterviewStatus.COMPLETED, session)


@router.post(
    "/interviews/{interview_session_id}/cancel",
    response_model=InterviewResponse,
)
async def cancel_interview_route(
    interview_session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> InterviewResponse:
    return await _close_interview(interview_session_id, InterviewStatus.CANCELLED, session)


def _assigned_question_response(assignment, question) -> InterviewQuestionResponse:
    return InterviewQuestionResponse(
        question_id=question.id,
        sequence_number=assignment.sequence_number,
        title=question.title,
        description=question.description,
        difficulty=question.difficulty,
        expected_language=question.expected_language,
        created_at=question.created_at,
    )


def _submission_attempt_response(submission) -> SubmissionAttemptResponse:
    return SubmissionAttemptResponse(
        submission_id=str(submission.id),
        question_id=submission.question_id,
        language=submission.language,
        source_code=submission.source_code,
        stdin=submission.stdin,
        status=submission.status,
        stdout=submission.stdout,
        stderr=submission.stderr,
        exit_code=submission.exit_code,
        execution_time_ms=submission.execution_time_ms,
        timed_out=submission.timed_out,
        created_at=submission.created_at,
    )


async def _submission_attempts(
    interview_session_id: UUID,
    question_id: UUID,
    session: AsyncSession,
) -> list:
    try:
        return await get_submission_attempts(session, interview_session_id, question_id)
    except InterviewSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    except QuestionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Question not found") from exc
    except UnassignedQuestionError as exc:
        raise HTTPException(
            status_code=409, detail="Question is not assigned to this interview session"
        ) from exc


@router.get(
    "/interviews/{interview_session_id}/questions/{question_id}/submissions",
    response_model=list[SubmissionAttemptResponse],
)
async def list_submission_attempts_route(
    interview_session_id: UUID,
    question_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[SubmissionAttemptResponse]:
    attempts = await _submission_attempts(interview_session_id, question_id, session)
    return [_submission_attempt_response(attempt) for attempt in attempts]


@router.get(
    "/interviews/{interview_session_id}/questions/{question_id}/latest-submission",
    response_model=SubmissionAttemptResponse,
)
async def latest_submission_route(
    interview_session_id: UUID,
    question_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> SubmissionAttemptResponse:
    try:
        submission = await get_latest_submission(
            session, interview_session_id, question_id
        )
    except InterviewSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    except QuestionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Question not found") from exc
    except UnassignedQuestionError as exc:
        raise HTTPException(
            status_code=409, detail="Question is not assigned to this interview session"
        ) from exc
    except SubmissionAttemptNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Submission not found") from exc
    return _submission_attempt_response(submission)


@router.post(
    "/interviews/{interview_session_id}/questions",
    response_model=InterviewQuestionResponse,
    status_code=201,
)
async def assign_question_route(
    interview_session_id: UUID,
    request: InterviewQuestionAssignmentRequest,
    session: AsyncSession = Depends(get_db_session),
) -> InterviewQuestionResponse:
    try:
        assignment = await assign_question(
            session,
            interview_session_id,
            request.question_id,
            request.sequence_number,
        )
    except InterviewSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    except QuestionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Question not found") from exc
    except InterviewSessionAlreadyClosedError as exc:
        raise HTTPException(
            status_code=409, detail="Interview session is not active"
        ) from exc
    except InterviewQuestionAssignmentConflictError as exc:
        raise HTTPException(
            status_code=409, detail="Question assignment conflicts with this interview"
        ) from exc
    question = await session.get(Question, request.question_id)
    return _assigned_question_response(assignment, question)


@router.post(
    "/interviews/{interview_session_id}/questions/bulk",
    response_model=list[InterviewQuestionResponse],
    status_code=201,
)
async def assign_questions_bulk_route(
    interview_session_id: UUID,
    request: InterviewQuestionBulkAssignmentRequest,
    session: AsyncSession = Depends(get_db_session),
) -> list[InterviewQuestionResponse]:
    try:
        assignments = await assign_questions(
            session,
            interview_session_id,
            [(item.question_id, item.sequence_number) for item in request.questions],
        )
    except InterviewSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    except QuestionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Question not found") from exc
    except InterviewSessionAlreadyClosedError as exc:
        raise HTTPException(
            status_code=409, detail="Interview session is not active"
        ) from exc
    except InterviewQuestionAssignmentConflictError as exc:
        raise HTTPException(
            status_code=409, detail="Question assignment conflicts with this interview"
        ) from exc
    questions = {
        question.id: question
        for question in (
            await session.scalars(
                select(Question).where(
                    Question.id.in_([item.question_id for item in request.questions])
                )
            )
        ).all()
    }
    return [
        _assigned_question_response(assignment, questions[assignment.question_id])
        for assignment in assignments
    ]


@router.get(
    "/interviews/{interview_session_id}/questions",
    response_model=list[InterviewQuestionResponse],
)
async def list_questions_route(
    interview_session_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[InterviewQuestionResponse]:
    try:
        assignments = await list_assigned_questions(session, interview_session_id)
    except InterviewSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Interview session not found") from exc
    return [
        _assigned_question_response(assignment, question)
        for assignment, question in assignments
    ]


@router.post("/questions", response_model=QuestionResponse, status_code=201)
async def create_question_route(
    request: QuestionCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> QuestionResponse:
    question = await create_question(
        session,
        request.title,
        request.description,
        request.difficulty,
        request.expected_language,
    )
    return QuestionResponse(
        question_id=question.id,
        title=question.title,
        description=question.description,
        difficulty=question.difficulty,
        expected_language=question.expected_language,
        created_at=question.created_at,
    )


def _test_case_response(test_case) -> QuestionTestCaseResponse:
    return QuestionTestCaseResponse(
        test_case_id=test_case.id,
        question_id=test_case.question_id,
        stdin=test_case.stdin,
        expected_stdout=test_case.expected_stdout,
        time_limit_ms=test_case.time_limit_ms,
        description=test_case.description,
        created_at=test_case.created_at,
    )


@router.post(
    "/questions/{question_id}/test-cases",
    response_model=QuestionTestCaseResponse,
    status_code=201,
)
async def create_test_case_route(
    question_id: UUID,
    request: QuestionTestCaseCreateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> QuestionTestCaseResponse:
    try:
        test_case = await create_question_test_case(
            session,
            question_id,
            request.stdin,
            request.expected_stdout,
            request.time_limit_ms,
            request.description,
        )
    except QuestionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Question not found") from exc
    except TestCaseLimitExceededError as exc:
        raise HTTPException(
            status_code=409, detail="Question has reached the test-case limit"
        ) from exc
    return _test_case_response(test_case)


@router.get(
    "/questions/{question_id}/test-cases",
    response_model=list[QuestionTestCaseResponse],
)
async def list_test_cases_route(
    question_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[QuestionTestCaseResponse]:
    try:
        test_cases = await list_question_test_cases(session, question_id)
    except QuestionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Question not found") from exc
    return [_test_case_response(test_case) for test_case in test_cases]
