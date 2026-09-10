"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.domain import router as domain_router
from app.api.routes.submissions import router as submissions_router
from app.core.config import settings

app = FastAPI(
    title=settings.app_title,
    description=settings.app_description,
    version=settings.app_version,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.frontend_origins),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(health_router)
app.include_router(domain_router)
app.include_router(submissions_router)
