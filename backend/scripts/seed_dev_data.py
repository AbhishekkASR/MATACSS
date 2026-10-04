"""Create idempotent development records for manual MATACSS testing.

Run from the backend directory with:

    python scripts/seed_dev_data.py

This script uses the configured DATABASE_URL and is intentionally not imported
or executed by the FastAPI application.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

# Make ``python scripts/seed_dev_data.py`` work when launched from backend/.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import async_session_factory, engine
from app.models.candidate import Candidate
from app.models.interview import InterviewSession
from app.models.interview_question import InterviewQuestion
from app.models.question import Question, QuestionStatus
from app.models.question_llm_lineage import QuestionLlmLineage
from app.models.question_test_case import QuestionTestCase
from app.models.user import User
from app.question_bank.engine import (
    TrustedValidationRequest,
    transition_question_status,
    validate_draft,
)


DEVELOPMENT_CANDIDATE_NAME = "MATACSS Development Candidate"
DEVELOPMENT_CANDIDATE_EMAIL = "matacss-dev@example.com"
DEVELOPMENT_ADMIN_EMAIL = "matacss-admin@example.com"

DEVELOPMENT_QUESTIONS = (
    (
        "MATACSS Hello World",
        "Read a line from standard input and print it unchanged.",
        "easy",
        "python",
    ),
    (
        "MATACSS Sum Values",
        "Read two integers and print their sum.",
        "easy",
        "python",
    ),
    (
        "MATACSS Reverse Text",
        "Read a line and print it in reverse.",
        "easy",
        "python",
    ),
)

DEVELOPMENT_TEST_CASES = {
    "MATACSS Hello World": (
        ("MATACSS", "prints the provided line"),
        ("Hello MATACSS", "handles a second line"),
    ),
    "MATACSS Sum Values": (
        ("2\n3", "adds positive integers"),
        ("-4\n9", "handles negative values"),
    ),
    "MATACSS Reverse Text": (
        ("MATACSS", "reverses ordinary text"),
        ("hello", "reverses a simple word"),
    ),
}


async def _ensure_admin():
    """Ensure a lifecycle admin exists."""
    async with async_session_factory() as session:
        admin = await session.scalar(
            select(User).where(User.email == DEVELOPMENT_ADMIN_EMAIL)
        )
        if admin is None:
            admin = User(
                email=DEVELOPMENT_ADMIN_EMAIL,
                password_hash="unused",
                role="admin",
                active=True,
            )
            session.add(admin)
            await session.commit()
        return admin.id


async def _ensure_candidate():
    """Ensure the development candidate exists."""
    async with async_session_factory() as session:
        candidate = await session.scalar(
            select(Candidate).where(Candidate.email == DEVELOPMENT_CANDIDATE_EMAIL)
        )
        if candidate is None:
            candidate = Candidate(
                name=DEVELOPMENT_CANDIDATE_NAME,
                email=DEVELOPMENT_CANDIDATE_EMAIL,
            )
            session.add(candidate)
            await session.commit()
        return candidate.id


async def _ensure_interview_session(candidate_id):
    """Ensure an active interview session exists for the candidate."""
    async with async_session_factory() as session:
        interview = await session.scalar(
            select(InterviewSession).where(
                InterviewSession.candidate_id == candidate_id,
                InterviewSession.status == "active",
            )
        )
        if interview is None:
            interview = InterviewSession(
                candidate_id=candidate_id,
                status="active",
                started_at=datetime.now(timezone.utc),
            )
            session.add(interview)
            await session.commit()
        return interview.id


async def _create_or_skip_question(title, description, difficulty, language):
    """Create a question with test cases and lineage if it doesn't exist."""
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(Question).where(Question.title == title)
        )
        if existing is not None:
            print(f"  Question '{title}' already exists (skipping creation)")
            return existing.id

        print(f"  Creating question '{title}'...")
        question = Question(
            title=title,
            description=description,
            difficulty=difficulty,
            expected_language=language,
            status=QuestionStatus.DRAFT,
        )
        session.add(question)
        await session.flush()

        # Add test cases
        for stdin, desc_text in DEVELOPMENT_TEST_CASES[title]:
            expected_stdout = (
                stdin
                if title == "MATACSS Hello World"
                else (
                    str(sum(int(value) for value in stdin.splitlines()))
                    if title == "MATACSS Sum Values"
                    else stdin[::-1]
                )
            )
            session.add(
                QuestionTestCase(
                    question_id=question.id,
                    stdin=stdin,
                    expected_stdout=expected_stdout,
                    description=desc_text,
                )
            )

        # Add LLM lineage (required for lifecycle transitions)
        session.add(
            QuestionLlmLineage(
                question_id=question.id,
                origin="curated",
                model=None,
                generation_timestamp=None,
                parent_question_id=None,
                generation_metadata={},
            )
        )
        print(f"    Added {len(DEVELOPMENT_TEST_CASES[title])} test cases and lineage")
        await session.commit()
        return question.id


async def _advance_to_active(question_id, admin_id):
    """Transition question: draft → validated → approved → active."""
    # Draft → Validated
    print(f"  Validating question {question_id}...")
    async with async_session_factory() as session:
        question = await session.get(Question, question_id)
        print(f"    Current status: {question.status}")

        # Verify lineage exists
        lineage = await session.scalar(
            select(QuestionLlmLineage).where(
                QuestionLlmLineage.question_id == question_id
            )
        )
        print(f"    Lineage present: {lineage is not None}")

        if question.status != QuestionStatus.DRAFT:
            print(f"    Not in DRAFT status, skipping")
            return

        await validate_draft(
            session,
            question,
            TrustedValidationRequest(
                trusted_reference_verified=True,
                review_notes="Development seed validation.",
            ),
            admin_id,
        )
        print(f"    ✓ Validated")

    # Validated → Approved
    print(f"  Approving question {question_id}...")
    async with async_session_factory() as session:
        question = await session.get(Question, question_id)
        await transition_question_status(
            session,
            question,
            QuestionStatus.VALIDATED,
            QuestionStatus.APPROVED,
            admin_id,
        )
        print(f"    ✓ Approved")

    # Approved → Active
    print(f"  Activating question {question_id}...")
    async with async_session_factory() as session:
        question = await session.get(Question, question_id)
        await transition_question_status(
            session,
            question,
            QuestionStatus.APPROVED,
            QuestionStatus.ACTIVE,
            admin_id,
        )
        print(f"    ✓ Active")


async def _assign_question_to_session(session_id, question_id, sequence):
    """Assign a question to an interview session."""
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(InterviewQuestion).where(
                InterviewQuestion.interview_session_id == session_id,
                InterviewQuestion.question_id == question_id,
            )
        )
        if existing is None:
            session.add(
                InterviewQuestion(
                    interview_session_id=session_id,
                    question_id=question_id,
                    sequence_number=sequence,
                )
            )
            await session.commit()


async def seed_development_data():
    """Seed dev data: candidate, interview, and active questions."""
    print("Ensuring admin user...")
    admin_id = await _ensure_admin()
    print(f"  ✓ Admin: {admin_id}")

    print("Ensuring candidate...")
    candidate_id = await _ensure_candidate()
    print(f"  ✓ Candidate: {candidate_id}")

    print("Ensuring interview session...")
    interview_id = await _ensure_interview_session(candidate_id)
    print(f"  ✓ Interview: {interview_id}")

    print("Creating questions...")
    question_ids = []
    for seq, (title, desc, difficulty, language) in enumerate(
        DEVELOPMENT_QUESTIONS, start=1
    ):
        qid = await _create_or_skip_question(title, desc, difficulty, language)
        question_ids.append(qid)
        await _advance_to_active(qid, admin_id)
        await _assign_question_to_session(interview_id, qid, seq)

    return candidate_id, interview_id, question_ids[0]


async def main() -> None:
    """Seed and print IDs."""
    try:
        candidate_id, interview_id, question_id = await seed_development_data()
    finally:
        await engine.dispose()

    print("\nDevelopment data ready.")
    print()
    print("Candidate:")
    print(candidate_id)
    print()
    print("Interview Session:")
    print(interview_id)
    print()
    print("Question:")
    print(question_id)


if __name__ == "__main__":
    asyncio.run(main())
