"""Run the execution worker continuously until the process is stopped."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.database import async_session_factory
from app.services.execution_worker import ExecutionWorker
from app.services.sandbox_service import DockerSandboxService

logger = logging.getLogger(__name__)


def _install_shutdown_handlers(
    loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event
) -> dict[signal.Signals, object]:
    """Arrange for termination signals to request a graceful worker stop."""
    previous_handlers: dict[signal.Signals, object] = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(
                sig,
                lambda _signum, _frame, event=stop_event, event_loop=loop: (
                    event_loop.call_soon_threadsafe(event.set)
                ),
            )
    return previous_handlers


def _restore_shutdown_handlers(
    loop: asyncio.AbstractEventLoop,
    previous_handlers: dict[signal.Signals, object],
) -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.remove_signal_handler(sig)
        except (NotImplementedError, RuntimeError):
            pass
        if sig in previous_handlers:
            signal.signal(sig, previous_handlers[sig])


async def main() -> int:
    """Run queued execution jobs continuously until shutdown is requested."""
    configure_logging(settings)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    previous_handlers = _install_shutdown_handlers(loop, stop_event)
    logger.info("Execution worker starting", extra={"event": "worker_starting"})
    try:
        worker = ExecutionWorker(
            DockerSandboxService(),
            poll_interval_seconds=settings.worker_poll_interval_seconds,
            batch_size=settings.worker_batch_size,
            max_concurrency=settings.worker_max_concurrency,
        )
        processed = await worker.run_forever(
            async_session_factory,
            stop_event=stop_event,
        )
    except Exception:
        logger.exception(
            "Execution worker stopped after an unrecoverable error",
            extra={"event": "worker_error"},
        )
        return 1
    finally:
        _restore_shutdown_handlers(loop, previous_handlers)
    logger.info(
        "Execution worker stopped",
        extra={"event": "worker_stopped", "processed_jobs": processed},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
