# MATACSS

**Multi-Agent Technical Assessment & Code Sandboxing System**

MATACSS is an AI-assisted technical interview and live-coding assessment platform. It combines a Next.js candidate workspace, a FastAPI backend, PostgreSQL persistence, LangGraph orchestration, a curated Question Bank, and restricted Docker execution.

> **Core principle:** deterministic execution and executable test-case evaluation produce the official correctness result and score. LLM/LangGraph output is advisory intelligence: it informs interview guidance and feedback but never overrides deterministic results.

## Table of Contents

- [Architecture](#architecture)
- [End-to-End Flow](#end-to-end-flow)
- [Implemented Features](#implemented-features)
- [Persistence](#persistence)
- [Database and Migrations](#database-and-migrations)
- [Environment Configuration](#environment-configuration)
- [Local Development](#local-development)
- [Worker and Execution](#worker-and-execution)
- [API Overview](#api-overview)
- [Security Model](#security-model)
- [Testing and Verified Status](#testing-and-verified-status)
- [Repository Structure](#repository-structure)
- [Future Work](#future-work)

## Architecture

```mermaid
flowchart TD
    Candidate --> Frontend[Next.js + Monaco Editor]
    Frontend --> API[FastAPI API]
    API --> DB[(PostgreSQL)]
    API --> Engine[Question Engine]
    Engine --> Bank[Question Bank]
    API --> Jobs[Durable Execution Jobs]
    Jobs --> Worker[Polling Worker]
    Worker --> Sandbox[Restricted Docker Sandbox]
    Sandbox --> Evaluation[Deterministic Evaluation]
    Evaluation --> DB
    API --> Graph[LangGraph Assessment Flow]
    Graph --> Interviewer[Interviewer Agent]
    Graph --> Reviewer[Code Reviewer Agent]
    Graph --> Edge[Edge-Case Agent]
    Graph --> Feedback[Feedback Aggregator]
    Graph --> DB
    DB --> Results[Assessment Results and Advisory Feedback]
    Results --> Frontend
```

### Components

- **Frontend:** Next.js, React, TypeScript, and Monaco Editor provide the candidate-facing workspace.
- **Backend:** FastAPI exposes authenticated REST endpoints. SQLAlchemy persists state to PostgreSQL, and Alembic manages schema evolution.
- **AI orchestration:** LangGraph coordinates shared assessment state across the Interviewer, Code Reviewer, Edge-Case, orchestration, and Feedback Aggregator stages.
- **Question system:** the Question Bank stores questions, test cases, lifecycle state, provenance, and LLM lineage. The Question Engine retrieves and assigns eligible questions and exposes generation/adaptation/validation workflows.
- **Execution:** persisted submissions create durable execution jobs. A worker claims jobs and invokes the Docker sandbox.
- **Results:** deterministic evaluations are persisted as official results; advisory agent feedback is persisted separately for assessment reporting.

## End-to-End Flow

```text
Candidate -> interview -> Question Engine -> question assignment -> Monaco coding
-> Submission API -> persisted submission -> execution job -> worker
-> Docker sandbox -> deterministic test execution -> official evaluation
-> LangGraph advisory analysis -> persisted feedback -> assessment result/report
```

1. A candidate is associated with an interview session and receives assigned questions.
2. The Question Engine retrieves active, non-repeated questions and manages assignment and lifecycle workflows.
3. The candidate writes code in the Monaco-based frontend and submits through the API.
4. The submission and durable execution job are persisted.
5. The worker polls and claims available jobs, then executes supported code in a short-lived Docker container.
6. Executable test cases determine pass/fail counts and the official evaluation result.
7. LangGraph agents consume validated assessment context and safe deterministic summaries to create advisory feedback.
8. Assessment results combine official evaluation data with separately persisted advisory feedback.

## Implemented Features

### Authentication and RBAC

- JWT registration, login, and current-user endpoints.
- Candidate, interviewer, and admin user roles.
- Role and ownership checks for protected candidate, interview, question, submission, and Question Engine operations when authentication is configured.
- Production validation for database settings, JWT secrets/algorithms, and CORS configuration.

### Candidate and Interview Lifecycle

- Candidate and interview-session creation.
- Interview progress, completion, and cancellation.
- Single and bulk assignment of active questions.
- Assigned-question delivery, question navigation, submission history, and latest-submission retrieval.
- Persisted assessment state, evaluation summaries, assessment results, and advisory feedback.

### Question Bank

- Question creation and metadata for title, description, difficulty, expected language, input/output formats, constraints, supported languages, and starter code.
- Executable test cases with sample/private classification, functional/stdin classification, ordering, and limits.
- Lifecycle states: `draft`, `validated`, `approved`, `active`, and `deprecated`.
- Provenance records for source, platform, original identifier, contest, dataset, URL, and license metadata.
- LLM lineage for curated, generated, and adapted questions.
- Only active questions are assignable to interviews.

### Question Engine

- Retrieval of active, non-repeated questions.
- Filtering and assignment for assessments.
- APIs for question generation, adaptation, validation, lifecycle transitions, assessment start/resume, and next-question selection.
- Repeat prevention is enforced through assignment and assessment context.

Automatic adaptive difficulty is **not** implemented. The existing system supplies an advisory foundation and Question Engine controls for future work.

### LiveCodeBench

The repository contains a LiveCodeBench decoder, normalizer, importer, and download/checksum scripts. The raw local dataset is ignored by Git. Imported records retain provenance and are normalized into Question Bank entities; import status depends on the available test-case format and validation state. No dataset statistics are asserted here.

### LangGraph Agents

- **Interviewer Agent:** returns a structured `continue` or `finish` recommendation from assessment context. The Question Engine—not the LLM—resolves any next active, non-repeated question.
- **Code Reviewer Agent:** provides advisory code-review findings from supplied source and safe deterministic execution context.
- **Edge-Case Agent:** provides advisory boundary-case reasoning from public question context and execution summaries. It does not become the official evaluator or modify official test results.
- **Feedback Aggregator:** combines the validated agent outputs into structured advisory assessment feedback.

### LLM Provider Foundation

The backend-owned provider abstraction defines typed messages, responses, and safe provider errors.

- Azure OpenAI is selected when endpoint, API key, and deployment are all configured.
- Direct OpenAI is used when Azure is not configured and `OPENAI_API_KEY` is present.
- Model/deployment and timeout settings are environment configured and validated.
- Settings representations mask credentials.
- Agent providers validate structured JSON responses against their orchestration contracts.

### Durable Execution and Docker Sandbox

Submissions create database-backed execution jobs. `backend/scripts/run_worker.py` continuously polls, claims available jobs, runs the sandbox, and persists terminal state. The implementation does not use ARQ, Celery, RabbitMQ, Redis, dead-letter queues, or automatic job retries.

Every candidate execution uses a short-lived Docker container with:

- disabled networking;
- non-root execution (`65532:65532`);
- a read-only root filesystem and bounded writable `/tmp` tmpfs;
- no host volumes or candidate access to a Docker socket;
- `no-new-privileges`, dropped capabilities, and container cleanup;
- configured CPU, memory, PID, timeout, and stdout/stderr limits.

This is a hardened execution boundary, not a mathematical guarantee against every Docker, container-runtime, or kernel escape.

### Deterministic Evaluation and Assessment Feedback

The evaluator runs executable test cases, records execution output/status, computes official pass/fail information and score, and persists the evaluation. Given the same submission, runtime, and tests, it is designed to produce reproducible results.

LangGraph feedback is advisory and separately persisted. Assessment reporting presents deterministic evaluation alongside advisory feedback without allowing the latter to recalculate or replace official correctness.

## Persistence

Major persisted concepts include:

- users and authentication roles;
- candidates and interview sessions;
- questions, test cases, and interview-question assignments;
- question provenance and LLM lineage;
- submissions and execution jobs;
- deterministic evaluation results;
- assessment feedback and assessment-result projections.

PostgreSQL is the production system of record. SQLAlchemy provides ORM persistence and Alembic manages schema revisions.

## Database and Migrations

PostgreSQL 16 is available through `backend/docker-compose.yml` for local development. Copy `backend/.env.example` to `backend/.env`, choose a non-placeholder local password, and keep `POSTGRES_PASSWORD` and `DATABASE_URL` consistent.

Run from `backend/`:

```powershell
docker compose up -d postgres
python -m alembic upgrade head
python -m alembic heads
python -m alembic downgrade -1
```

The current migration head is `007_assessment_feedback`.

## Environment Configuration

Copy `backend/.env.example` to `backend/.env`. `.env`, TLS client certificates, and API keys are ignored and must not be committed.

| Variables | Purpose | Required / example |
| --- | --- | --- |
| `APP_ENV`, `DEBUG`, `MATACSS_APP_TITLE`, `MATACSS_API_HOST`, `MATACSS_API_PORT`, `MATACSS_LOG_LEVEL` | application runtime | local defaults exist; e.g. `APP_ENV=development` |
| `DATABASE_URL`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW` | PostgreSQL connection and pool | required for PostgreSQL; `postgresql+asyncpg://user:password@host:5432/matacss` |
| `MATACSS_FRONTEND_ORIGINS` | trusted browser origins | configure for deployment; comma-separated URLs |
| `MATACSS_JWT_SECRET`, `MATACSS_JWT_ALGORITHM`, `MATACSS_JWT_EXPIRE_MINUTES` | authentication | secret required for production; `HS256`, `60` |
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS` | direct OpenAI provider | key required only when using direct OpenAI; never commit it |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_TIMEOUT_SECONDS` | Azure OpenAI provider | endpoint/key/deployment must be supplied together; e.g. `https://resource.openai.azure.com` |
| `MATACSS_DOCKER_HOST`, `MATACSS_DOCKER_CERTS_DIR` | dedicated executor TLS connection | required by Compose API/worker services; e.g. `tcp://executor.example:2376` |
| `MATACSS_SANDBOX_PYTHON_IMAGE`, `MATACSS_SANDBOX_CPP_IMAGE`, `MATACSS_SANDBOX_JAVA_IMAGE`, `MATACSS_SANDBOX_*` limits | sandbox images and resource limits | defaults exist; tune for deployment |
| `MATACSS_WORKER_POLL_INTERVAL_SECONDS`, `MATACSS_WORKER_BATCH_SIZE`, `MATACSS_WORKER_MAX_CONCURRENCY`, `MATACSS_WORKER_MAX_RETRIES` | worker polling and throughput settings | defaults exist; e.g. `5`, `10`, `1` |
| `POSTGRES_PUBLISHED_PORT`, `MATACSS_API_BIND_ADDRESS`, `MATACSS_API_PUBLISHED_PORT`, `MATACSS_FRONTEND_BIND_ADDRESS`, `MATACSS_FRONTEND_PUBLISHED_PORT`, `NEXT_PUBLIC_API_BASE_URL` | local Compose/browser bindings | defaults exist; browser URL is public, not a secret |

## Local Development

### Requirements

- Python 3.11 or newer
- Node.js/npm for the frontend
- Docker Desktop or Docker Engine
- PostgreSQL through the Compose service or an equivalent configured instance

### Clone and setup

```powershell
git clone https://github.com/AbhishekkASR/MATACSS.git
cd MATACSS
Copy-Item backend/.env.example backend/.env
```

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
docker compose up -d postgres
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

### Worker, health, and API documentation

In a separate terminal from `backend/`:

```powershell
python scripts/run_worker.py
Invoke-RestMethod http://127.0.0.1:8000/health
```

The API base path is `/api/v1`. FastAPI serves OpenAPI JSON at `/openapi.json` and interactive Swagger UI at `/docs`.

To start the complete Compose stack after configuring all required environment values:

```powershell
cd backend
docker compose up --build
```

## Worker and Execution

Run the worker with:

```powershell
cd backend
python scripts/run_worker.py
```

The worker polls pending jobs, claims work using the persistence layer, executes candidate code in the Docker sandbox, and persists terminal job/submission results. Terminal execution outcomes include successful execution, compilation error, runtime error, timeout, output-limit handling, and sandbox infrastructure failure as represented by the execution pipeline.

## API Overview

All endpoints below are implemented; detailed request/response schemas are authoritative at `/openapi.json`.

| Group | Endpoints / purpose | Access |
| --- | --- | --- |
| Health | `GET /health` | public |
| Authentication | `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me` | registration/login public; current user authenticated |
| Candidates | `POST /api/v1/candidates` | interviewer/admin when auth is configured |
| Interviews | create, progress, results, completion, cancellation, question assignment/listing, submission history/latest submission under `/api/v1/interviews/...` | role/ownership controlled |
| Questions | `POST /api/v1/questions`, create/list question test cases | role controlled; sample filtering for unprivileged views |
| Question Engine | assessment start/resume/next; generate, adapt, validate, transition, retrieve under `/api/v1/question-engine/...` | role controlled |
| Submissions and evaluations | create submission, status, evaluate, and evaluation retrieval under `/api/v1/submissions/...` | role/ownership controlled |

## Security Model

- JWT authentication and candidate/interviewer/admin authorization protect configured API operations.
- Production configuration validates non-placeholder database/JWT settings and explicit CORS origins.
- Secrets are environment based, ignored by Git, and masked in settings representations.
- Candidate code is isolated by the Docker controls described above: no network, no host mounts, non-root execution, read-only root filesystem, capability restrictions, bounded `/tmp`, resource limits, timeout, bounded output, and cleanup.
- The sandbox is a practical defense-in-depth boundary, with the container/kernel limitations stated above.

## Testing and Verified Status

**Development / pre-alpha verified status**

- Backend non-Docker tests: **315 passed, 0 failed**.
- PostgreSQL/Docker integration tests: **29 passed, 0 failed**.
- Frontend lint, frontend production build and TypeScript checks, Python compilation, and `git diff --check` passed.
- Alembic has one head: **`007_assessment_feedback`**.

A real Azure LLM → LangGraph → Docker execution → deterministic evaluation → persisted advisory feedback → assessment result flow was verified. The real deterministic evaluation produced **2/2 passing tests and 100%**. The interviewer recommended `finish`, so that particular session ended without another assigned question; continue/finish behavior is separately covered by Question Engine API tests.

Run tests from `backend/`:

```powershell
python -m pytest
python -m pytest tests/integration/test_sandbox_docker.py -m docker
python -m pytest tests/integration/test_postgres_database.py -m postgres
```

Docker and PostgreSQL-marked tests require their respective services.

## Repository Structure

```text
MATACSS/
├── README.md                 # single project documentation source
├── backend/
│   ├── alembic/              # schema migrations
│   ├── app/                  # API, models, services, orchestration, Question Bank
│   ├── scripts/              # worker and dataset utilities
│   ├── tests/                # backend and integration tests
│   ├── docker-compose.yml    # local service stack
│   └── .env.example          # configuration template
├── frontend/
│   ├── app/                  # Next.js routes
│   ├── components/           # UI and Monaco workspace components
│   └── package.json          # frontend scripts/dependencies
├── data/                     # local, ignored dataset location
└── docs/                     # supporting project documents
```

## Future Work

The following are future work, not currently implemented features:

- **Production infrastructure:** scalable execution infrastructure, worker orchestration, load balancing, and deployment hardening.
- **Question intelligence:** calibration, stronger recommendation, similarity/plagiarism detection, and richer question analytics.
- **Adaptive interviews:** dynamic difficulty and deeper performance adaptation.
- **AI improvements:** richer feedback, reasoning, personalization, and evaluation analytics.
- **Candidate and recruiter experience:** dashboards, history/progress visualization, question management UI, and assessment analytics.
- **Security and observability:** stronger monitoring, auditability, and advanced threat detection.
- **CI/CD and demo:** production pipelines, automated deployment, public demo, and continuing documentation improvements.

## Documentation Principle

`README.md` is the single source of truth for MATACSS project documentation. There is no dependency on `backend/README.md`.
