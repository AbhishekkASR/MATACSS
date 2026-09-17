"""Process queued execution jobs once and exit when the queue is empty."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.database import async_session_factory
from app.services.execution_worker import ExecutionWorker
from app.services.sandbox_service import DockerSandboxService


async def main() -> int:
    """Process all currently queued jobs."""
    worker = ExecutionWorker(
        DockerSandboxService(),
        poll_interval_seconds=settings.worker_poll_interval_seconds,
        batch_size=settings.worker_batch_size,
        max_concurrency=settings.worker_max_concurrency,
    )
    async with async_session_factory() as session:
        processed = await worker.run_until_idle(session)
    print(f"Processed {processed} execution job(s).")
    return 0


if __name__ == "__main__":
    asyncio.run(main())
