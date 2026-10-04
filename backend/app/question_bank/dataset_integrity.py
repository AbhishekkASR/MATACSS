"""Integrity checks for the pinned LiveCodeBench source dataset."""

from __future__ import annotations

import hashlib
from pathlib import Path

EXPECTED_LIVECODEBENCH_SHA256 = (
    "BB4C364F71921C4495A6AD15ABE1A927350B720009F4933E2E71F8AF0F6FD1F5"
)
CHUNK_SIZE = 1 << 20


class DatasetIntegrityError(ValueError):
    """Raised when a LiveCodeBench file is not the pinned trusted dataset."""


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def verify_livecodebench_dataset(path: Path) -> None:
    """Reject files that do not match the pinned LiveCodeBench dataset hash."""
    if sha256_of_file(path) != EXPECTED_LIVECODEBENCH_SHA256:
        raise DatasetIntegrityError(
            "LiveCodeBench SHA-256 verification failed; import aborted."
        )
