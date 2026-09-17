"""Focused tests covering the JWT auth and authorization foundation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

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
from app.models import Base, Candidate


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
