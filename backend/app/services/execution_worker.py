"""Local durable worker for queued code execution jobs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from docker.errors import DockerException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_correlation_id, reset_correlation_id, set_correlation_id
from app.models import ExecutionJob, Submission
from app.services.execution_queue import claim_next_job, mark_stale_running_jobs
from app.services.sandbox_service import DockerSandboxService

logger = logging.getLogger(__name__)


class ExecutionWorker:
    """Process durable execution jobs with bounded lifecycle controls."""

    def __init__(
        self,
        sandbox_service: DockerSandboxService,
        *,
        poll_interval_seconds: float = 5.0,
        batch_size: int = 10,
        max_concurrency: int = 1,
        stale_after: timedelta | None = None,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        self.sandbox_service = sandbox_service
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.batch_size = max(1, int(batch_size))
        self.max_concurrency = max(1, int(max_concurrency))
        self.stale_after = stale_after or timedelta(minutes=10)
        self.stop_event = stop_event or asyncio.Event()

    @property
    def is_stopped(self) -> bool:
        return self.stop_event.is_set()

    async def stop(self) -> None:
        """Request a graceful exit for the worker loop."""
        self.stop_event.set()

    async def start(self) -> None:
        """Compatibility alias for graceful worker startup."""
        self.stop_event.clear()

    async def process_next_job(self, session: AsyncSession) -> bool:
        """Claim and process one queued job, returning whether work was found."""
        try:
            claimed = await claim_next_job(session)
        except Exception:
            logger.exception(
                "Execution worker failed while claiming the next job",
                extra={"event": "job_claim_error"},
            )
            return False
        if claimed is None:
            return False
        submission, job = claimed
        token = set_correlation_id(f"job:{job.id}")
        try:
            logger.info(
                "Execution job started",
                extra={
                    "event": "job_started",
                    "job_id": str(job.id),
                    "submission_id": str(submission.id),
                },
            )
            await self._execute_and_persist(session, submission, job)
            logger.info(
                "Execution job completed",
                extra={
                    "event": "job_completed",
                    "job_id": str(job.id),
                    "submission_id": str(submission.id),
                    "status": job.status,
                },
            )
            return True
        finally:
            reset_correlation_id(token)

    async def process_available_jobs(
        self, session: AsyncSession, max_jobs: int | None = None
    ) -> int:
        """Process queued jobs until the queue is empty or the bound is reached."""
        limit = self.batch_size if max_jobs is None else max_jobs
        if limit < 1:
            raise ValueError("max_jobs must be positive")
        processed = 0
        while processed < limit:
            if not await self.process_next_job(session):
                break
            processed += 1
        return processed

    async def run(
        self,
        session: AsyncSession,
        *,
        max_jobs: int | None = None,
        max_iterations: int | None = None,
    ) -> int:
        """Run the worker until the queue is empty or the loop bound is reached."""
        return await self.run_until_idle(
            session,
            max_jobs=max_jobs,
            max_iterations=max_iterations,
        )

    async def run_until_idle(
        self,
        session: AsyncSession,
        *,
        max_jobs: int | None = None,
        max_iterations: int | None = None,
    ) -> int:
        """Run the worker until the queue is empty or the loop bound is reached."""
        processed = 0
        iterations = 0
        limit = self.batch_size if max_jobs is None else max_jobs
        while not self.is_stopped:
            iterations += 1
            await mark_stale_running_jobs(session, self.stale_after)
            processed_now = await self.process_available_jobs(session, max_jobs=limit)
            processed += processed_now
            if max_iterations is not None and iterations >= max_iterations:
                break
            if processed_now == 0:
                break
        return processed

    async def run_forever(
        self,
        session_factory: Callable[[], AsyncSession] | Callable[[], Awaitable[AsyncSession]],
        *,
        stop_event: asyncio.Event | None = None,
        max_iterations: int | None = None,
        poll_interval_seconds: float | None = None,
        batch_size: int | None = None,
    ) -> int:
        """Run a bounded worker loop until shutdown or the queue becomes idle."""
        if stop_event is not None:
            self.stop_event = stop_event
        effective_poll = (
            self.poll_interval_seconds
            if poll_interval_seconds is None
            else float(poll_interval_seconds)
        )
        effective_batch = self.batch_size if batch_size is None else max(1, int(batch_size))
        total_processed = 0
        iterations = 0

        while not self.is_stopped:
            if max_iterations is not None and iterations >= max_iterations:
                break
            iterations += 1
            factory_result = session_factory()
            if asyncio.iscoroutine(factory_result):
                session = await factory_result
            else:
                session = factory_result
            async with session as active_session:
                await mark_stale_running_jobs(active_session, self.stale_after)
                processed_now = await self.process_available_jobs(
                    active_session, max_jobs=effective_batch
                )
                total_processed += processed_now
            if processed_now == 0:
                await asyncio.sleep(effective_poll)
            if max_iterations is not None and iterations >= max_iterations:
                break
        return total_processed

    async def _execute_and_persist(
        self, session: AsyncSession, submission: Submission, job: ExecutionJob
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
            logger.warning(
                "Sandbox execution failed for job",
                extra={"event": "sandbox_failure", "job_id": str(job.id), "submission_id": str(submission.id)},
            )
            await self._persist_failure(
                session, job.id, "Sandbox execution failed."
            )
        except Exception:
            logger.exception(
                "Execution worker failed while processing a job",
                extra={"event": "job_processing_error", "job_id": str(job.id), "submission_id": str(submission.id)},
            )
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
            submission.stderr = error_message
            submission.exit_code = None
            submission.timed_out = False
        job.status = "failed"
        job.error_message = error_message
        job.completed_at = datetime.now(timezone.utc)
        await session.commit()
        logger.warning(
            "Execution job failed and was persisted",
            extra={
                "event": "job_failed",
                "job_id": str(job.id),
                "submission_id": str(job.submission_id),
                "error": error_message,
            },
        )


async def process_next_execution_job(
    session: AsyncSession, sandbox_service: DockerSandboxService
) -> bool:
    """Backward-compatible function wrapper for the reusable worker."""
    return await ExecutionWorker(sandbox_service).process_next_job(session)
