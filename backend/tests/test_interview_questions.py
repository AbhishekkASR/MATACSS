"""Tests for ordered interview question assignments."""

import asyncio
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_db_session
from app.main import app
from app.models import Base


@pytest.fixture
def client() -> TestClient:
    async def setup() -> async_sessionmaker:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    factory = asyncio.run(setup())

    async def override() -> AsyncGenerator:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db_session, None)


def assessment(client: TestClient) -> tuple[dict, list[dict]]:
    candidate = client.post(
        "/api/v1/candidates",
        json={"name": "Assignment Candidate", "email": f"{uuid4()}@example.com"},
    ).json()
    interview = client.post(
        "/api/v1/interviews", json={"candidate_id": candidate["candidate_id"]}
    ).json()
    questions = [
        client.post(
            "/api/v1/questions",
            json={
                "title": f"Assignment Question {index}",
                "description": "Description",
                "difficulty": "easy",
                "expected_language": "python",
            },
        ).json()
        for index in range(1, 4)
    ]
    return interview, questions


def test_assign_and_retrieve_questions_in_sequence_order(client: TestClient) -> None:
    interview, questions = assessment(client)
    for sequence_number, question in zip((2, 1, 3), questions):
        response = client.post(
            f"/api/v1/interviews/{interview['interview_session_id']}/questions",
            json={
                "question_id": question["question_id"],
                "sequence_number": sequence_number,
            },
        )
        assert response.status_code == 201

    response = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions"
    )
    assert response.status_code == 200
    assert [item["sequence_number"] for item in response.json()] == [1, 2, 3]
    assert [item["question_id"] for item in response.json()] == [
        questions[1]["question_id"],
        questions[0]["question_id"],
        questions[2]["question_id"],
    ]


def test_assignment_missing_entities_and_invalid_values(client: TestClient) -> None:
    interview, questions = assessment(client)
    path = f"/api/v1/interviews/{interview['interview_session_id']}/questions"
    assert client.post(
        path,
        json={"question_id": str(uuid4()), "sequence_number": 1},
    ).status_code == 404
    assert client.post(
        f"/api/v1/interviews/{uuid4()}/questions",
        json={"question_id": questions[0]["question_id"], "sequence_number": 1},
    ).status_code == 404
    assert client.post(
        path,
        json={"question_id": questions[0]["question_id"], "sequence_number": 0},
    ).status_code == 422
    assert client.post(
        f"/api/v1/interviews/not-a-uuid/questions",
        json={"question_id": questions[0]["question_id"], "sequence_number": 1},
    ).status_code == 422


def test_duplicate_question_and_sequence_return_409(client: TestClient) -> None:
    interview, questions = assessment(client)
    path = f"/api/v1/interviews/{interview['interview_session_id']}/questions"
    assert client.post(
        path,
        json={"question_id": questions[0]["question_id"], "sequence_number": 1},
    ).status_code == 201
    assert client.post(
        path,
        json={"question_id": questions[0]["question_id"], "sequence_number": 2},
    ).status_code == 409
    assert client.post(
        path,
        json={"question_id": questions[1]["question_id"], "sequence_number": 1},
    ).status_code == 409


def test_bulk_assignment_is_all_or_nothing(client: TestClient) -> None:
    interview, questions = assessment(client)
    path = f"/api/v1/interviews/{interview['interview_session_id']}/questions/bulk"
    response = client.post(
        path,
        json={
            "questions": [
                {"question_id": questions[0]["question_id"], "sequence_number": 1},
                {"question_id": questions[1]["question_id"], "sequence_number": 1},
            ]
        },
    )
    assert response.status_code == 422
    listed = client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions"
    )
    assert listed.json() == []

    response = client.post(
        path,
        json={
            "questions": [
                {"question_id": questions[0]["question_id"], "sequence_number": 1},
                {"question_id": questions[1]["question_id"], "sequence_number": 2},
            ]
        },
    )
    assert response.status_code == 201
    assert len(response.json()) == 2


def test_bulk_missing_question_rolls_back(client: TestClient) -> None:
    interview, questions = assessment(client)
    path = f"/api/v1/interviews/{interview['interview_session_id']}/questions/bulk"
    response = client.post(
        path,
        json={
            "questions": [
                {"question_id": questions[0]["question_id"], "sequence_number": 1},
                {"question_id": str(uuid4()), "sequence_number": 2},
            ]
        },
    )
    assert response.status_code == 404
    assert client.get(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions"
    ).json() == []


def test_assignment_requires_active_interview(client: TestClient) -> None:
    interview, questions = assessment(client)
    assert client.post(
        f"/api/v1/interviews/{interview['interview_session_id']}/complete"
    ).status_code == 200
    assert client.post(
        f"/api/v1/interviews/{interview['interview_session_id']}/questions",
        json={"question_id": questions[0]["question_id"], "sequence_number": 1},
    ).status_code == 409
