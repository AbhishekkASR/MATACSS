"""Helpers for setting explicit Question Bank lifecycle states in API tests."""

import asyncio
from collections.abc import Iterable
from uuid import UUID

from fastapi.testclient import TestClient

from app.core.database import async_session_factory, get_db_session
from app.models.question import Question, QuestionStatus


def set_question_status(
    client: TestClient, question_ids: Iterable[UUID | str], status: QuestionStatus
) -> None:
    ids = [UUID(str(question_id)) for question_id in question_ids]
    override = client.app.dependency_overrides.get(get_db_session)

    async def update_status() -> None:
        if override is None:
            async with async_session_factory() as session:
                await _update_questions(session, ids, status)
            return

        generator = override()
        session = await anext(generator)
        try:
            await _update_questions(session, ids, status)
        finally:
            await generator.aclose()

    portal = client.portal
    if portal is None:
        asyncio.run(update_status())
    else:
        portal.call(update_status)


async def _update_questions(session, question_ids: list[UUID], status: QuestionStatus) -> None:
    for question_id in question_ids:
        question = await session.get(Question, question_id)
        if question is None:
            raise AssertionError("Test question was not found")
        question.status = status
    await session.commit()
