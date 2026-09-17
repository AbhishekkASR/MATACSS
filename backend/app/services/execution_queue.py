"""Durable queue operations for execution jobs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExecutionJob, Submission
from app.services.database_service import claim_next_execution_job

logger = logging.getLogger(__name__)


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
    """Return running jobs older than the diagnostic staleness threshold."""
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


async def mark_stale_running_jobs(
    session: AsyncSession,
    stale_after: timedelta,
    *,
    now: datetime | None = None,
    reason: str | None = None,
) -> list[ExecutionJob]:
    """Mark stale running jobs as failed without retrying them.

    This is a safe recovery hook for workers that lose their lease or crash
    while still holding a `running` job record. The detection is intentionally
    explicit and read/write-safe rather than silently rescheduling work.
    """
    if stale_after <= timedelta(0):
        raise ValueError("stale_after must be positive")
    current_time = now or datetime.now(timezone.utc)
    stale_jobs = await find_stale_running_jobs(session, stale_after, now=current_time)
    if not stale_jobs:
        return []

    default_reason = (
        "Execution job exceeded the allowed runtime window and was marked failed."
    )
    failure_message = reason or default_reason
    for job in stale_jobs:
        submission = await session.get(Submission, job.submission_id)
        if submission is not None:
            submission.status = "sandbox_error"
            submission.stderr = failure_message
            submission.stdout = submission.stdout or ""
            submission.exit_code = None
            submission.timed_out = False
        job.status = "failed"
        job.error_message = failure_message
        job.completed_at = current_time
        logger.warning(
            "Marked stale execution job as failed",
            extra={
                "job_id": str(job.id),
                "submission_id": str(job.submission_id),
                "reason": failure_message,
            },
        )

    await session.commit()
    return stale_jobs
