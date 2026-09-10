"""Health-check API routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Return the current service health status."""
    return {"status": "healthy"}
