# MATACSS

MATACSS is a deterministic technical-assessment platform for running
programming questions inside isolated Docker sandboxes, tracking candidate
attempts, evaluating official test cases, and presenting assessment results.

The repository contains a working, security-conscious foundation for the
assessment workflow and multi-agent orchestration, while intentionally keeping
AI/agent behavior advisory and non-persistent.

Implemented in the current repository:

- FastAPI backend with SQLite for local development and PostgreSQL-ready configuration
- JWT bearer authentication with secure password hashing and role-based authorization
- Candidate/interviewer/admin user model and protected assessment routes
- Next.js frontend with Monaco editor and assessment workspace
- Interview lifecycle and interview-specific question assignment
- Per-question submission history and latest-attempt tracking
- Durable asynchronous execution jobs and a local worker
- Deterministic official evaluation and score calculation
- Assessment-level results aggregation
- Defense-in-depth Docker sandbox controls with adversarial integration tests
- LangGraph orchestration with deterministic Interviewer, Code Reviewer, Edge-Case Generator, and feedback aggregation foundations
- Bounded, advisory AI feedback that never overrides official evaluation results
- Centralized environment-driven production configuration with secure defaults and safe CORS handling
- Structured observability, worker hardening, and deployment/CI scaffolding

## Current status

This repository is a deterministic local-development and release-readiness
foundation for MATACSS. It includes secure authentication, safe orchestration
boundaries, and production configuration checks. Real LLM integration,
autonomous execution, automatic persistence of AI outputs, and automatic
verification of generated edge cases are not implemented.

## Architecture

```text
Next.js + Monaco
        |
        v
FastAPI
        |
        +--> PostgreSQL
        |      candidates, interviews, assignments, submissions,
        |      execution jobs, test cases, evaluations
        |
        +--> Durable execution job (queued)
                    |
                    v
             Local ExecutionWorker
                    |
                    v
             DockerSandboxService
                    |
                    v
             Submission status/output
                    |
                    v
             Explicit evaluation boundary
                    |
                    v
             Assessment results aggregation
```

### Submission lifecycle

1. `POST /api/v1/submissions` validates the active interview and assigned
   question.
2. The backend persists a queued `Submission` and one unique
   `ExecutionJob`, then returns immediately.
3. The local worker claims jobs in FIFO order using PostgreSQL row locking and
   `SKIP LOCKED` where supported.
4. Candidate code is executed only through `DockerSandboxService`.
5. The worker persists execution output and terminal status.
6. The frontend polls the typed submission-status endpoint until execution
   finishes.
7. Evaluation is explicit through
   `POST /api/v1/submissions/{submission_id}/evaluate`.

The HTTP submission request never executes Docker directly.

## Security controls

Every candidate execution uses a new short-lived Docker container with the
following implemented controls:

- Network disabled
- Non-root numeric user (`65532:65532`)
- Read-only root filesystem
- Writable/executable `/tmp` only, backed by a bounded tmpfs
- `nosuid` and `nodev` temporary filesystem flags
- Docker init process for child-process reaping
- No host bind mounts or Docker socket
- Explicit empty volume configuration
- `no-new-privileges`
- All Linux capabilities dropped
- Memory, CPU, and PID limits
- Five-second execution timeout
- Bounded stdout/stderr capture
- Fixed runtime commands and fixed source paths
- Separate safe stdin transfer
- Forced container cleanup after success and failure
- Sanitized Docker and worker error messages

These controls are defense-in-depth. The test suite demonstrates the behavior
of the configured Docker boundary; it is not a formal proof of immunity from
host-kernel, Docker-daemon, runtime-image, or virtualization vulnerabilities.

Supported runtime images:

- `python:3.12-alpine`
- `gcc:14-bookworm`
- `eclipse-temurin:21-jdk`

Supported languages:

- Python
- C++
- Java

## Repository layout

```text
backend/
  app/
    api/                 FastAPI routes
    models/              SQLAlchemy models
    schemas/             Pydantic request/response schemas
    services/            persistence, queue, worker, evaluation, sandbox
  alembic/               Database migrations
  scripts/
    seed_dev_data.py     Idempotent development seed
    run_worker.py        Process queued jobs and exit
  tests/
    integration/         PostgreSQL/Docker integration tests
frontend/
  app/                   Next.js assessment workspace
  components/            Editor, output, and results UI
  lib/api.ts             Typed API client
  types/                 Frontend API/domain types
```

## Requirements

- Python 3.11+
- Node.js 20+
- npm
- Docker Desktop or Docker Engine
- PostgreSQL 16 for the development database

## CI/CD and deployment

The repository includes a minimal GitHub Actions CI workflow in [.github/workflows/ci.yml](.github/workflows/ci.yml) that validates:

- backend dependency installation
- backend compile checks
- backend non-Docker test suite
- frontend dependency installation
- frontend lint and build checks
- backend/frontend Docker build validation

See [docs/deployment.md](docs/deployment.md) for the full deployment notes, environment variables, and local validation commands.

## Production configuration

Use `backend/.env.production.example` as the template for production values.
The application validates production settings at startup and fails early when:

- `APP_ENV=production` and `MATACSS_JWT_SECRET` is missing or too weak
- `DATABASE_URL` is missing or uses an insecure SQLite configuration
- CORS values are missing or wildcarded
- host/port or worker settings are invalid

Do not commit real secrets. Keep deployment secrets in the runtime environment or
secret manager for the target platform.

## Backend setup

From `backend/`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create `backend/.env` from the existing environment template and configure a
local development `DATABASE_URL`. Do not commit credentials.

Start PostgreSQL:

```powershell
docker compose up -d postgres
python -m alembic upgrade head
```

Seed the development candidate, interview, assigned questions, and deterministic
test cases:

```powershell
python scripts/seed_dev_data.py
```

The seed operation is idempotent and may be run repeatedly.

Run the API:

```powershell
python -m uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`.

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Process queued submissions locally:

```powershell
python scripts/run_worker.py
```

The worker processes all currently queued jobs and exits when no jobs remain.
It does not start automatically inside FastAPI.

## Frontend setup

From `frontend/`:

```powershell
npm install
Copy-Item .env.example .env.local
npm run dev
```

Configure:

- `NEXT_PUBLIC_API_BASE_URL`, for example
  `http://127.0.0.1:8000`
- `NEXT_PUBLIC_DEMO_INTERVIEW_SESSION_ID`
- `NEXT_PUBLIC_DEMO_QUESTION_ID`

Open `http://localhost:3000`.

The assessment workspace provides Monaco editing, language selection, stdin,
Run Code, queued/running status, output, attempt navigation, and assessment
results. The frontend uses polling for asynchronous execution; it does not use
WebSockets.

## API overview

### Domain and interview lifecycle

- `POST /api/v1/candidates`
- `POST /api/v1/interviews`
- `GET /api/v1/interviews/{interview_session_id}`
- `POST /api/v1/interviews/{interview_session_id}/complete`
- `POST /api/v1/interviews/{interview_session_id}/cancel`
- `POST /api/v1/interviews/{interview_session_id}/questions`
- `POST /api/v1/interviews/{interview_session_id}/questions/bulk`
- `GET /api/v1/interviews/{interview_session_id}/questions`
- `GET /api/v1/interviews/{interview_session_id}/results`

### Questions and deterministic evaluation

- `POST /api/v1/questions`
- `POST /api/v1/questions/{question_id}/test-cases`
- `GET /api/v1/questions/{question_id}/test-cases`
- `POST /api/v1/submissions/{submission_id}/evaluate`
- `GET /api/v1/submissions/{submission_id}/evaluation`

Test-case management is a development/admin API and is not exposed in the
candidate UI.

### Submissions

- `POST /api/v1/submissions`
- `GET /api/v1/submissions/{submission_id}/status`
- `GET /api/v1/interviews/{interview_session_id}/questions/{question_id}/submissions`
- `GET /api/v1/interviews/{interview_session_id}/questions/{question_id}/latest-submission`

Execution responses distinguish queued, running, success, compilation error,
runtime error, timeout, output-limit, and sandbox failure states. Output is
not fabricated while a job is queued or running.

## Evaluation and scoring

Question test cases are authoritative for deterministic evaluation.

- CRLF/LF differences are normalized.
- Only trailing whitespace/newline differences are removed.
- No fuzzy matching is performed.
- A case passes only when execution succeeds and normalized stdout exactly
  matches expected stdout.
- Compilation, runtime, timeout, output-limit, and sandbox failures fail the
  individual case safely.
- Evaluation stops only when a fatal sandbox-level condition makes continuing
  unsafe or impossible.
- Score is `passed_test_cases / total_test_cases * 100`.
- Questions with no test cases return a clear non-scored state.

Assessment results use only the latest submission for each assigned question.
Unevaluated attempts are reported separately and are not silently converted to
zero.

## Testing

Run the focused backend tests:

```powershell
cd backend
python -m pytest tests\test_execution_jobs.py tests\test_evaluation.py tests\test_submissions.py -q
```

Run the complete non-Docker backend suite:

```powershell
python -m pytest tests --ignore=tests/integration -q
```

Run Docker-backed integrations only when the local environment provides Docker
and PostgreSQL support:

```powershell
python -m pytest tests\integration\test_sandbox_docker.py -m docker -q
python -m pytest tests\integration\test_submission_docker.py -m docker -q
```

Current verified evidence from the repository state:

- 157 non-Docker backend tests passed
- Frontend lint/build checks are expected to run in a Node-enabled environment
- Docker integration tests remain environment-dependent and are not treated as
  a required gate when Docker/PostgreSQL services are unavailable

## Implemented roadmap

### Implemented

- Candidate, interview, and question APIs
- Interview lifecycle and deterministic progress
- Interview-specific question assignment and ordering
- Monaco assessment workspace
- Per-question editor/stdin state
- Submission history and latest attempts
- Durable asynchronous execution jobs
- Local FIFO execution worker
- Explicit deterministic test-case evaluation
- Assessment-level result aggregation
- Candidate results dashboard
- Docker sandbox isolation and resource controls
- Adversarial sandbox security testing
- Alembic migrations and idempotent development seed data
- JWT bearer authentication and role-based authorization
- Secure password hashing and protected route dependencies
- Centralized environment-driven configuration and production validation
- Safe CORS handling and secret masking
- Structured observability and request/job correlation
- Deterministic Interviewer, Code Reviewer, and Edge-Case Generator foundations
- Multi-agent orchestration with validated handoffs and safe data boundaries
- Advisory feedback aggregation that never overrides official evaluation results
- Deployment/CI documentation and release-oriented project guidance

### Planned / intentionally not implemented

- Real LLM provider integration
- Autonomous execution of generated or agent-created tests
- Persistence of agent outputs to official evaluation data
- Automatic verification of generated edge-case outputs
- External production queue infrastructure beyond the local deterministic foundation
- Additional autonomous agent behavior beyond bounded deterministic orchestration

## Design boundaries

The current implementation intentionally keeps the authoritative runtime and
security boundaries explicit:

- Official evaluation and scoring remain the source of truth for correctness.
- Docker execution remains the only execution path for candidate code.
- PostgreSQL persistence and execution jobs are authoritative for the app's runtime data.
- Agent outputs remain advisory-only and cannot mutate official tests, evaluation records, or execution state.
- Real LLM integration, automatic agent persistence, and autonomous verification are not implemented.
- Production deployment still depends on a secure runtime environment for secrets and infrastructure boundary management.
