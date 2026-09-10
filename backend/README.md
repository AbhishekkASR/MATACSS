# MATACSS Backend

This directory contains the FastAPI backend foundation and isolated Docker
sandbox service for MATACSS.

## Requirements

- Python 3.11 or newer

## Create and activate the virtual environment

From this directory:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution for the current user, run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then activate the environment again.

## Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Docker prerequisite

Install and start Docker Desktop (or a Docker Engine) before running sandbox
integration tests. Verify that the daemon is available:

```powershell
docker version
```

The sandbox supports `python`, `cpp`, and `java` using these images:

- `python:3.12-alpine`
- `gcc:14-bookworm`
- `eclipse-temurin:21-jdk`

## Run the development server

```powershell
python -m uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`.

Check the health endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

## Run tests

```powershell
python -m pytest
```

Normal tests use mocked Docker SDK objects and do not execute candidate code.
Run the real Docker integration tests explicitly:

```powershell
python -m pytest tests/integration/test_sandbox_docker.py -m docker
```

If Docker is unavailable, those integration tests are skipped.

## Local PostgreSQL development database

Docker Compose provides the local PostgreSQL development database. The
Compose configuration binds PostgreSQL to `localhost:5432`, uses the database
`matacss` and user `matacss_user`, and persists data in the named volume
`matacss_postgres_data`.

Create `backend/.env` from `.env.example` and set a local development password.
That file is ignored and must not be committed. Set `DATABASE_URL` to use the
same password when running backend commands from PowerShell.

Start PostgreSQL from `backend/`:

```powershell
docker compose up -d postgres
```

Inspect status and health:

```powershell
docker compose ps
docker compose logs postgres
```

Stop the service without deleting its data:

```powershell
docker compose stop postgres
```

Install and start PostgreSQL for database integration work. Configure the
async SQLAlchemy connection without committing credentials:

```powershell
$env:DATABASE_URL = "postgresql+asyncpg://matacss_user:change_me@localhost:5432/matacss"
```

Create the `matacss` database using your PostgreSQL administration tool, then
apply migrations:

```powershell
python -m alembic upgrade head
```

Roll back the latest migration:

```powershell
python -m alembic downgrade -1
```

The normal test suite uses an isolated in-memory SQLite database for ORM
behavior and does not claim PostgreSQL compatibility. Run PostgreSQL checks
explicitly when a real server is available:

```powershell
python -m pytest tests/integration/test_postgres_database.py -m postgres
```

The submission API uses the configured PostgreSQL database for persistent
submissions, execution jobs, evaluations, and assessment results.

## Candidate, interview, and question APIs

Create a candidate:

```http
POST /api/v1/candidates
```

```json
{"name": "Ada Lovelace", "email": "ada@example.com"}
```

```json
{
  "candidate_id": "uuid",
  "name": "Ada Lovelace",
  "email": "ada@example.com",
  "created_at": "2026-09-10T00:00:00Z"
}
```

Create an interview for an existing candidate:

```http
POST /api/v1/interviews
```

```json
{"candidate_id": "candidate-uuid"}
```

```json
{
  "interview_session_id": "uuid",
  "candidate_id": "candidate-uuid",
  "status": "active",
  "started_at": "2026-09-10T00:00:00Z",
  "created_at": "2026-09-10T00:00:00Z"
}
```

Create a question:

```http
POST /api/v1/questions
```

```json
{
  "title": "Two sum",
  "description": "Find two values.",
  "difficulty": "easy",
  "expected_language": "python"
}
```

The supported difficulties are `easy`, `medium`, and `hard`; supported
languages are `python`, `cpp`, and `java`.

## Code submission API

Submit source code for asynchronous execution in Docker:

```http
POST /api/v1/submissions
Content-Type: application/json
```

```json
{
  "interview_session_id": "interview-session-uuid",
  "question_id": "question-uuid",
  "language": "python",
  "source_code": "print('hello')",
  "stdin": ""
}
```

Queued response:

```json
{
  "submission_id": "b3b7c4df-7e80-4f18-ae4b-8a2ffb6e6f8f",
  "job_id": "job-uuid",
  "job_status": "queued",
  "status": "queued",
  "message": "Submission queued for execution.",
  "stdout": "",
  "stderr": "",
  "exit_code": 0,
  "execution_time_ms": null,
  "timed_out": false
}
```

Compilation-error response:

```json
{
  "submission_id": "uuid",
  "interview_session_id": "interview-session-uuid",
  "question_id": "question-uuid",
  "status": "compilation_error",
  "message": "Submission failed to compile.",
  "stdout": "",
  "stderr": "compiler diagnostics",
  "exit_code": 1,
  "execution_time_ms": 35.1,
  "timed_out": false
}
```

Runtime-error response:

```json
{
  "submission_id": "uuid",
  "interview_session_id": "interview-session-uuid",
  "question_id": "question-uuid",
  "status": "runtime_error",
  "message": "Submission terminated with a runtime error.",
  "stdout": "",
  "stderr": "runtime diagnostics",
  "exit_code": 1,
  "execution_time_ms": 12.4,
  "timed_out": false
}
```

Timeout response:

```json
{
  "submission_id": "uuid",
  "interview_session_id": "interview-session-uuid",
  "question_id": "question-uuid",
  "status": "timeout",
  "message": "Submission exceeded the execution time limit.",
  "stdout": "",
  "stderr": "execution timed out",
  "exit_code": null,
  "execution_time_ms": 5000.0,
  "timed_out": true
}
```

Supported languages are `python`, `cpp`, and `java`. Compilation, runtime,
timeout, output-limit, and sandbox failures are reported in the response status;
only infrastructure-level `sandbox_error` responses use HTTP 500.

Poll `GET /api/v1/submissions/{submission_id}/status` until the job reaches a
terminal state. The local worker can process queued jobs with:

```powershell
python scripts/run_worker.py
```

## Sandbox controls

Each execution uses a new container with network access disabled, no host
mounts or Docker socket, a non-root numeric user, a read-only root filesystem,
capabilities dropped, `no-new-privileges`, CPU/memory/PID limits, a five-second
timeout, bounded output, and guaranteed cleanup. Candidate code is never
executed directly on the host.

The current limits are:

- CPU: `0.5` CPU
- Memory: `128m`
- Processes: `64`
- Timeout: `5` seconds
- Captured stdout/stderr: `65536` bytes each
