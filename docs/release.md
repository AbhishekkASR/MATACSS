# Release documentation

## Release scope

This repository is a deterministic, security-conscious release candidate for the MATACSS assessment platform. It includes the core assessment workflow, worker execution, Docker sandbox controls, authentication, orchestration foundations, and production configuration/observability guardrails.

This release intentionally does not include real LLM integration, autonomous generated-test execution, or persistence of AI outputs.

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
- Bounded agent foundations for interviewer, code reviewer, and edge-case generation
- Multi-agent orchestration handoff validation and advisory feedback aggregation
- Production config validation, secret masking, and CORS protection
- Request/job correlation logging and observability safeguards
- Deployment and CI documentation for GitHub release use

### Planned / intentionally not included

- Real LLM provider integration
- Autonomous execution or verification of generated test cases
- Agent-side persistence into official evaluation data
- External production queueing beyond the deterministic local worker foundation
- Frontend or API features that rely on untrusted autonomous actions

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
- [x] Frontend lint/build checks are documented as required validation steps
- [x] Docker integration tests remain environment-dependent and are not treated as a silent pass in minimal environments

## Known limitations

- The repository is intentionally deterministic and does not add real model providers.
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
cd C:\Users\Abhishek\Desktop\MATACSS.worktrees\edge-case-generator-agent-foundation
python -m compileall backend/app
cd backend
python -m pytest tests --ignore=tests/integration -q
```

Frontend checks (when Node deps are installed):

```powershell
cd frontend
npm run lint
npm run build
```

Docker validation (when Docker is available):

```powershell
cd backend
python -m pytest tests/integration -q
```

### Current results

- Backend compile check: passed
- Full non-Docker backend suite: 157 passed, 0 failed
- Security-focused auth/config/logging checks: passed
- Frontend lint/build: run in a Node-enabled environment as required, without modifying app behavior
- Docker/PostgreSQL integration tests: environment-dependent and only valid when the required services are available locally

## Release recommendation

This repository is suitable for public-facing documentation and release-oriented validation as a deterministic, security-conscious assessment platform foundation. It should be published with the explicit caveat that real LLM integration, autonomous generated-case verification, and external production infrastructure remain future work rather than current features.
