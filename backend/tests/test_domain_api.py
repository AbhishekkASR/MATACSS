"""API tests for candidate, interview, and question workflows."""

import asyncio
from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import get_db_session
from app.main import app
from app.models import Base


@pytest.fixture(scope="module")
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


def candidate(client: TestClient, email: str = "ada@example.com") -> dict:
    response = client.post(
        "/api/v1/candidates", json={"name": "Ada Lovelace", "email": email}
    )
    assert response.status_code == 201
    return response.json()


def test_candidate_created(client: TestClient) -> None:
    body = candidate(client)
    assert body["name"] == "Ada Lovelace"
    assert body["email"] == "ada@example.com"
    assert body["candidate_id"]
    assert body["created_at"]


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"name": " ", "email": "name@example.com"}, "name"),
        ({"name": "Name", "email": " "}, "email"),
        ({"name": "Name", "email": "invalid"}, "email"),
    ],
)
def test_candidate_validation(client: TestClient, payload: dict, field: str) -> None:
    response = client.post("/api/v1/candidates", json=payload)
    assert response.status_code == 422
    assert field in response.text


def test_duplicate_candidate_email_conflict(client: TestClient) -> None:
    candidate(client, "duplicate@example.com")
    response = client.post(
        "/api/v1/candidates",
        json={"name": "Other", "email": "duplicate@example.com"},
    )
    assert response.status_code == 409


def test_interview_created_for_candidate(client: TestClient) -> None:
    created = candidate(client, "interview@example.com")
    response = client.post(
        "/api/v1/interviews", json={"candidate_id": created["candidate_id"]}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["candidate_id"] == created["candidate_id"]
    assert body["status"] == "active"
    assert body["started_at"]


def test_interview_requires_existing_candidate(client: TestClient) -> None:
    response = client.post(
        "/api/v1/interviews",
        json={"candidate_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404


def test_question_created(client: TestClient) -> None:
    response = client.post(
        "/api/v1/questions",
        json={
            "title": "Two sum",
            "description": "Find two values.",
            "difficulty": "easy",
            "expected_language": "python",
        },
    )
    assert response.status_code == 201
    assert response.json()["title"] == "Two sum"


@pytest.mark.parametrize(
    "payload",
    [
        {"title": " ", "description": "desc", "difficulty": "easy", "expected_language": "python"},
        {"title": "title", "description": " ", "difficulty": "easy", "expected_language": "python"},
        {"title": "title", "description": "desc", "difficulty": "expert", "expected_language": "python"},
        {"title": "title", "description": "desc", "difficulty": "easy", "expected_language": "go"},
    ],
)
def test_question_validation(client: TestClient, payload: dict) -> None:
    assert client.post("/api/v1/questions", json=payload).status_code == 422


def test_health_still_works(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
