# Production Configuration

This project keeps deployment settings centralized in `backend/app/core/config.py`.
The configuration is intentionally environment-driven so local development remains
safe while production deployments fail early on insecure or incomplete settings.

## Core principles

- Use `APP_ENV` to switch the runtime profile.
- Local defaults are intentionally permissive for development only.
- Production requires explicit configuration for database connectivity, JWT
  secrets, and trusted CORS origins.
- Secrets are never committed to source control.
- Secret-bearing values are redacted in debug output and configuration reprs.

## Supported environment variables

- `APP_ENV`: `development` or `production`.
- `DEBUG`: boolean override for FastAPI debug mode.
- `DATABASE_URL`: authoritative database connection string.
- `MATACSS_JWT_SECRET`: strong secret, minimum 32 characters in production.
- `MATACSS_JWT_ALGORITHM`: JWT signing algorithm, default `HS256`.
- `MATACSS_JWT_EXPIRE_MINUTES`: JWT lifetime in minutes.
- `MATACSS_FRONTEND_ORIGINS` or `MATACSS_CORS_ALLOWED_ORIGINS`: comma-separated
  trusted origins; production requires explicit values, not `*`.
- `MATACSS_API_HOST`: bind host for the FastAPI app.
- `MATACSS_API_PORT`: bind port for the FastAPI app.
- `MATACSS_WORKER_POLL_INTERVAL_SECONDS`: queue polling interval.
- `MATACSS_WORKER_BATCH_SIZE`: job batching size.
- `MATACSS_WORKER_MAX_RETRIES`: retry policy for worker tasks.
- `MATACSS_SANDBOX_*`: sandbox runtime image and security-limits config.
- `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_TIMEOUT_SECONDS`: optional
  direct OpenAI provider configuration.
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`,
  `AZURE_OPENAI_DEPLOYMENT`, and `AZURE_OPENAI_TIMEOUT_SECONDS`: optional Azure
  OpenAI provider configuration; supply the endpoint, key, and deployment
  together.

The Docker SDK is used by both the continuous execution worker and the API's
submission-evaluation route. The Compose deployment therefore gives both
backend services a read-only mount of the Docker TLS client certificate
directory and sets `DOCKER_HOST`, `DOCKER_TLS_VERIFY`, and `DOCKER_CERT_PATH`.
Point these only to a dedicated, network-restricted execution host. Docker
Engine API client certificates grant broad daemon control; TLS does not reduce
those permissions. Never mount the application host's Docker socket or share
its daemon with this workload. See [deployment.md](deployment.md) for the call
topology, Compose network boundaries, and startup procedure.

## Production behavior

When `APP_ENV=production`, the settings layer validates that:

- `DATABASE_URL` is configured and not SQLite.
- `MATACSS_JWT_SECRET` is present and at least 32 characters.
- the token secret does not contain obvious placeholders such as `change_me`.
- `MATACSS_FRONTEND_ORIGINS` is explicit and does not contain wildcard origins.
- API host/port values are valid and positive.

If any of these checks fail, the application raises a clear `ValueError` during
configuration initialization so the deployment does not start with a fragile or
insecure configuration.

## Local development defaults

For non-production environments, the app keeps safe development defaults such as:

- `APP_ENV=development`
- `DEBUG` defaulting to `True` for local work
- `http://127.0.0.1:3000` and `http://localhost:3000` as fallback CORS origins
- local PostgreSQL defaults if no `DATABASE_URL` is supplied

These defaults are for local convenience only and are never treated as production
security settings.

## Example file

Use the checked-in template at
[backend/production.env.example](../backend/production.env.example) as a
starting point for real deployments. It contains placeholders only; do not
commit populated env files, database passwords, JWT secrets, LLM keys, or Docker
client private keys.

## Security notes

- Do not commit secrets to Git.
- Prefer environment injection via your deployment platform.
- Do not log raw JWT secrets, DB passwords, or full config dumps.
- Keep explicit CORS allowlists for each environment.

This configuration layer does not change business logic, API contracts, or the
execution boundary; it only centralizes and validates deployment configuration.
