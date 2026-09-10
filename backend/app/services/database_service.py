"""Persistence services for database-backed interview entities."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import func, select

from app.models.candidate import Candidate
from app.models.interview import InterviewSession, InterviewStatus
from app.models.interview_question import InterviewQuestion
from app.models.question import Question
from app.models.submission import Submission
from app.models.question_test_case import QuestionTestCase
from app.models.evaluation import EvaluationResult
from app.models.execution_job import ExecutionJob
from app.schemas.execution import ExecutionResult


class DuplicateCandidateEmailError(Exception):
    """Raised when a candidate email is already registered."""


class CandidateNotFoundError(Exception):
    """Raised when an interview references an unknown candidate."""


class InterviewSessionNotFoundError(Exception):
    """Raised when a submission references an unknown interview session."""


class QuestionNotFoundError(Exception):
    """Raised when a submission references an unknown question."""


class InactiveInterviewSessionError(Exception):
    """Raised when a submission targets an inactive interview session."""


class DatabasePersistenceError(Exception):
    """Raised when a persistence operation cannot be completed."""


class TestCaseLimitExceededError(Exception):
    """Raised when a question would exceed the bounded evaluation workload."""


class InterviewSessionAlreadyClosedError(Exception):
    """Raised when a closed interview cannot transition again."""


class InterviewQuestionAssignmentConflictError(Exception):
    """Raised when an assignment violates a session uniqueness rule."""


class UnassignedQuestionError(Exception):
    """Raised when a submission targets a question outside the interview."""


class SubmissionAttemptNotFoundError(Exception):
    """Raised when a requested question has no persisted submission attempts."""


class SubmissionNotFoundError(Exception):
    """Raised when an evaluation targets an unknown submission."""


class SubmissionExecutionIncompleteError(Exception):
    """Raised when evaluation is requested before execution completes."""


class ExecutionJobNotFoundError(Exception):
    """Raised when a submission has no execution job."""


async def create_candidate(session: AsyncSession, name: str, email: str) -> Candidate:
    candidate = Candidate(name=name, email=email)
    session.add(candidate)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateCandidateEmailError from exc
    await session.refresh(candidate)
    return candidate


async def create_interview_session(
    session: AsyncSession,
    candidate_id: UUID,
    status: str = InterviewStatus.ACTIVE,
) -> InterviewSession:
    candidate = await session.scalar(
        select(Candidate).where(Candidate.id == candidate_id)
    )
    if candidate is None:
        raise CandidateNotFoundError
    interview = InterviewSession(
        candidate_id=candidate_id,
        status=status,
        started_at=datetime.now(timezone.utc) if status == "active" else None,
    )
    session.add(interview)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise
    await session.refresh(interview)
    return interview


async def get_interview_progress(
    session: AsyncSession, interview_session_id: UUID
) -> tuple[InterviewSession, int, int, int]:
    """Return an interview and aggregate progress without exposing ORM objects."""
    interview = await session.scalar(
        select(InterviewSession).where(InterviewSession.id == interview_session_id)
    )
    if interview is None:
        raise InterviewSessionNotFoundError

    total_questions = await session.scalar(
        select(func.count(InterviewQuestion.id)).where(
            InterviewQuestion.interview_session_id == interview_session_id
        )
    ) or 0
    submission_count = await session.scalar(
        select(func.count(Submission.id)).where(
            Submission.interview_session_id == interview_session_id
        )
    ) or 0
    submitted_questions = await session.scalar(
        select(func.count(func.distinct(Submission.question_id)))
        .join(
            InterviewQuestion,
            (InterviewQuestion.question_id == Submission.question_id)
            & (
                InterviewQuestion.interview_session_id
                == Submission.interview_session_id
            ),
        )
        .where(Submission.interview_session_id == interview_session_id)
    ) or 0
    return interview, total_questions, submitted_questions, submission_count


async def _get_active_interview(
    session: AsyncSession, interview_session_id: UUID
) -> InterviewSession:
    interview = await session.scalar(
        select(InterviewSession).where(InterviewSession.id == interview_session_id)
    )
    if interview is None:
        raise InterviewSessionNotFoundError
    if interview.status != InterviewStatus.ACTIVE:
        raise InterviewSessionAlreadyClosedError
    return interview


async def assign_question(
    session: AsyncSession,
    interview_session_id: UUID,
    question_id: UUID,
    sequence_number: int,
) -> InterviewQuestion:
    await _get_active_interview(session, interview_session_id)
    question = await session.scalar(select(Question).where(Question.id == question_id))
    if question is None:
        raise QuestionNotFoundError

    assignment = InterviewQuestion(
        interview_session_id=interview_session_id,
        question_id=question_id,
        sequence_number=sequence_number,
    )
    session.add(assignment)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise InterviewQuestionAssignmentConflictError from exc
    await session.refresh(assignment)
    return assignment


async def assign_questions(
    session: AsyncSession,
    interview_session_id: UUID,
    assignments: list[tuple[UUID, int]],
) -> list[InterviewQuestion]:
    await _get_active_interview(session, interview_session_id)
    question_ids = [question_id for question_id, _ in assignments]
    questions = (
        await session.scalars(select(Question).where(Question.id.in_(question_ids)))
    ).all()
    if len(questions) != len(question_ids):
        raise QuestionNotFoundError

    records = [
        InterviewQuestion(
            interview_session_id=interview_session_id,
            question_id=question_id,
            sequence_number=sequence_number,
        )
        for question_id, sequence_number in assignments
    ]
    session.add_all(records)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise InterviewQuestionAssignmentConflictError from exc
    for record in records:
        await session.refresh(record)
    return records


async def list_assigned_questions(
    session: AsyncSession, interview_session_id: UUID
) -> list[tuple[InterviewQuestion, Question]]:
    interview = await session.scalar(
        select(InterviewSession).where(InterviewSession.id == interview_session_id)
    )
    if interview is None:
        raise InterviewSessionNotFoundError
    rows = await session.execute(
        select(InterviewQuestion, Question)
        .join(Question, Question.id == InterviewQuestion.question_id)
        .where(InterviewQuestion.interview_session_id == interview_session_id)
        .order_by(InterviewQuestion.sequence_number.asc())
    )
    return list(rows.all())


async def ensure_question_assigned(
    session: AsyncSession, interview_session_id: UUID, question_id: UUID
) -> None:
    assignment = await session.scalar(
        select(InterviewQuestion).where(
            InterviewQuestion.interview_session_id == interview_session_id,
            InterviewQuestion.question_id == question_id,
        )
    )
    if assignment is None:
        raise UnassignedQuestionError


async def get_submission_attempts(
    session: AsyncSession, interview_session_id: UUID, question_id: UUID
) -> list[Submission]:
    """Return attempts newest first after validating the assessment boundary."""
    interview = await session.scalar(
        select(InterviewSession).where(InterviewSession.id == interview_session_id)
    )
    if interview is None:
        raise InterviewSessionNotFoundError
    question = await session.scalar(select(Question).where(Question.id == question_id))
    if question is None:
        raise QuestionNotFoundError
    await ensure_question_assigned(session, interview_session_id, question_id)
    result = await session.scalars(
        select(Submission)
        .where(
            Submission.interview_session_id == interview_session_id,
            Submission.question_id == question_id,
        )
        .order_by(Submission.created_at.desc(), Submission.id.desc())
    )
    return list(result.all())


async def get_latest_submission(
    session: AsyncSession, interview_session_id: UUID, question_id: UUID
) -> Submission:
    attempts = await get_submission_attempts(
        session, interview_session_id, question_id
    )
    if not attempts:
        raise SubmissionAttemptNotFoundError
    return attempts[0]


async def create_question_test_case(
    session: AsyncSession,
    question_id: UUID,
    stdin: str,
    expected_stdout: str,
    time_limit_ms: int | None,
    description: str | None,
) -> QuestionTestCase:
    from datetime import datetime, timezone

    question = await session.scalar(select(Question).where(Question.id == question_id))
    if question is None:
        raise QuestionNotFoundError
    existing_count = await session.scalar(
        select(func.count(QuestionTestCase.id)).where(
            QuestionTestCase.question_id == question_id
        )
    )
    if existing_count is not None and existing_count >= 100:
        raise TestCaseLimitExceededError
    test_case = QuestionTestCase(
        question_id=question_id,
        stdin=stdin,
        expected_stdout=expected_stdout,
        time_limit_ms=time_limit_ms,
        description=description,
        created_at=datetime.now(timezone.utc),
    )
    session.add(test_case)
    await session.commit()
    await session.refresh(test_case)
    return test_case


async def list_question_test_cases(
    session: AsyncSession, question_id: UUID
) -> list[QuestionTestCase]:
    question = await session.scalar(select(Question).where(Question.id == question_id))
    if question is None:
        raise QuestionNotFoundError
    result = await session.scalars(
        select(QuestionTestCase)
        .where(QuestionTestCase.question_id == question_id)
        .order_by(QuestionTestCase.created_at.asc(), QuestionTestCase.id.asc())
    )
    return list(result.all())


async def get_submission_for_evaluation(
    session: AsyncSession, submission_id: UUID
) -> Submission:
    submission = await session.scalar(
        select(Submission).where(Submission.id == submission_id)
    )
    if submission is None:
        raise SubmissionNotFoundError
    return submission


async def get_evaluation_result(
    session: AsyncSession, submission_id: UUID
) -> EvaluationResult | None:
    return await session.scalar(
        select(EvaluationResult).where(EvaluationResult.submission_id == submission_id)
    )


async def transition_interview_session(
    session: AsyncSession, interview_session_id: UUID, target_status: InterviewStatus
) -> InterviewSession:
    """Transition an active interview while locking the row for this transaction."""
    interview = await session.scalar(
        select(InterviewSession)
        .where(InterviewSession.id == interview_session_id)
        .with_for_update()
    )
    if interview is None:
        raise InterviewSessionNotFoundError
    if interview.status != InterviewStatus.ACTIVE:
        raise InterviewSessionAlreadyClosedError

    interview.status = target_status
    interview.completed_at = datetime.now(timezone.utc)
    try:
        await session.commit()
    except SQLAlchemyError:
        await session.rollback()
        raise
    await session.refresh(interview)
    return interview


async def create_question(
    session: AsyncSession,
    title: str,
    description: str,
    difficulty: str,
    expected_language: str | None = None,
) -> Question:
    question = Question(
        title=title,
        description=description,
        difficulty=difficulty,
        expected_language=expected_language,
    )
    session.add(question)
    await session.commit()
    await session.refresh(question)
    return question


async def create_submission(
    session: AsyncSession,
    interview_session_id: UUID,
    question_id: UUID,
    language: str,
    source_code: str,
    stdin: str = "",
    commit: bool = True,
    status: str = "pending",
) -> Submission:
    latest_created_at = await session.scalar(
        select(func.max(Submission.created_at)).where(
            Submission.interview_session_id == interview_session_id,
            Submission.question_id == question_id,
        )
    )
    created_at = datetime.now(timezone.utc)
    if latest_created_at is not None:
        if latest_created_at.tzinfo is None:
            latest_created_at = latest_created_at.replace(tzinfo=timezone.utc)
    if latest_created_at is not None and created_at <= latest_created_at:
        from datetime import timedelta

        created_at = latest_created_at + timedelta(microseconds=1)
    submission = Submission(
        interview_session_id=interview_session_id,
        question_id=question_id,
        language=language,
        source_code=source_code,
        stdin=stdin,
        status=status,
        created_at=created_at,
    )
    session.add(submission)
    if commit:
        await session.commit()
        await session.refresh(submission)
    else:
        await session.flush()
    return submission


async def create_execution_job(
    session: AsyncSession, submission: Submission
) -> ExecutionJob:
    job = ExecutionJob(
        submission_id=submission.id,
        status="queued",
        attempt_count=0,
        created_at=submission.created_at,
    )
    session.add(job)
    try:
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        raise DatabasePersistenceError from exc
    await session.refresh(job)
    return job


async def get_submission_with_job(
    session: AsyncSession, submission_id: UUID
) -> tuple[Submission, ExecutionJob]:
    result = await session.execute(
        select(Submission, ExecutionJob)
        .join(ExecutionJob, ExecutionJob.submission_id == Submission.id)
        .where(Submission.id == submission_id)
    )
    row = result.first()
    if row is None:
        raise SubmissionNotFoundError
    return row


async def claim_next_execution_job(
    session: AsyncSession,
) -> tuple[Submission, ExecutionJob] | None:
    """Claim one queued job using a row lock where supported."""
    job = await session.scalar(
        select(ExecutionJob)
        .where(ExecutionJob.status == "queued")
        .order_by(ExecutionJob.created_at.asc(), ExecutionJob.id.asc())
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    submission = await session.get(Submission, job.submission_id)
    if submission is None:
        job.status = "failed"
        job.error_message = "Submission record is unavailable."
        job.completed_at = datetime.now(timezone.utc)
        await session.commit()
        return None
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.attempt_count += 1
    submission.status = "running"
    await session.commit()
    await session.refresh(job)
    await session.refresh(submission)
    return submission, job


async def store_execution_result(
    session: AsyncSession, submission: Submission, result: ExecutionResult
) -> Submission:
    submission.status = result.status
    submission.stdout = result.stdout
    submission.stderr = result.stderr
    submission.exit_code = result.exit_code
    submission.execution_time_ms = result.execution_time_ms
    submission.timed_out = result.timed_out
    await session.commit()
    await session.refresh(submission)
    return submission
