"""Real Docker integration tests for the submission endpoint."""

import docker
import pytest
from docker.errors import DockerException
from fastapi.testclient import TestClient
from sqlalchemy import select
from uuid import uuid4

from app.core.config import settings
from app.main import app
from app.core.database import async_session_factory
from app.models import Candidate, QuestionStatus, Submission, UserRole
from app.services.auth_service import create_user
from app.services.execution_worker import process_next_execution_job
from app.services.sandbox_service import DockerSandboxService
from tests.question_helpers import set_question_status
from uuid import UUID

pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def client() -> TestClient:
    original_jwt_secret = settings.jwt_secret
    if not original_jwt_secret:
        object.__setattr__(
            settings, "jwt_secret", "docker-integration-test-secret-32bytes"
        )
    try:
        try:
            docker.from_env().ping()
        except DockerException as exc:
            pytest.skip(f"Docker is unavailable: {exc}")
        with TestClient(app) as test_client:
            yield test_client
    finally:
        if not original_jwt_secret:
            object.__setattr__(settings, "jwt_secret", original_jwt_secret)


@pytest.fixture(scope="module")
def assessment(client: TestClient) -> dict:
    unique_id = uuid4()
    email = f"docker-{unique_id}@example.com"
    password = "docker-integration-password"
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "name": f"Docker Candidate {unique_id}",
            "email": email,
            "password": password,
        },
    )
    assert registration.status_code == 201
    candidate_login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert candidate_login.status_code == 200
    candidate_headers = {
        "Authorization": f"Bearer {candidate_login.json()['access_token']}"
    }

    async def find_candidate_id() -> str:
        async with async_session_factory() as session:
            candidate = await session.scalar(
                select(Candidate).where(Candidate.email == email)
            )
            assert candidate is not None
            return str(candidate.id)

    candidate_id = client.portal.call(find_candidate_id)
    interview = client.post(
        "/api/v1/interviews",
        json={"candidate_id": candidate_id},
        headers=candidate_headers,
    )
    assert interview.status_code == 201
    interview_id = interview.json()["interview_session_id"]

    admin_email = f"docker-admin-{unique_id}@example.com"
    admin_password = "docker-admin-integration-password"

    async def create_admin() -> None:
        async with async_session_factory() as session:
            await create_user(
                session, admin_email, admin_password, role=UserRole.ADMIN
            )

    client.portal.call(create_admin)
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": admin_email, "password": admin_password},
    )
    assert admin_login.status_code == 200
    admin_headers = {
        "Authorization": f"Bearer {admin_login.json()['access_token']}"
    }
    question = client.post(
        "/api/v1/questions",
        json={
            "title": f"Docker question {unique_id}",
            "description": "Execute safely.",
            "difficulty": "easy",
            "expected_language": "python",
        },
        headers=admin_headers,
    )
    assert question.status_code == 201
    question_id = question.json()["question_id"]
    set_question_status(client, [question_id], QuestionStatus.ACTIVE)
    assignment = client.post(
        f"/api/v1/interviews/{interview_id}/questions",
        json={"question_id": question_id, "sequence_number": 1},
        headers=admin_headers,
    )
    assert assignment.status_code == 201
    yield {
        "interview_session_id": interview_id,
        "question_id": question_id,
        "candidate_headers": candidate_headers,
        "admin_headers": admin_headers,
    }


def submit(
    client: TestClient, assessment: dict, language: str, source_code: str
) -> dict:
    response = client.post(
        "/api/v1/submissions",
        json={
            **assessment,
            "language": language,
            "source_code": source_code,
        },
        headers=assessment["candidate_headers"],
    )
    assert response.status_code == 200
    result = response.json()

    async def process() -> None:
        async with async_session_factory() as session:
            for _ in range(100):
                assert await process_next_execution_job(
                    session, DockerSandboxService()
                )
                submission = await session.get(
                    Submission, UUID(result["submission_id"])
                )
                if submission is not None and submission.status != "queued":
                    break

    client.portal.call(process)
    status = client.get(
        f"/api/v1/submissions/{result['submission_id']}/status",
        headers=assessment["candidate_headers"],
    )
    assert status.status_code == 200
    assert status.json()["job_status"] == "succeeded"
    return {
        **result,
        "status": status.json()["submission_status"],
        "stdout": status.json()["stdout"] or "",
        "stderr": status.json()["stderr"] or "",
        "timed_out": status.json()["timed_out"],
    }


def test_python_success(client: TestClient, assessment: dict) -> None:
    result = submit(client, assessment, "python", "print('hello')")
    assert result["status"] == "success"
    assert result["stdout"].strip() == "hello"


def test_python_evaluation_executes_multiple_cases_in_docker(
    client: TestClient, assessment: dict
) -> None:
    for stdin in ("first", "second"):
        test_case = client.post(
            f"/api/v1/questions/{assessment['question_id']}/test-cases",
            json={
                "stdin": stdin,
                "expected_stdout": f"{stdin}\n",
                "description": "Docker evaluation case",
            },
            headers=assessment["admin_headers"],
        )
        assert test_case.status_code == 201

    submission = submit(
        client,
        assessment,
        "python",
        "print(input())",
    )
    evaluated = client.post(
        f"/api/v1/submissions/{submission['submission_id']}/evaluate",
        headers=assessment["candidate_headers"],
    )
    assert evaluated.status_code == 200
    body = evaluated.json()
    assert body["status"] == "scored"
    assert body["total_test_cases"] == 2
    assert body["passed_test_cases"] == 2
    assert body["score"] == 100


def test_python_runtime_error(client: TestClient, assessment: dict) -> None:
    result = submit(client, assessment, "python", "raise RuntimeError('boom')")
    assert result["status"] == "runtime_error"


def test_python_timeout(client: TestClient, assessment: dict) -> None:
    result = submit(client, assessment, "python", "while True: pass")
    assert result["status"] == "timeout"
    assert result["timed_out"] is True


def test_python_output_limit(client: TestClient, assessment: dict) -> None:
    result = submit(client, assessment, "python", "print('x' * 100000)")
    assert result["status"] == "output_limit_exceeded"


def test_cpp_compilation_error(client: TestClient, assessment: dict) -> None:
    result = submit(client, assessment, "cpp", "int main() {")
    assert result["status"] == "compilation_error"


def test_cpp_success(client: TestClient, assessment: dict) -> None:
    result = submit(
        client, assessment, "cpp", '#include <iostream>\nint main(){std::cout<<"ok";}'
    )
    assert result["status"] == "success"


def test_java_compilation_error(client: TestClient, assessment: dict) -> None:
    result = submit(client, assessment, "java", "public class Main {")
    assert result["status"] == "compilation_error"


def test_java_success(client: TestClient, assessment: dict) -> None:
    source = (
        'public class Main { public static void main(String[] args) '
        '{ System.out.print("ok"); } }'
    )
    result = submit(client, assessment, "java", source)
    assert result["status"] == "success"
