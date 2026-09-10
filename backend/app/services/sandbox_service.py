"""Docker-backed isolated execution service."""

from __future__ import annotations

import time
from dataclasses import dataclass
import logging
from queue import Empty, Queue
from threading import Thread
from typing import Any

import docker
from docker.errors import DockerException

from app.core.config import settings
from app.schemas.execution import ExecutionResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SandboxLimits:
    """Resource and output limits applied to every sandbox container."""

    timeout_seconds: float = settings.sandbox_timeout_seconds
    memory_limit: str = settings.sandbox_memory_limit
    cpu_limit: float = settings.sandbox_cpu_limit
    pids_limit: int = settings.sandbox_pids_limit
    output_limit_bytes: int = settings.sandbox_output_limit_bytes

    @property
    def nano_cpus(self) -> int:
        return int(self.cpu_limit * 1_000_000_000)


@dataclass(frozen=True)
class LanguageRuntime:
    """Container image and argument vectors for one supported language."""

    image: str
    source_path: str
    compile_command: tuple[str, ...] | None
    run_command: tuple[str, ...]


class DockerSandboxService:
    """Execute untrusted source code in short-lived restricted containers."""

    _USER = "65532:65532"
    _WORKING_DIRECTORY = "/tmp"
    _RUNTIMES = {
        "python": LanguageRuntime(
            settings.sandbox_python_image,
            "/tmp/main.py",
            None,
            ("python", "/tmp/main.py"),
        ),
        "cpp": LanguageRuntime(
            settings.sandbox_cpp_image,
            "/tmp/main.cpp",
            ("g++", "-std=c++17", "-O2", "-o", "/tmp/program", "/tmp/main.cpp"),
            ("/tmp/program",),
        ),
        "java": LanguageRuntime(
            settings.sandbox_java_image,
            "/tmp/Main.java",
            ("javac", "/tmp/Main.java"),
            ("java", "-cp", "/tmp", "Main"),
        ),
    }

    def __init__(
        self,
        client: Any | None = None,
        limits: SandboxLimits | None = None,
    ) -> None:
        self.client = client or docker.from_env()
        self.limits = limits or SandboxLimits()

    def execute(
        self,
        language: str,
        source_code: str,
        stdin: str = "",
    ) -> ExecutionResult:
        """Execute source code and return a sanitized, bounded result."""
        runtime = self._RUNTIMES.get(language)
        if runtime is None:
            return self._sandbox_error()

        container = None
        started_at = time.perf_counter()
        try:
            container = self.client.containers.create(
                image=runtime.image,
                command=("tail", "-f", "/dev/null"),
                working_dir=self._WORKING_DIRECTORY,
                user=self._USER,
                network_disabled=True,
                mem_limit=self.limits.memory_limit,
                nano_cpus=self.limits.nano_cpus,
                pids_limit=self.limits.pids_limit,
                read_only=True,
                tmpfs={"/tmp": "rw,exec,nosuid,nodev,size=64m"},
                security_opt=["no-new-privileges:true"],
                cap_drop=["ALL"],
                init=True,
                volumes={},
                stdin_open=True,
                auto_remove=False,
            )
            container.start()
            self._write_source(container, runtime.source_path, source_code)
            self._write_source(container, "/tmp/stdin", stdin)

            if runtime.compile_command is not None:
                compilation = self._run_command(container, runtime.compile_command)
                if compilation.timed_out:
                    return self._with_duration(compilation, started_at)
                if compilation.exit_code != 0:
                    return self._result(
                        "compilation_error",
                        compilation.stdout,
                        compilation.stderr,
                        compilation.exit_code,
                        False,
                        started_at,
                    )

            execution = self._run_command(container, runtime.run_command)
            if execution.status != "success":
                return self._with_duration(execution, started_at)
            status = "success" if execution.exit_code == 0 else "runtime_error"
            return self._result(
                status,
                execution.stdout,
                execution.stderr,
                execution.exit_code,
                execution.timed_out,
                started_at,
            )
        except (DockerException, OSError, ValueError):
            logger.exception("Sandbox execution failed during container execution")
            return self._sandbox_error(started_at)
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except DockerException:
                    pass

    def _write_source(self, container: Any, path: str, source_code: str) -> None:
        """Write source through the Docker API, never through a host shell."""
        filename = path.rsplit("/", maxsplit=1)[-1]
        payload = source_code.encode("utf-8")
        connection = container.exec_run(
            ("sh", "-c", f"cat > /tmp/{filename}"),
            stdin=True,
            socket=True,
            user=self._USER,
        ).output
        connection.sendall(payload)
        connection.close()

    def _run_command(
        self,
        container: Any,
        command: tuple[str, ...],
    ) -> ExecutionResult:
        started_at = time.perf_counter()
        # The command and redirection target are fixed runtime values, never
        # derived from candidate source, stdin, or other request data.
        command_with_stdin = (
            "sh",
            "-c",
            f"{' '.join(command)} < /tmp/stdin",
        )

        result_queue: Queue[ExecutionResult] = Queue(maxsize=1)

        def run() -> None:
            try:
                result_queue.put(
                    self._stream_command(container, command_with_stdin, started_at)
                )
            except (DockerException, OSError, ValueError):
                logger.exception("Sandbox execution failed while running command")
                result_queue.put(self._sandbox_error(started_at))

        worker = Thread(target=run, daemon=True)
        worker.start()
        worker.join(self.limits.timeout_seconds)
        if worker.is_alive():
            self._terminate_container(container)
            worker.join(self._timeout_join_seconds)
            return self._result(
                "timeout", "", "execution timed out", None, True, started_at
            )
        try:
            return result_queue.get_nowait()
        except Empty:
            return self._sandbox_error(started_at)

    def _stream_command(
        self,
        container: Any,
        command: tuple[str, ...],
        started_at: float,
    ) -> ExecutionResult:
        stdout = bytearray()
        stderr = bytearray()
        captured = 0
        exec_id = container.client.api.exec_create(
            container.id,
            command,
            stdin=False,
            tty=False,
        )["Id"]
        result = container.client.api.exec_start(exec_id, stream=True, demux=True)
        for chunk in result:
            out_chunk, err_chunk = chunk if isinstance(chunk, tuple) else (chunk, b"")
            for target, value in ((stdout, out_chunk), (stderr, err_chunk)):
                if value:
                    remaining = self.limits.output_limit_bytes - captured
                    if remaining <= 0:
                        self._terminate_container(container)
                        return self._result(
                            "output_limit_exceeded",
                            bytes(stdout),
                            "Output limit exceeded.",
                            None,
                            False,
                            started_at,
                        )
                    bounded = bytes(value)[:remaining]
                    target.extend(bounded)
                    captured += len(bounded)
                    if len(bounded) < len(value):
                        self._terminate_container(container)
                        return self._result(
                            "output_limit_exceeded",
                            bytes(stdout),
                            "Output limit exceeded.",
                            None,
                            False,
                            started_at,
                        )
        exit_code = container.client.api.exec_inspect(exec_id)["ExitCode"]
        return self._result(
            "success",
            bytes(stdout),
            bytes(stderr),
            exit_code,
            False,
            started_at,
        )

    @property
    def _timeout_join_seconds(self) -> float:
        return min(1.0, max(0.1, self.limits.timeout_seconds))

    def _terminate_container(self, container: Any) -> None:
        try:
            container.kill()
        except DockerException:
            pass

    def _decode_and_limit(self, output: Any) -> str:
        if output is None:
            return ""
        if isinstance(output, str):
            text = output
        else:
            text = bytes(output).decode("utf-8", errors="replace")
        encoded = text.encode("utf-8")
        if len(encoded) > self.limits.output_limit_bytes:
            return encoded[: self.limits.output_limit_bytes].decode(
                "utf-8", errors="replace"
            )
        return text

    def _result(
        self,
        status: str,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        timed_out: bool,
        started_at: float,
    ) -> ExecutionResult:
        return ExecutionResult(
            status=status,
            stdout=self._decode_and_limit(stdout),
            stderr=self._decode_and_limit(stderr),
            exit_code=exit_code,
            execution_time_ms=round((time.perf_counter() - started_at) * 1000, 2),
            timed_out=timed_out,
        )

    def _with_duration(
        self, result: ExecutionResult, started_at: float
    ) -> ExecutionResult:
        return result.model_copy(
            update={
                "execution_time_ms": round(
                    (time.perf_counter() - started_at) * 1000, 2
                )
            }
        )

    def _sandbox_error(self, started_at: float | None = None) -> ExecutionResult:
        start = started_at or time.perf_counter()
        return self._result(
            "sandbox_error",
            "",
            "Sandbox execution failed.",
            None,
            False,
            start,
        )