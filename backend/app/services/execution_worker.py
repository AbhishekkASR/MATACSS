"""Local durable worker for queued code execution jobs."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from docker.errors import DockerException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ExecutionJob, Submission
from app.services.execution_queue import claim_next_job
from app.services.sandbox_service import DockerSandboxService


class ExecutionWorker:
    """Process durable execution jobs without owning a long-running process."""

    def __init__(self, sandbox_service: DockerSandboxService) -> None:
        self.sandbox_service = sandbox_service

    async def process_next_job(self, session: AsyncSession) -> bool:
        """Claim and process one queued job, returning whether work was found."""
        claimed = await claim_next_job(session)
        if claimed is None:
            return False
        submission, job = claimed
        await self._execute_and_persist(session, submission, job)
        return True

    async def process_available_jobs(
        self, session: AsyncSession, max_jobs: int | None = None
    ) -> int:
        """Process queued jobs until the queue is empty or the bound is reached."""
        if max_jobs is not None and max_jobs < 1:
            raise ValueError("max_jobs must be positive")
        processed = 0
        while max_jobs is None or processed < max_jobs:
            if not await self.process_next_job(session):
                break
            processed += 1
        return processed

    async def _execute_and_persist(
        self, session: AsyncSession, submission: Submission, job
    ) -> None:
        """Execute through the sandbox and persist one terminal job state."""
        try:
            result = await asyncio.to_thread(
                self.sandbox_service.execute,
                language=submission.language,
                source_code=submission.source_code,
                stdin=submission.stdin,
            )
            submission.status = result.status
            submission.stdout = result.stdout
            submission.stderr = result.stderr
            submission.exit_code = result.exit_code
            submission.execution_time_ms = result.execution_time_ms
            submission.timed_out = result.timed_out
            job.status = "succeeded"
            job.completed_at = datetime.now(timezone.utc)
            await session.commit()
        except DockerException:
            await self._persist_failure(
                session, job.id, "Sandbox execution failed."
            )
        except Exception:
            await self._persist_failure(session, job.id, "Execution worker failed.")

    async def _persist_failure(
        self, session: AsyncSession, job_id, error_message: str
    ) -> None:
        await session.rollback()
        job = await session.get(ExecutionJob, job_id)
        if job is None:
            return
        submission = await session.get(Submission, job.submission_id)
        if submission is not None:
            submission.status = "sandbox_error"
            submission.stdout = ""
            submission.stderr = "Sandbox execution failed."
            submission.exit_code = None
            submission.timed_out = False
        job.status = "failed"
        job.error_message = error_message
        job.completed_at = datetime.now(timezone.utc)
        await session.commit()


async def process_next_execution_job(
    session: AsyncSession, sandbox_service: DockerSandboxService
) -> bool:
    """Backward-compatible function wrapper for the reusable worker."""
    return await ExecutionWorker(sandbox_service).process_next_job(session)
