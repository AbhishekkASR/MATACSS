"""Unit tests for the Docker sandbox service using mocked Docker objects."""

from types import SimpleNamespace
from threading import Event
from unittest.mock import Mock

from docker.errors import DockerException

from app.schemas.execution import ExecutionResult
from app.services.sandbox_service import DockerSandboxService, SandboxLimits


def make_service(
    exec_results: list[SimpleNamespace],
    output_limit_bytes: int = 64,
) -> tuple[DockerSandboxService, Mock, Mock]:
    container = Mock()
    container.id = "container-id"
    client = Mock()
    client.containers.create.return_value = container
    client.api.exec_create.return_value = {"Id": "exec-id"}
    client.api.exec_start.side_effect = [
        iter(result.output for result in exec_results)
    ]
    client.api.exec_inspect.return_value = {
        "ExitCode": exec_results[-1].exit_code
    }
    container.client = client
    service = DockerSandboxService(
        client=client,
        limits=SandboxLimits(
            timeout_seconds=1,
            memory_limit="64m",
            cpu_limit=0.25,
            pids_limit=16,
            output_limit_bytes=output_limit_bytes,
        ),
    )
    return service, client, container


def test_python_success_uses_restricted_container_and_cleans_up() -> None:
    service, client, container = make_service(
        [SimpleNamespace(exit_code=0, output=(b"hello\n", b""))]
    )

    result = service.execute("python", "print('hello')")

    assert result == ExecutionResult(
        status="success",
        stdout="hello\n",
        stderr="",
        exit_code=0,
        execution_time_ms=result.execution_time_ms,
        timed_out=False,
    )
    create_kwargs = client.containers.create.call_args.kwargs
    assert create_kwargs["network_disabled"] is True
    assert create_kwargs["mem_limit"] == "64m"
    assert create_kwargs["nano_cpus"] == 250_000_000
    assert create_kwargs["pids_limit"] == 16
    assert create_kwargs["user"] == "65532:65532"
    assert create_kwargs["read_only"] is True
    assert create_kwargs["tmpfs"] == {"/tmp": "rw,exec,nosuid,nodev,size=64m"}
    assert create_kwargs["cap_drop"] == ["ALL"]
    assert create_kwargs["security_opt"] == ["no-new-privileges:true"]
    assert create_kwargs["init"] is True
    assert create_kwargs["volumes"] == {}
    container.remove.assert_called_once_with(force=True)


def test_java_uses_available_runtime_image() -> None:
    assert (
        DockerSandboxService._RUNTIMES["java"].image
        == "eclipse-temurin:21-jdk"
    )


def test_compilation_error_does_not_run_program() -> None:
    service, _, container = make_service(
        [SimpleNamespace(exit_code=1, output=(b"", b"compile failed"))]
    )

    result = service.execute("cpp", "int main() {")

    assert result.status == "compilation_error"
    assert result.stderr == "compile failed"
    assert result.exit_code == 1
    assert container.client.api.exec_start.call_count == 1
    container.remove.assert_called_once_with(force=True)


def test_output_is_bounded() -> None:
    service, _, _ = make_service(
        [SimpleNamespace(exit_code=0, output=(b"0123456789", b"abcdefghij"))],
        output_limit_bytes=8,
    )

    result = service.execute("python", "print('output')")

    assert len(result.stdout.encode()) <= 8
    assert len(result.stderr.encode()) <= 8


def test_output_limit_terminates_capture_at_limit() -> None:
    service, client, container = make_service(
        [SimpleNamespace(exit_code=0, output=(b"0123456789", b""))],
        output_limit_bytes=8,
    )

    result = service.execute("python", "print('output')")

    assert result.status == "output_limit_exceeded"
    assert result.stderr.startswith("Output l")
    assert len(result.stderr.encode()) <= 8
    assert client.api.exec_start.call_args.kwargs == {
        "stream": True,
        "demux": True,
    }
    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)


def test_timeout_terminates_execution_and_cleanup() -> None:
    stopped = Event()
    container = Mock()
    container.id = "container-id"
    container.kill.side_effect = stopped.set
    client = Mock()
    client.containers.create.return_value = container
    container.client = client
    client.api.exec_create.return_value = {"Id": "exec-id"}

    def blocking_stream(*args, **kwargs):
        while not stopped.is_set():
            stopped.wait(0.01)
        return iter(())

    client.api.exec_start.side_effect = blocking_stream
    client.api.exec_inspect.return_value = {"ExitCode": -9}
    service = DockerSandboxService(
        client=client,
        limits=SandboxLimits(timeout_seconds=0.05),
    )

    result = service.execute("python", "while True: pass")

    assert result.status == "timeout"
    assert result.timed_out is True
    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)


def test_docker_failure_returns_sanitized_sandbox_error() -> None:
    client = Mock()
    client.containers.create.side_effect = DockerException("private docker detail")
    service = DockerSandboxService(client=client)

    result = service.execute("python", "print('hello')")

    assert result.status == "sandbox_error"
    assert result.stderr == "Sandbox execution failed."
    assert "private docker detail" not in result.stderr
