# MATACSS Backend

MATACSS is a technical-assessment backend. It manages candidates, interviews, questions, submissions, deterministic code evaluation, persisted assessment state, and advisory feedback produced through a LangGraph workflow.

Deterministic execution and evaluation are the correctness authority. LLM output is advisory: it can provide interview guidance, code-review observations, edge-case suggestions, and assessment feedback, but it does not alter official test results or scores.

## Architecture

- **FastAPI** exposes the HTTP API.
- **PostgreSQL**, asynchronous **SQLAlchemy**, and **Alembic** provide persistence and migrations.
- **LangGraph** coordinates interviewer, code-review, edge-case, orchestration, and feedback stages.
- A backend-owned **LLM provider abstraction** supports Azure OpenAI and direct OpenAI configuration.
- The **Question Bank / Question Engine** persists lifecycle, provenance, LLM lineage, test cases, retrieval, assignment, generation, adaptation, and validation operations.
- Durable database-backed **execution jobs** are claimed by a polling worker.
- A restricted **Docker sandbox** executes candidate code; deterministic results, evaluations, assessment state, and advisory feedback are persisted.

## Implemented Features

### Authentication and RBAC

- JWT registration, login, and current-user endpoints.
- Candidate, interviewer, and admin roles.
- Role checks and candidate/interview ownership checks on protected operations when authentication is configured.
- Production configuration validation for database, JWT, CORS, and operational settings.

### Assessment and Interview Lifecycle

- Candidate and interview creation, progress retrieval, completion, and cancellation.
- Single and bulk assignment of active questions.
- Question delivery, navigation, submission history, and latest-submission retrieval.
- Persisted assessment state, deterministic evaluation summaries, results, and advisory feedback.

### Question Bank and Question Engine

- Question metadata: input/output formats, constraints, language support, starter code, and lifecycle state.
- Test cases: sample/private and functional/stdin classification, ordering, and limits.
- Lifecycle states: `draft`, `validated`, `approved`, `active`, and `deprecated`.
- Provenance for source platform, original identifier, contest, dataset, URL, and license metadata.
- LLM lineage for curated, generated, and adapted questions.
- Active non-repeated-question retrieval; Question Engine generation, adaptation, validation, transition, and assignment APIs.

### LiveCodeBench

The repository includes LiveCodeBench decoder, normalizer, importer, and download/checksum tooling. The local dataset is ignored by Git; the imported local JSONL contains 175 records and is not committed. AtCoder records with usable private tests are normalized to `validated`; incomplete imports and LeetCode functional-format records remain `draft` until lifecycle advancement.

### LangGraph Agents

The compiled assessment graph runs over validated assessment context:

- **Interviewer Agent** returns a structured `continue` or `finish` recommendation. The Question Engine—not the LLM—resolves the next active, non-repeated question.
- **Code Reviewer Agent** produces advisory findings from source and safe deterministic execution context.
- **Edge-Case Generator Agent** produces structured edge-case guidance from public question context and execution summaries.
- **Orchestrator and Feedback Aggregator** combine outputs into structured, persisted advisory assessment feedback.

Automatic adaptive difficulty is future work; the current implementation provides the Question Engine and advisory-decision foundation only.

### LLM Provider Support

`app.core.llm_provider` defines typed messages, responses, provider errors, and a provider interface.

- Azure OpenAI is used when endpoint, API key, and deployment are all configured.
- Direct OpenAI is used when Azure is not configured and `OPENAI_API_KEY` is present.
- Model/deployment and timeouts are environment-configured; invalid configuration fails safely.
- Settings representations mask API keys.
- Agent providers request and validate structured JSON payloads where their contracts require them.

Use local `.env` files for secrets. They are ignored and must never be committed.

### Submission and Execution Pipeline

```text
Candidate submission -> persisted submission and execution job -> polling worker
-> Docker sandbox -> persisted execution result -> deterministic evaluation
-> persisted evaluation -> advisory LangGraph feedback -> assessment result/report
```

`scripts/run_worker.py` continuously polls durable execution jobs, claims available work, invokes the sandbox, and persists terminal state. The repository does not use RabbitMQ, Redis, Celery, ARQ, dead-letter queues, or automatic job retries.

### Docker Sandbox Security

Each candidate execution uses a short-lived Docker container with:

- network disabled and no host volumes;
- non-root user (`65532:65532`), read-only root filesystem, and bounded writable `/tmp` tmpfs;
- configured memory, CPU, PID, timeout, and stdout/stderr limits;
- `no-new-privileges`, all capabilities dropped, and container cleanup in `finally`.

The Compose API and worker use TLS client certificates for a separately configured execution daemon. Candidate containers receive neither a Docker socket nor host volumes. These controls reduce exposure but do not guarantee protection from every possible container, Docker, or kernel escape.

## Verified Development / Release Status

The verified current project status from development work is:

- Backend non-Docker tests: **315 passed, 0 failed**.
- PostgreSQL/Docker integration tests: **29 passed, 0 failed**.
- Frontend lint, production build, TypeScript checks, Python compilation, and `git diff --check` passed.
- Alembic has one migration head: **`007_assessment_feedback`**.
- A real Azure LLM → LangGraph → Docker execution → deterministic evaluation → persisted advisory-feedback E2E flow was verified.
- Deterministic evaluation produced **2/2 passing tests and 100%**; advisory LangGraph feedback was persisted.
- The real interviewer recommended `finish` in that run, so no additional question was assigned. Continue/finish behavior is separately covered by Question Engine API tests.

## Local Development

Run these commands from `backend/`.

### Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env`, set local values, and never commit `.env`, TLS certificates, or API keys.

### PostgreSQL, migrations, API, and worker

The Compose stack defines PostgreSQL, migrations, API, worker, and frontend. It requires the values in `.env.example`, including PostgreSQL credentials and the TLS endpoint/certificates for the dedicated Docker execution daemon.

```powershell
docker compose up -d postgres
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
python scripts/run_worker.py
```

To start the complete Compose stack after supplying the required environment values:

```powershell
docker compose up --build
```

The default local API is `http://127.0.0.1:8000`; health is `GET /health`.

### Tests and migrations

```powershell
python -m pytest
python -m pytest tests/integration/test_sandbox_docker.py -m docker
python -m pytest tests/integration/test_postgres_database.py -m postgres
python -m alembic heads
python -m alembic downgrade -1
```

Docker and PostgreSQL-marked tests require their respective services.

### Relevant environment variables

- Database: `DATABASE_URL`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.
- Authentication: `MATACSS_JWT_SECRET`, `MATACSS_JWT_ALGORITHM`, `MATACSS_JWT_EXPIRE_MINUTES`.
- Worker: `MATACSS_WORKER_POLL_INTERVAL_SECONDS`, `MATACSS_WORKER_BATCH_SIZE`, `MATACSS_WORKER_MAX_CONCURRENCY`.
- Sandbox: `MATACSS_DOCKER_HOST`, `MATACSS_DOCKER_CERTS_DIR`, runtime images, and `MATACSS_SANDBOX_*` limits.
- LLM: `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_TIMEOUT_SECONDS`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`, and `AZURE_OPENAI_TIMEOUT_SECONDS`.

## API Reference

All groups except health are under `/api/v1`.

| Group | Implemented endpoints |
| --- | --- |
| Health | `GET /health` |
| Authentication | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Candidates and interviews | candidate/interview creation, progress, results, completion, cancellation, assignment, and submission-history routes |
| Questions | question creation, test-case creation/listing, and interview-question assignment/listing |
| Question Engine | assessment start/resume/next; generate, adapt, validate, transition, and retrieve questions |
| Submissions | create submission, get status, trigger evaluation, and retrieve evaluation |

`/openapi.json` is the authoritative request/response contract for a running API.

## Future Work / Roadmap

- Production-grade execution infrastructure and scalable worker orchestration.
- Richer adaptive interviewing and question recommendation/calibration.
- Larger question-intelligence and quality-calibration systems.
- Plagiarism or similarity detection.
- Candidate and recruiter/admin dashboard improvements.
- Advanced observability, performance/scaling, CI/CD, and deployment hardening.
