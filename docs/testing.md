# MATACSS Testing Summary

This repository contains a layered, deterministic test suite covering the full assessment lifecycle without turning real LLMs or Docker execution into a production dependency.

## Coverage areas

- auth and authorization isolation
- candidate/interview/question lifecycle
- submission enqueueing and worker claiming
- sandbox execution and resource isolation
- evaluation scoring and result generation
- LangGraph interviewer/code-review/edge-case orchestration
- deterministic feedback aggregation
- production configuration validation
- observability/logging and correlation IDs
- Docker-backed integration flows when available in the runtime environment

## High-value regression coverage

The suite includes end-to-end tests for:

- candidate -> interview -> question assignment -> submission -> worker completion -> evaluation
- deterministic graph execution through assessment context, interviewer, reviewer, edge-case generation, orchestration, and feedback aggregation
- worker stale-job handling and bounded execution behavior
- production config edge cases and secret redaction
- request correlation IDs and sanitized logging output

## Execution commands

Run the focused regression set:

```bash
cd backend
python -m pytest tests/test_end_to_end_pipeline.py tests/test_observability.py -q
```

Run the full non-Docker backend suite:

```bash
cd backend
python -m pytest tests -q -k "not docker"
```

Compile the backend package:

```bash
cd backend
python -m compileall app
```

Run Docker-backed integration tests if the environment supports them:

```bash
cd backend
python -m pytest tests/integration/test_submission_docker.py -q
```

## Current project status

The deterministic core, worker, sandbox, auth, orchestration, and production config layers are covered by the existing suite. The Docker integration tests remain environment-sensitive and are expected to be skipped or fail in minimal environments where Docker is unavailable or not configured for the full sandbox runtime.

## Gaps / known limitations

- There is no front-end browser suite in this repository; the API flow is validated instead.
- Real LLM providers and autonomous verification are intentionally absent by design.
- Docker integration is only exercised where the local runtime supports the required container environment.
