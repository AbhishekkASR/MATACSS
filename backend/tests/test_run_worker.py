"""Tests for the production execution worker entrypoint."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from scripts import run_worker


def test_main_runs_forever_with_config_and_shutdown_event(monkeypatch) -> None:
    settings = SimpleNamespace(
        worker_poll_interval_seconds=7,
        worker_batch_size=13,
        worker_max_concurrency=2,
    )
    worker = Mock()
    worker.run_forever = AsyncMock(return_value=4)
    worker_factory = Mock(return_value=worker)
    session_factory = Mock()

    monkeypatch.setattr(run_worker, "settings", settings)
    monkeypatch.setattr(run_worker, "configure_logging", Mock())
    monkeypatch.setattr(run_worker, "ExecutionWorker", worker_factory)
    monkeypatch.setattr(run_worker, "DockerSandboxService", Mock())
    monkeypatch.setattr(run_worker, "async_session_factory", session_factory)

    assert asyncio.run(run_worker.main()) == 0

    worker_factory.assert_called_once_with(
        run_worker.DockerSandboxService.return_value,
        poll_interval_seconds=7,
        batch_size=13,
        max_concurrency=2,
    )
    worker.run_forever.assert_awaited_once()
    args, kwargs = worker.run_forever.await_args
    assert args == (session_factory,)
    assert isinstance(kwargs["stop_event"], asyncio.Event)


def test_main_logs_unrecoverable_worker_errors(monkeypatch, caplog) -> None:
    worker = Mock()
    worker.run_forever = AsyncMock(side_effect=RuntimeError("worker failed"))
    monkeypatch.setattr(
        run_worker,
        "settings",
        SimpleNamespace(
            worker_poll_interval_seconds=5,
            worker_batch_size=10,
            worker_max_concurrency=1,
        ),
    )
    monkeypatch.setattr(run_worker, "configure_logging", Mock())
    monkeypatch.setattr(run_worker, "ExecutionWorker", Mock(return_value=worker))
    monkeypatch.setattr(run_worker, "DockerSandboxService", Mock())

    assert asyncio.run(run_worker.main()) == 1
    assert "Execution worker stopped after an unrecoverable error" in caplog.text
