# Deployment and CI/CD

This repository keeps deployment simple and explicit. The goal is to validate the backend and frontend in CI without altering the existing MATACSS execution, assessment, auth, worker, or evaluation logic.

## CI workflow

The GitHub Actions workflow in [.github/workflows/ci.yml](../.github/workflows/ci.yml) performs the following checks:

- Backend dependency install
- Backend Python compile check
- Backend non-Docker test suite (`pytest tests --ignore=tests/integration -q`)
- Frontend dependency install
- Frontend ESLint validation
- Frontend Next.js production build
- Docker build validation for both backend and frontend images

The workflow is intentionally separated from PostgreSQL/Docker integration tests so that environment-specific checks remain optional when the required services are unavailable.

## Required environment variables

### Backend

Use the values from [backend/.env.example](../backend/.env.example) and [backend/.env.production.example](../backend/.env.production.example) as the baseline. In production, set and protect the following values with your runtime secret manager or platform-secret mechanism:

- `APP_ENV=production`
- `DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<db>`
- `MATACSS_JWT_SECRET=<strong random secret, at least 32 characters>`
- `MATACSS_JWT_ALGORITHM=HS256`
- `MATACSS_JWT_EXPIRE_MINUTES=60`
- `MATACSS_FRONTEND_ORIGINS=https://app.example.com,https://admin.example.com`
- `MATACSS_API_HOST=0.0.0.0`
- `MATACSS_API_PORT=8000`
- `MATACSS_LOG_LEVEL=INFO`

### Frontend

Set frontend environment variables in the deployment environment or `.env.local` for local development.

- `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`
- Optional: any public deployment base URLs required by the app environment.

## Local validation commands

From the repository root:

```powershell
# Backend
cd backend
python -m pip install -r requirements.txt
python -m compileall app
pytest tests --ignore=tests/integration -q

# Frontend
cd ../frontend
npm ci
npm run lint
npm run build

# Docker validation when Docker is available
cd ../backend
docker build -f Dockerfile .
cd ../frontend
docker build -f Dockerfile .
```

## Deployment image notes

- The backend image runs Uvicorn on port 8000.
- The frontend image builds the Next.js app and serves the production build on port 3000.
- Neither image changes the sandbox runtime, execution semantics, worker behavior, or evaluation pipeline.
- The deployment configuration intentionally does not add secret material or database credentials to version control.

## Operational guidance

- Keep database secrets and JWT secrets outside source control.
- Keep the PostgreSQL and Docker integration tests in their own environment-specific pipeline stage, not as a required gate when the platform does not provide those services.
- Production deployments should still validate the required non-Docker test and build gates before enabling rollout.
