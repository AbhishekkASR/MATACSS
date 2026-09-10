"""Durable queue operations for execution jobs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExecutionJob, Submission
from app.services.database_service import claim_next_execution_job


async def enqueue_job(
    session: AsyncSession, submission: Submission
) -> ExecutionJob:
    """Persist the one queued job associated with a submission."""
    job = ExecutionJob(
        submission_id=submission.id,
        status="queued",
        attempt_count=0,
        created_at=submission.created_at,
    )
    session.add(job)
    await session.flush()
    return job


async def claim_next_job(
    session: AsyncSession,
) -> tuple[Submission, ExecutionJob] | None:
    """Claim the oldest queued job using the database locking strategy."""
    return await claim_next_execution_job(session)


async def find_stale_running_jobs(
    session: AsyncSession,
    stale_after: timedelta,
    *,
    now: datetime | None = None,
) -> list[ExecutionJob]:
    """Return running jobs older than the diagnostic staleness threshold.

    This function is intentionally read-only. Recovery and retry policy are
    deferred until a later queue/retry architecture is introduced.
    """
    if stale_after <= timedelta(0):
        raise ValueError("stale_after must be positive")
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - stale_after
    result = await session.scalars(
        select(ExecutionJob)
        .where(
            ExecutionJob.status == "running",
            ExecutionJob.started_at.is_not(None),
            ExecutionJob.started_at < cutoff,
        )
        .order_by(ExecutionJob.started_at.asc(), ExecutionJob.id.asc())
    )
    return list(result.all())
