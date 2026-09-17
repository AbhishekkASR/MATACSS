"""FastAPI application entry point."""

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.domain import router as domain_router
from app.api.routes.submissions import router as submissions_router
from app.core.config import settings
from app.core.logging import configure_logging, reset_correlation_id, sanitize_exception_message, set_correlation_id

configure_logging(settings)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_title,
    description=settings.app_description,
    version=settings.app_version,
    debug=settings.debug,
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Attach a correlation ID to each request and log the lifecycle."""
    correlation_id = request.headers.get("x-correlation-id") or uuid.uuid4().hex
    request.state.correlation_id = correlation_id
    token = set_correlation_id(correlation_id)
    started_at = time.perf_counter()
    logger.info(
        "API request started",
        extra={
            "event": "api_request_started",
            "method": request.method,
            "path": request.url.path,
        },
    )
    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers["X-Correlation-ID"] = correlation_id
        logger.info(
            "API request completed",
            extra={
                "event": "api_request_completed",
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
    except Exception as exc:
        logger.exception(
            "API request failed",
            extra={
                "event": "api_request_failed",
                "method": request.method,
                "path": request.url.path,
                "error": sanitize_exception_message(exc),
            },
        )
        raise
    finally:
        reset_correlation_id(token)


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.frontend_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-Correlation-ID"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(domain_router)
app.include_router(submissions_router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
