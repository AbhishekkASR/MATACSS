# Observability and Logging

This repository uses deterministic, bounded runtime logging for API traffic and worker activity. The goal is to make operational troubleshooting easier without exposing secrets, source code, hidden test data, or execution payloads.

## Responsibilities

- Centralized logging configuration is driven by the app settings layer.
- All HTTP requests carry a correlation ID used across the request lifecycle.
- Worker jobs emit structured lifecycle events that include the job ID and submission ID but never the candidate source code or runtime output.
- Exception logging is sanitized before emission.

## Configuration

The application reads the optional environment variable `MATACSS_LOG_LEVEL` to set the logger severity. Supported values are `DEBUG`, `INFO`, `WARNING`, `ERROR`, and `CRITICAL`. The default is `INFO`.

## Correlation IDs

Each API request receives an `X-Correlation-ID` header value. If the client does not provide one, the server creates a UUID-based ID and echoes it back in the response headers. The same correlation ID is attached to log records during the request lifecycle.

The worker also binds a per-job correlation ID derived from the execution job ID while it is processing. That keeps job claims, sandbox failures, and completion events traceable without leaking source content or runtime payloads.

## Redaction rules

The logging layer redacts sensitive content before it reaches logs, including:

- `Authorization: Bearer ...`
- `password=...`
- `token=...`
- `secret=...`
- `JWT=...`
- API keys

No source code, stdin, stdout, hidden tests, Docker internals, database credentials, or JWTs are logged.

## Operational events

Important lifecycle events include:

- API request start/completion/error
- execution job claim and completion
- sandbox execution failure
- stale job detection and failure marking
- orchestration graph failure and completion

## Future extension

This step is intentionally limited to deterministic, safe observability. It does not implement production log shipping, remote telemetry, or live tracing beyond in-process structured logs.
