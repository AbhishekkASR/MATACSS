"""Schema for isolated sandbox execution results."""

from typing import Literal

from pydantic import BaseModel, Field

ExecutionStatus = Literal[
    "queued",
    "running",
    "success",
    "compilation_error",
    "runtime_error",
    "timeout",
    "output_limit_exceeded",
    "sandbox_error",
]


class ExecutionResult(BaseModel):
    """Public execution outcome without Docker implementation details."""

    status: ExecutionStatus
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    execution_time_ms: float = Field(ge=0)
    timed_out: bool = False
