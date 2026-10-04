"""Focused tests covering the JWT auth and authorization foundation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.api.routes.auth as auth_routes
import app.api.routes.domain as domain_routes
import app.api.routes.submissions as submissions_routes
import app.core.config as config
import app.core.database as database_module
import app.core.security as security
import app.main as main_module
from app.core.database import get_db_session
from app.models import Base, Candidate, Question, QuestionStatus, QuestionTestCase, UserRole
from app.services.auth_service import create_user


@pytest.fixture
def configured_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import importlib

    monkeypatch.setenv("MATACSS_JWT_SECRET", "test-secret")
    monkeypatch.setenv("MATACSS_JWT_EXPIRE_MINUTES", "60")

    importlib.reload(config)
    importlib.reload(security)
    importlib.reload(auth_routes)
    importlib.reload(domain_routes)
    importlib.reload(submissions_routes)
    importlib.reload(main_module)

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
    original_session_factory = database_module.async_session_factory
    database_module.async_session_factory = factory

    async def override() -> AsyncGenerator:
        async with factory() as session:
            yield session

    main_module.app.dependency_overrides[get_db_session] = override
    try:
        with TestClient(main_module.app) as client:
            yield client
    finally:
        main_module.app.dependency_overrides.pop(get_db_session, None)
        database_module.async_session_factory = original_session_factory
        monkeypatch.delenv("MATACSS_JWT_SECRET", raising=False)
        monkeypatch.delenv("MATACSS_JWT_EXPIRE_MINUTES", raising=False)
        importlib.reload(config)
        importlib.reload(security)
        importlib.reload(auth_routes)
        importlib.reload(domain_routes)
        importlib.reload(submissions_routes)
        importlib.reload(main_module)


def test_login_and_me(configured_client: TestClient) -> None:
    register = configured_client.post(
        "/api/v1/auth/register",
        json={
            "name": "Alice Candidate",
            "email": "alice@example.com",
            "password": "secure-password",
        },
    )
    assert register.status_code == 201
    assert register.json()["email"] == "alice@example.com"
    assert register.json()["role"] == "candidate"

    token = configured_client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "secure-password"},
    )
    assert token.status_code == 200
    body = token.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    me = configured_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


def test_registration_rejects_client_selected_privileged_role(
    configured_client: TestClient,
) -> None:
    response = configured_client.post(
        "/api/v1/auth/register",
        json={
            "name": "Attempted Admin",
            "email": "attempted-admin@example.com",
            "password": "secure-password",
            "role": "admin",
        },
    )
    assert response.status_code == 422


def test_invalid_token_is_rejected(configured_client: TestClient) -> None:
    response = configured_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )
    assert response.status_code == 401


def test_candidate_cannot_access_other_candidate_interview(
    configured_client: TestClient,
) -> None:
    register_a = configured_client.post(
        "/api/v1/auth/register",
        json={
            "name": "Candidate A",
            "email": "candidate-a@example.com",
            "password": "strong-pass1",
        },
    )
    register_b = configured_client.post(
        "/api/v1/auth/register",
        json={
            "name": "Candidate B",
            "email": "candidate-b@example.com",
            "password": "strong-pass2",
        },
    )
    assert register_a.status_code == 201
    assert register_b.status_code == 201

    async def get_candidate_id(email: str) -> str:
        async with database_module.async_session_factory() as session:
            candidate = await session.scalar(
                select(Candidate).where(Candidate.email == email)
            )
            assert candidate is not None
            return str(candidate.id)

    candidate_a_id = asyncio.run(get_candidate_id("candidate-a@example.com"))

    token_a = configured_client.post(
        "/api/v1/auth/login",
        json={"email": "candidate-a@example.com", "password": "strong-pass1"},
    )
    token_b = configured_client.post(
        "/api/v1/auth/login",
        json={"email": "candidate-b@example.com", "password": "strong-pass2"},
    )
    assert token_a.status_code == 200
    assert token_b.status_code == 200

    interview = configured_client.post(
        "/api/v1/interviews",
        json={"candidate_id": candidate_a_id},
        headers={"Authorization": f"Bearer {token_a.json()['access_token']}"},
    )
    assert interview.status_code == 201
    interview_id = interview.json()["interview_session_id"]

    forbidden = configured_client.get(
        f"/api/v1/interviews/{interview_id}",
        headers={"Authorization": f"Bearer {token_b.json()['access_token']}"},
    )
    assert forbidden.status_code == 403

    forbidden_completion = configured_client.post(
        f"/api/v1/interviews/{interview_id}/complete",
        headers={"Authorization": f"Bearer {token_b.json()['access_token']}"},
    )
    assert forbidden_completion.status_code == 403

    completed = configured_client.post(
        f"/api/v1/interviews/{interview_id}/complete",
        headers={"Authorization": f"Bearer {token_a.json()['access_token']}"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    repeated_completion = configured_client.post(
        f"/api/v1/interviews/{interview_id}/complete",
        headers={"Authorization": f"Bearer {token_a.json()['access_token']}"},
    )
    assert repeated_completion.status_code == 409


def test_submission_attempt_routes_enforce_auth_and_interview_ownership(
    configured_client: TestClient,
) -> None:
    register_a = configured_client.post(
        "/api/v1/auth/register",
        json={
            "name": "Owner Candidate",
            "email": "owner@example.com",
            "password": "strong-pass1",
        },
    )
    register_b = configured_client.post(
        "/api/v1/auth/register",
        json={
            "name": "Other Candidate",
            "email": "other@example.com",
            "password": "strong-pass2",
        },
    )
    assert register_a.status_code == register_b.status_code == 201

    async def create_admin() -> None:
        async with database_module.async_session_factory() as session:
            await create_user(
                session,
                "admin@example.com",
                "secure-password",
                role=UserRole.ADMIN,
            )

    asyncio.run(create_admin())
    tokens = {}
    for email, password in (
        ("owner@example.com", "strong-pass1"),
        ("other@example.com", "strong-pass2"),
        ("admin@example.com", "secure-password"),
    ):
        token = configured_client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
        assert token.status_code == 200
        tokens[email] = {"Authorization": f"Bearer {token.json()['access_token']}"}

    async def get_candidate_id() -> str:
        async with database_module.async_session_factory() as session:
            candidate = await session.scalar(
                select(Candidate).where(Candidate.email == "owner@example.com")
            )
            assert candidate is not None
            return str(candidate.id)

    interview = configured_client.post(
        "/api/v1/interviews",
        json={"candidate_id": asyncio.run(get_candidate_id())},
        headers=tokens["owner@example.com"],
    )
    assert interview.status_code == 201
    interview_id = interview.json()["interview_session_id"]

    question_response = configured_client.post(
        "/api/v1/questions",
        json={
            "title": "Private submission question",
            "description": "Question description",
            "difficulty": "easy",
            "expected_language": "python",
        },
        headers=tokens["admin@example.com"],
    )
    assert question_response.status_code == 201
    question_id = question_response.json()["question_id"]

    async def activate_question() -> None:
        async with database_module.async_session_factory() as session:
            question = await session.get(Question, UUID(question_id))
            assert question is not None
            question.status = QuestionStatus.ACTIVE
            await session.commit()

    asyncio.run(activate_question())
    assignment = configured_client.post(
        f"/api/v1/interviews/{interview_id}/questions",
        json={"question_id": question_id, "sequence_number": 1},
        headers=tokens["admin@example.com"],
    )
    assert assignment.status_code == 201

    submission = configured_client.post(
        "/api/v1/submissions",
        json={
            "interview_session_id": interview_id,
            "question_id": question_id,
            "language": "python",
            "source_code": "print('private source')",
        },
        headers=tokens["owner@example.com"],
    )
    assert submission.status_code == 200

    history_url = (
        f"/api/v1/interviews/{interview_id}/questions/{question_id}/submissions"
    )
    latest_url = (
        f"/api/v1/interviews/{interview_id}/questions/{question_id}/latest-submission"
    )
    for url in (history_url, latest_url):
        assert configured_client.get(url).status_code == 401
        assert (
            configured_client.get(url, headers=tokens["other@example.com"]).status_code
            == 403
        )

    history = configured_client.get(
        history_url, headers=tokens["owner@example.com"]
    )
    latest = configured_client.get(latest_url, headers=tokens["owner@example.com"])
    assert history.status_code == latest.status_code == 200
    assert history.json()[0]["source_code"] == "print('private source')"
    assert latest.json()["source_code"] == "print('private source')"
    assert configured_client.get(
        history_url, headers=tokens["admin@example.com"]
    ).status_code == 200


def test_test_case_listing_hides_private_cases_from_candidates(
    configured_client: TestClient,
) -> None:
    async def create_admin() -> None:
        async with database_module.async_session_factory() as session:
            await create_user(
                session,
                "case-admin@example.com",
                "secure-password",
                role=UserRole.ADMIN,
            )

    asyncio.run(create_admin())
    admin_login = configured_client.post(
        "/api/v1/auth/login",
        json={"email": "case-admin@example.com", "password": "secure-password"},
    )
    admin_headers = {
        "Authorization": f"Bearer {admin_login.json()['access_token']}"
    }
    question = configured_client.post(
        "/api/v1/questions",
        json={
            "title": "Case visibility question",
            "description": "Question description",
            "difficulty": "easy",
            "expected_language": "python",
        },
        headers=admin_headers,
    )
    assert question.status_code == 201
    question_id = question.json()["question_id"]

    hidden_case = configured_client.post(
        f"/api/v1/questions/{question_id}/test-cases",
        json={"stdin": "hidden input", "expected_stdout": "hidden output"},
        headers=admin_headers,
    )
    assert hidden_case.status_code == 201

    async def add_sample_case() -> None:
        async with database_module.async_session_factory() as session:
            session.add(
                QuestionTestCase(
                    question_id=UUID(question_id),
                    stdin="sample input",
                    expected_stdout="sample output",
                    is_sample=True,
                )
            )
            await session.commit()

    asyncio.run(add_sample_case())
    candidate = configured_client.post(
        "/api/v1/auth/register",
        json={
            "name": "Case Candidate",
            "email": "case-candidate@example.com",
            "password": "strong-pass3",
        },
    )
    assert candidate.status_code == 201
    candidate_login = configured_client.post(
        "/api/v1/auth/login",
        json={"email": "case-candidate@example.com", "password": "strong-pass3"},
    )
    candidate_headers = {
        "Authorization": f"Bearer {candidate_login.json()['access_token']}"
    }

    candidate_cases = configured_client.get(
        f"/api/v1/questions/{question_id}/test-cases",
        headers=candidate_headers,
    )
    admin_cases = configured_client.get(
        f"/api/v1/questions/{question_id}/test-cases",
        headers=admin_headers,
    )
    assert candidate_cases.status_code == admin_cases.status_code == 200
    assert [(item["stdin"], item["expected_stdout"]) for item in candidate_cases.json()] == [
        ("sample input", "sample output")
    ]
    assert len(admin_cases.json()) == 2
