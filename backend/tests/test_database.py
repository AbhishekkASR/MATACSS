"""SQLite-backed ORM tests; PostgreSQL behavior is covered separately."""

import asyncio
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, Candidate, InterviewSession, Question, Submission
from app.schemas.execution import ExecutionResult
from app.services.database_service import (
    create_candidate,
    create_interview_session,
    create_question,
    create_submission,
    store_execution_result,
)


def run(coro):
    return asyncio.run(coro)


def test_model_metadata_loads() -> None:
    assert {
        "candidates",
        "interview_sessions",
        "questions",
        "submissions",
    }.issubset(Base.metadata.tables)


def test_database_entities_and_execution_result_persist() -> None:
    async def scenario() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine.sync_engine, "connect")
        def enable_foreign_keys(dbapi_connection, _):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            candidate = await create_candidate(session, "Ada Lovelace", "ada@example.com")
            interview = await create_interview_session(session, candidate.id)
            question = await create_question(
                session, "Two sum", "Find two values.", "easy", "python"
            )
            submission = await create_submission(
                session, interview.id, question.id, "python", "print(1)"
            )
            result = await store_execution_result(
                session,
                submission,
                ExecutionResult(
                    status="success",
                    stdout="1\n",
                    exit_code=0,
                    execution_time_ms=4.2,
                ),
            )

            assert isinstance(candidate.id, UUID)
            assert interview.candidate_id == candidate.id
            assert submission.interview_session_id == interview.id
            assert submission.question_id == question.id
            assert result.status == "success"
            assert result.stdout == "1\n"
            assert result.timed_out is False

            stored = (
                await session.execute(
                    select(Submission).where(Submission.id == submission.id)
                )
            ).scalar_one()
            assert stored.exit_code == 0
            assert stored.execution_time_ms == 4.2

        await engine.dispose()

    run(scenario())
