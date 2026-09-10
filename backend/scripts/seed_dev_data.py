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
from app.models.question import Question
from app.models.question_test_case import QuestionTestCase


DEVELOPMENT_CANDIDATE_NAME = "MATACSS Development Candidate"
DEVELOPMENT_CANDIDATE_EMAIL = "matacss-dev@example.com"
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
        ("", "handles empty input"),
    ),
}


async def seed_development_data() -> tuple[Candidate, InterviewSession, Question]:
    """Create or reuse the development candidate, active session, and question."""
    async with async_session_factory() as session:
        async with session.begin():
            candidate = await session.scalar(
                select(Candidate).where(
                    Candidate.email == DEVELOPMENT_CANDIDATE_EMAIL
                )
            )
            if candidate is None:
                candidate = Candidate(
                    name=DEVELOPMENT_CANDIDATE_NAME,
                    email=DEVELOPMENT_CANDIDATE_EMAIL,
                )
                session.add(candidate)
                await session.flush()

            interview_session = await session.scalar(
                select(InterviewSession)
                .where(
                    InterviewSession.candidate_id == candidate.id,
                    InterviewSession.status == "active",
                )
                .order_by(InterviewSession.created_at.asc())
            )
            if interview_session is None:
                interview_session = InterviewSession(
                    candidate_id=candidate.id,
                    status="active",
                    started_at=datetime.now(timezone.utc),
                )
                session.add(interview_session)
                await session.flush()

            seeded_questions: list[Question] = []
            for title, description, difficulty, language in DEVELOPMENT_QUESTIONS:
                question = await session.scalar(
                    select(Question).where(Question.title == title)
                )
                if question is None:
                    question = Question(
                        title=title,
                        description=description,
                        difficulty=difficulty,
                        expected_language=language,
                    )
                    session.add(question)
                    await session.flush()
                seeded_questions.append(question)
                for stdin, description in DEVELOPMENT_TEST_CASES[title]:
                    expected_stdout = (
                        stdin
                        if title == "MATACSS Hello World"
                        else (
                            str(sum(int(value) for value in stdin.splitlines()))
                            if title == "MATACSS Sum Values"
                            else stdin[::-1]
                        )
                    )
                    existing_case = await session.scalar(
                        select(QuestionTestCase).where(
                            QuestionTestCase.question_id == question.id,
                            QuestionTestCase.stdin == stdin,
                            QuestionTestCase.expected_stdout == expected_stdout,
                        )
                    )
                    if existing_case is None:
                        session.add(
                            QuestionTestCase(
                                question_id=question.id,
                                stdin=stdin,
                                expected_stdout=expected_stdout,
                                description=description,
                            )
                        )

            for sequence_number, question in enumerate(seeded_questions, start=1):
                assignment = await session.scalar(
                    select(InterviewQuestion).where(
                        InterviewQuestion.interview_session_id == interview_session.id,
                        InterviewQuestion.question_id == question.id,
                    )
                )
                if assignment is None:
                    session.add(
                        InterviewQuestion(
                            interview_session_id=interview_session.id,
                            question_id=question.id,
                            sequence_number=sequence_number,
                        )
                    )

        return candidate, interview_session, seeded_questions[0]


async def main() -> None:
    """Seed development data and print IDs for frontend configuration."""
    try:
        candidate, interview_session, question = await seed_development_data()
    finally:
        await engine.dispose()

    print("Development data ready.")
    print()
    print("Candidate:")
    print(candidate.id)
    print()
    print("Interview Session:")
    print(interview_session.id)
    print()
    print("Question:")
    print(question.id)


if __name__ == "__main__":
    asyncio.run(main())
