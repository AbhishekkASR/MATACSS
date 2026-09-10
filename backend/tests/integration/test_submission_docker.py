"""Real Docker integration tests for the submission endpoint."""

import docker
import pytest
from docker.errors import DockerException
from fastapi.testclient import TestClient
from uuid import uuid4

from app.main import app
from app.core.database import async_session_factory
from app.services.execution_worker import process_next_execution_job
from app.services.sandbox_service import DockerSandboxService
from app.models import Submission
from uuid import UUID

pytestmark = pytest.mark.docker


@pytest.fixture(scope="module")
def client() -> TestClient:
    try:
        docker.from_env().ping()
    except DockerException as exc:
        pytest.skip(f"Docker is unavailable: {exc}")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def assessment(client: TestClient) -> dict:
    unique_id = uuid4()
    candidate = client.post(
        "/api/v1/candidates",
        json={
            "name": f"Docker Candidate {unique_id}",
            "email": f"docker-{unique_id}@example.com",
        },
    )
    assert candidate.status_code == 201
    candidate_id = candidate.json()["candidate_id"]
    interview = client.post(
        "/api/v1/interviews", json={"candidate_id": candidate_id}
    )
    assert interview.status_code == 201
    interview_id = interview.json()["interview_session_id"]
    question = client.post(
        "/api/v1/questions",
        json={
            "title": f"Docker question {unique_id}",
            "description": "Execute safely.",
            "difficulty": "easy",
            "expected_language": "python",
        },
    )
    assert question.status_code == 201
    question_id = question.json()["question_id"]
    assignment = client.post(
        f"/api/v1/interviews/{interview_id}/questions",
        json={"question_id": question_id, "sequence_number": 1},
    )
    assert assignment.status_code == 201
    yield {"interview_session_id": interview_id, "question_id": question_id}


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
    status = client.get(f"/api/v1/submissions/{result['submission_id']}/status")
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
        )
        assert test_case.status_code == 201

    submission = submit(
        client,
        assessment,
        "python",
        "print(input())",
    )
    evaluated = client.post(
        f"/api/v1/submissions/{submission['submission_id']}/evaluate"
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
