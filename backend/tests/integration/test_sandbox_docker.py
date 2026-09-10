"""Real Docker integration tests for the sandbox service.

Run explicitly with:
    python -m pytest tests/integration/test_sandbox_docker.py -m docker
"""

import docker
import pytest
from docker.errors import DockerException

from app.services.sandbox_service import DockerSandboxService

pytestmark = pytest.mark.docker


class RecordingContainers:
    def __init__(self, containers):
        self._containers = containers
        self.last_create_kwargs = {}
        self.last_container = None

    def create(self, **kwargs):
        self.last_create_kwargs = kwargs
        self.last_container = self._containers.create(**kwargs)
        return self.last_container


class RecordingClient:
    def __init__(self, client):
        self._client = client
        self.containers = RecordingContainers(client.containers)

    def ping(self):
        return self._client.ping()


@pytest.fixture(scope="module")
def sandbox() -> DockerSandboxService:
    try:
        client = docker.from_env()
        client.ping()
    except DockerException as exc:
        pytest.skip(f"Docker is unavailable: {exc}")
    return DockerSandboxService(client=RecordingClient(client))


def test_python_success(sandbox: DockerSandboxService) -> None:
    result = sandbox.execute("python", "print('hello')")
    assert result.status == "success"
    assert result.stdout.strip() == "hello"


def test_python_runtime_error(sandbox: DockerSandboxService) -> None:
    result = sandbox.execute("python", "raise RuntimeError('boom')")
    assert result.status == "runtime_error"
    assert "RuntimeError" in result.stderr


def test_python_timeout(sandbox: DockerSandboxService) -> None:
    result = sandbox.execute("python", "while True: pass")
    assert result.status == "timeout"
    assert result.timed_out is True


def test_output_limit(sandbox: DockerSandboxService) -> None:
    result = sandbox.execute("python", "print('x' * 100000)")
    assert result.status == "output_limit_exceeded"
    assert len(result.stdout.encode()) <= sandbox.limits.output_limit_bytes


def test_cpp_success(sandbox: DockerSandboxService) -> None:
    result = sandbox.execute("cpp", '#include <iostream>\nint main(){std::cout<<"ok";}')
    assert result.status == "success"
    assert result.stdout.strip() == "ok"


def test_cpp_compilation_error(sandbox: DockerSandboxService) -> None:
    result = sandbox.execute("cpp", "int main() {")
    assert result.status == "compilation_error"


def test_java_success(sandbox: DockerSandboxService) -> None:
    source = "public class Main { public static void main(String[] args) { System.out.print(\"ok\"); } }"
    result = sandbox.execute("java", source)
    assert result.status == "success"
    assert result.stdout.strip() == "ok"


def test_java_compilation_error(sandbox: DockerSandboxService) -> None:
    result = sandbox.execute("java", "public class Main {")
    assert result.status == "compilation_error"


def test_container_cleanup_and_controls(sandbox: DockerSandboxService) -> None:
    result = sandbox.execute("python", "print('controls')")
    assert result.status == "success"
    options = sandbox.client.containers.last_create_kwargs
    assert options["network_disabled"] is True
    assert options["user"] == "65532:65532"
    assert options["mem_limit"] == sandbox.limits.memory_limit
    assert options["nano_cpus"] == sandbox.limits.nano_cpus
    assert options["pids_limit"] == sandbox.limits.pids_limit
    assert options["read_only"] is True
    assert options["cap_drop"] == ["ALL"]
    assert options["security_opt"] == ["no-new-privileges:true"]
    assert options["init"] is True
    assert options["volumes"] == {}
    assert options["tmpfs"] == {"/tmp": "rw,exec,nosuid,nodev,size=64m"}
    with pytest.raises(docker.errors.NotFound):
        sandbox.client._client.containers.get(
            sandbox.client.containers.last_container.id
        )


def test_source_and_stdin_metacharacters_are_not_commands(
    sandbox: DockerSandboxService,
) -> None:
    result = sandbox.execute(
        "python",
        "print('source ; touch /tmp/should-not-run')",
        stdin="; rm -rf /; $(id)",
    )
    assert result.status == "success"
    assert "source ; touch /tmp/should-not-run" in result.stdout


def test_network_access_is_blocked(sandbox: DockerSandboxService) -> None:
    result = sandbox.execute(
        "python",
        (
            "import socket\n"
            "socket.setdefaulttimeout(1)\n"
            "socket.create_connection(('1.1.1.1', 80))\n"
        ),
    )
    assert result.status in {"runtime_error", "timeout"}
    assert result.status != "success"


def test_privilege_and_host_socket_access_are_not_available(
    sandbox: DockerSandboxService,
) -> None:
    result = sandbox.execute(
        "python",
        (
            "import os\n"
            "assert os.geteuid() != 0\n"
            "assert not os.path.exists('/var/run/docker.sock')\n"
            "print('restricted')\n"
        ),
    )
    assert result.status == "success"
    assert result.stdout.strip() == "restricted"


def test_read_only_root_and_tmpfs_boundary(
    sandbox: DockerSandboxService,
) -> None:
    result = sandbox.execute(
        "python",
        (
            "from pathlib import Path\n"
            "Path('/etc/matacss-write-test').write_text('blocked')\n"
        ),
    )
    assert result.status == "runtime_error"
    assert "Read-only file system" in result.stderr or "Permission denied" in result.stderr


def test_pid_limit_blocks_unbounded_child_creation(
    sandbox: DockerSandboxService,
) -> None:
    result = sandbox.execute(
        "python",
        (
            "import subprocess\n"
            "children=[]\n"
            "for _ in range(128):\n"
            "    try: children.append(subprocess.Popen(['sleep', '2']))\n"
            "    except OSError: break\n"
            "print(len(children))\n"
            "[child.terminate() for child in children]\n"
        ),
    )
    assert result.status in {"success", "runtime_error"}
    if result.status == "success":
        assert int(result.stdout.strip()) < 128


def test_memory_abuse_is_contained(sandbox: DockerSandboxService) -> None:
    result = sandbox.execute(
        "python",
        "data = bytearray(256 * 1024 * 1024)\nprint(len(data))",
    )
    assert result.status in {"runtime_error", "sandbox_error", "timeout"}
    assert result.status != "success"


@pytest.mark.parametrize(
    "language,source",
    [
        ("python", "raise RuntimeError('cleanup')"),
        ("cpp", "int main() {"),
        ("python", "while True: pass"),
    ],
)
def test_container_cleanup_after_terminal_failures(
    sandbox: DockerSandboxService, language: str, source: str
) -> None:
    result = sandbox.execute(language, source)
    assert result.status in {
        "runtime_error",
        "compilation_error",
        "timeout",
    }
    with pytest.raises(docker.errors.NotFound):
        sandbox.client._client.containers.get(
            sandbox.client.containers.last_container.id
        )
