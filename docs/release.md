# Release documentation

## Release scope

This repository contains the MATACSS assessment workflow, worker execution,
Docker sandbox controls, authentication, LangGraph orchestration, configured
OpenAI/Azure provider support, Question Bank lifecycle, and deployment
configuration/observability guardrails. LLM outputs are advisory and remain
separate from official deterministic evaluation.

## Implemented vs planned

### Implemented

- FastAPI backend, deterministic orchestration, and core assessment flows
- PostgreSQL-ready persistence and local SQLite compatibility for non-Docker validation
- JWT bearer authentication, password hashing, and role-based access control
- Candidate/interviewer/admin authorization boundaries
- Interview/question/submission/evaluation lifecycle
- Durable execution jobs and local worker processing
- Docker sandbox isolation and bounded execution controls
- Official evaluation and score calculation using deterministic test cases
- Configurable provider-backed interviewer, code reviewer, and edge-case agents
- Multi-agent orchestration handoff validation and advisory feedback aggregation
- Per-submission persistence and retrieval of advisory feedback and next-step recommendations
- Active-only Question Engine assignment and candidate progression
- Supported Python functional-question evaluation inside the Docker sandbox
- Admin-authenticated LLM question generation/adaptation as unverified drafts
- Production config validation, secret masking, and CORS protection
- Request/job correlation logging and observability safeguards
- Deployment and CI documentation for GitHub release use

### Planned / intentionally not included

- Autonomous execution or verification of generated test cases
- Verification and promotion of generated edge cases into official test cases
- Real-provider smoke testing without deployment credentials
- External production executor and TLS infrastructure provisioning

## Release checklist

- [x] README reflects the current implementation and known boundaries
- [x] Setup commands and environment parameters follow the actual repo layout
- [x] Authentication/JWT configuration is constrained to HMAC algorithms only
- [x] Local development defaults remain safe and non-production
- [x] Production config validation rejects insecure defaults
- [x] Docker sandbox boundary and execution policy remain separate from agent logic
- [x] AI/agent outputs remain advisory and cannot overwrite official evaluation results
- [x] Key security findings have been documented and regression-tested
- [x] Non-Docker backend validation is passing
- [x] Frontend lint/build checks pass in the current Node-enabled environment
- [x] Docker integration tests were run with an isolated SQLite schema and local Docker daemon

## Known limitations

- Real OpenAI/Azure calls require deployment credentials and were not smoke-tested in this environment.
- Generated edge cases are advisory and unverified; they are not used for official scoring.
- The Docker sandbox remains a host-level execution boundary and should be validated in a hardened deployment environment.
- PostgreSQL and Docker integration tests require the appropriate runtime services.
- The app still assumes secure secret management, a trusted deployment boundary, and production operational hardening outside the application code.

## Threat-model boundaries

The application intentionally enforces the following boundaries:

- Candidate code is executed only through the Docker sandbox path.
- Agents do not directly access Docker, PostgreSQL, or execution internals.
- Hidden tests, credentials, and sensitive runtime data are not exposed to agent generation inputs.
- Deterministic evaluation remains authoritative for execution correctness and scoring.
- AI-generated feedback remains advisory only.

This release is not a claim of full immunity to host-level, kernel-level, or deployment-level attacks; those require platform hardening beyond the application code itself.

## Verification status

### Run commands

```powershell
cd C:\Users\Abhishek\Desktop\MATACSS
cd backend
python -m compileall app tests
python -m pytest tests --ignore=tests/integration -q
```

Frontend checks (when Node deps are installed):

```powershell
cd C:\Users\Abhishek\Desktop\MATACSS\frontend
npm run lint
npm run build
```

Docker validation (when Docker is available):

```powershell
cd C:\Users\Abhishek\Desktop\MATACSS\backend
python -m pytest tests/integration -q
```

### Current results

- Backend compile check: passed
- Full non-Docker backend suite: 315 passed, 0 failed
- Docker sandbox/submission integration modules: 28 passed
- Security-focused auth/config/logging checks: passed
- Frontend lint/build: passed
- PostgreSQL runtime integration and production Compose startup: not verified in this environment

## Release recommendation

This repository is suitable for release-oriented validation as a security-conscious assessment platform. A real-provider smoke test, generated-case verification workflow, and provisioned production executor remain unverified or incomplete and should be treated as such.
