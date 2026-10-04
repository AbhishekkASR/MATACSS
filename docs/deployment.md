# Deployment

The Compose stack in [backend/docker-compose.yml](../backend/docker-compose.yml)
provides PostgreSQL, Alembic migrations, a FastAPI API, a separate continuous
execution worker, and the production-built Next.js frontend. It does not start a
Docker-in-Docker daemon or mount the host's Docker socket.

## Execution topology and trust boundary

Code submissions are queued by `POST /api/v1/submissions` and processed by
`backend/scripts/run_worker.py`, which creates restricted short-lived containers
through `DockerSandboxService`. The API also creates those containers directly
when `POST /api/v1/submissions/{submission_id}/evaluate` evaluates test cases.
Consequently **both API and worker need Docker Engine API access** in the current
architecture; granting access only to the worker would break evaluation.

`DockerSandboxService` disables network access for candidate containers, limits
CPU, memory, PIDs, and output, and drops capabilities. These controls do not turn
Docker daemon access into a low-privilege API: anyone holding its client
certificate has broad control of that daemon. Do not bind-mount
`/var/run/docker.sock`, use the application host's shared Docker daemon, or
expose an unauthenticated Docker TCP endpoint.

For production, point `MATACSS_DOCKER_HOST` at a **dedicated, isolated execution
host** with a mutually authenticated TLS Docker endpoint (normally port 2376).
Restrict that endpoint with host/network firewall rules to the API and worker;
keep it off the public internet, do not run application workloads on it, and
keep its Docker client CA/certificate/key outside the repository. The API and
worker receive the client certificate read-only and `docker.from_env()` uses
`DOCKER_HOST`, `DOCKER_TLS_VERIFY=1`, and `DOCKER_CERT_PATH`. TLS authenticates
and encrypts the connection but does not scope Docker API permissions. If the
dedicated, isolated executor and its network restrictions cannot be provided,
do not start code execution in production; a narrower worker-only boundary
requires changing the API evaluation call path, which is outside this
configuration-only deployment.

## Configure and start

1. Copy [backend/.env.example](../backend/.env.example) to `backend/.env` for a
   local deployment, or use [backend/production.env.example](../backend/production.env.example)
   as a production reference. Replace placeholders; keep `POSTGRES_PASSWORD`
   and the password in `DATABASE_URL` identical. Use a URL-safe DB password or
   percent-encode reserved characters in `DATABASE_URL`.
2. Provision `ca.pem`, `cert.pem`, and `key.pem` in the directory named by
   `MATACSS_DOCKER_CERTS_DIR`. These are the client credentials for the
   dedicated TLS executor, not host Docker credentials. Protect the private key
   and do not commit this directory.
3. Set `MATACSS_DOCKER_HOST` to that executor's TLS endpoint and set
   `NEXT_PUBLIC_API_BASE_URL` to the API URL that users' browsers can reach.
   `NEXT_PUBLIC_API_BASE_URL` is embedded in the frontend at image build time
   and is public configuration, not a secret.
4. Start from the repository root:

   ```powershell
   Copy-Item backend/.env.example backend/.env
   docker compose --env-file backend/.env -f backend/docker-compose.yml up --build -d
   ```

   The example contains placeholders and an example executor hostname; the
   executor and its certificates must be configured before API/worker startup.
   For production, inject actual secrets from the deployment secret manager
   rather than committing them to an env file.
5. Check service status with `docker compose --env-file backend/.env -f
   backend/docker-compose.yml ps`. Do not run `docker compose config` with real
   secrets in a terminal whose output is captured; Compose config output can
   contain interpolated values.

The `migrate` one-shot service waits for PostgreSQL's `pg_isready` health check
and runs `alembic upgrade head`; API and worker wait for successful migration
completion. PostgreSQL data is kept in the named volume
`matacss_postgres_data`. Back up that volume/database before applying production
migrations.

## Services and health checks

| Service | Purpose | Health/readiness behavior |
| --- | --- | --- |
| `postgres` | PostgreSQL 16 | `pg_isready` health check; data volume persists |
| `migrate` | Alembic schema upgrade | One-shot; API and worker require successful exit |
| `api` | FastAPI on port 8000 | Existing `/health` endpoint liveness check |
| `worker` | Continuous queued-job executor | Process liveness check; restarts on exit |
| `frontend` | Next.js production server on port 3000 | HTTP check against the frontend |

The existing `/health` endpoint is a liveness response; it does not probe the
database or executor. Compose's startup dependencies gate initial service
creation on migrations, but they do not detect later database/executor
failures. The worker's process check likewise does not prove queue or executor
availability. Monitor logs and service health in the deployment platform, and
use a TLS reverse proxy for externally reachable production routes. By default,
published ports bind to loopback; set the `MATACSS_*_BIND_ADDRESS` values only
when the host firewall and ingress proxy are configured.

## Configuration and secrets

The backend reads these actual settings (see
[backend/app/core/config.py](../backend/app/core/config.py)):

- PostgreSQL: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
  `DATABASE_URL`, `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`.
- Runtime/API: `APP_ENV`, `DEBUG`, `MATACSS_APP_TITLE`, `MATACSS_API_HOST`,
  `MATACSS_API_PORT`, `MATACSS_LOG_LEVEL`, `MATACSS_FRONTEND_ORIGINS`.
- Authentication: `MATACSS_JWT_SECRET`, `MATACSS_JWT_ALGORITHM`,
  `MATACSS_JWT_EXPIRE_MINUTES`.
- Worker: `MATACSS_WORKER_POLL_INTERVAL_SECONDS`,
  `MATACSS_WORKER_BATCH_SIZE`, `MATACSS_WORKER_MAX_CONCURRENCY`,
  `MATACSS_WORKER_MAX_RETRIES`.
- Sandbox: `MATACSS_SANDBOX_PYTHON_IMAGE`, `MATACSS_SANDBOX_CPP_IMAGE`,
  `MATACSS_SANDBOX_JAVA_IMAGE`, `MATACSS_SANDBOX_TIMEOUT_SECONDS`,
  `MATACSS_SANDBOX_MEMORY_LIMIT`, `MATACSS_SANDBOX_CPU_LIMIT`,
  `MATACSS_SANDBOX_PIDS_LIMIT`, `MATACSS_SANDBOX_OUTPUT_LIMIT_BYTES`.
- LLM: direct OpenAI uses backend-only `OPENAI_API_KEY`, `OPENAI_MODEL`, and
  `OPENAI_TIMEOUT_SECONDS`. Azure OpenAI uses
  `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`,
  `AZURE_OPENAI_DEPLOYMENT`, and `AZURE_OPENAI_TIMEOUT_SECONDS`.

The Compose-only executor and port settings are `MATACSS_DOCKER_HOST`,
`MATACSS_DOCKER_CERTS_DIR`, `POSTGRES_PUBLISHED_PORT`,
`MATACSS_API_BIND_ADDRESS`, `MATACSS_API_PUBLISHED_PORT`,
`MATACSS_FRONTEND_BIND_ADDRESS`, `MATACSS_FRONTEND_PUBLISHED_PORT`, and
`NEXT_PUBLIC_API_BASE_URL`. Only the frontend base URL is compiled into the
browser image; LLM keys, database credentials, and JWT secrets are passed only
to backend containers. Never use `NEXT_PUBLIC_` for secrets.

`backend/.dockerignore` and `frontend/.dockerignore` exclude env files,
credentials, local databases, and build/development artifacts from image build
contexts. Use a protected secret manager or deployment environment for real
values. Do not print environment contents or commit populated `.env` files.

## Build and validate

With Docker Compose v2 and configured deployment variables, validate the
Compose model without printing its resolved values:

```powershell
docker compose --env-file backend/.env -f backend/docker-compose.yml config --quiet
docker compose --env-file backend/.env -f backend/docker-compose.yml build
```

After copying either environment template to `backend/.env`, validate the
Compose model before starting services:

```powershell
docker compose --env-file backend/.env -f backend/docker-compose.yml config --quiet
```

For manual image builds, run `docker build -f backend/Dockerfile backend` and
`docker build -f frontend/Dockerfile frontend` from the repository root.
