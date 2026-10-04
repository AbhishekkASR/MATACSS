"""LiveCodeBench record decoder.

Decoding pipeline for private_test_cases:

    Base64  →  zlib decompress  →  pickle.loads (protocol 4)  →  JSON parse

Trust boundary
--------------
This decoder is used exclusively by the offline import script that reads a
pinned, SHA-256-verified local dataset file.  It MUST NOT be called from any
web-facing endpoint or from user-supplied data.  Pickle is inherently unsafe
with untrusted payloads; the safety here relies entirely on the verified source.

The import script verifies the dataset file hash before calling this module.
"""

from __future__ import annotations

import base64
import json
import pickle  # noqa: S403  — only used on verified local dataset; see module docstring
import zlib
from dataclasses import dataclass


# ── Public-test-case structure ────────────────────────────────────────────────

@dataclass(frozen=True)
class RawTestCase:
    """One decoded test case from either the public or private pool."""

    input: str
    output: str
    testtype: str  # "stdin" | "functional"
    is_sample: bool


# ── Decoder ───────────────────────────────────────────────────────────────────

class LiveCodeBenchDecodeError(Exception):
    """Raised when any stage of the private_test_cases decode pipeline fails."""


def decode_private_test_cases(encoded: str) -> list[RawTestCase]:
    """Decode the private_test_cases field of one LiveCodeBench record.

    Pipeline:
        1. Base64-decode the string.
        2. zlib-decompress (magic bytes 0x78 0x9C — NOT gzip).
        3. pickle.loads the bytes → yields a Python str.
        4. JSON-parse the str → yields a list of dicts.

    Returns a list of RawTestCase with is_sample=False.

    Raises LiveCodeBenchDecodeError on any failure.

    SECURITY: This function must only be called by the offline importer on a
    verified local dataset file.  Never expose it to user-supplied input.
    """
    try:
        raw_bytes = base64.b64decode(encoded)
    except Exception as exc:
        raise LiveCodeBenchDecodeError(f"Base64 decode failed: {exc}") from exc

    try:
        decompressed = zlib.decompress(raw_bytes)
    except zlib.error as exc:
        raise LiveCodeBenchDecodeError(f"zlib decompress failed: {exc}") from exc

    try:
        json_str = pickle.loads(decompressed)  # noqa: S301 — see module docstring
    except Exception as exc:
        raise LiveCodeBenchDecodeError(f"pickle.loads failed: {exc}") from exc

    if not isinstance(json_str, str):
        raise LiveCodeBenchDecodeError(
            f"pickle payload must be a str, got {type(json_str).__name__}"
        )

    try:
        cases_raw = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise LiveCodeBenchDecodeError(f"JSON parse of pickle payload failed: {exc}") from exc

    if not isinstance(cases_raw, list):
        raise LiveCodeBenchDecodeError(
            f"decoded test-case payload must be a list, got {type(cases_raw).__name__}"
        )

    result: list[RawTestCase] = []
    for i, item in enumerate(cases_raw):
        try:
            result.append(_parse_raw_tc(item, is_sample=False, index=i))
        except LiveCodeBenchDecodeError:
            raise
    return result


def decode_public_test_cases(json_string: str) -> list[RawTestCase]:
    """Decode the public_test_cases field (a JSON string) of one record.

    Returns a list of RawTestCase with is_sample=True.
    """
    try:
        cases_raw = json.loads(json_string)
    except json.JSONDecodeError as exc:
        raise LiveCodeBenchDecodeError(f"public_test_cases JSON parse failed: {exc}") from exc

    if not isinstance(cases_raw, list):
        raise LiveCodeBenchDecodeError(
            f"public_test_cases must be a JSON array, got {type(cases_raw).__name__}"
        )

    result: list[RawTestCase] = []
    for i, item in enumerate(cases_raw):
        result.append(_parse_raw_tc(item, is_sample=True, index=i))
    return result


def _parse_raw_tc(item: object, *, is_sample: bool, index: int) -> RawTestCase:
    if not isinstance(item, dict):
        raise LiveCodeBenchDecodeError(
            f"test case at index {index} must be a dict, got {type(item).__name__}"
        )
    for key in ("input", "output", "testtype"):
        if key not in item:
            raise LiveCodeBenchDecodeError(
                f"test case at index {index} missing required key '{key}'"
            )
    inp = item["input"]
    out = item["output"]
    tt = item["testtype"]
    if not isinstance(inp, str):
        raise LiveCodeBenchDecodeError(
            f"test case at index {index}: 'input' must be str, got {type(inp).__name__}"
        )
    if not isinstance(out, str):
        raise LiveCodeBenchDecodeError(
            f"test case at index {index}: 'output' must be str, got {type(out).__name__}"
        )
    # Validate UTF-8 safety
    try:
        out.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LiveCodeBenchDecodeError(
            f"test case at index {index}: 'output' is not valid UTF-8: {exc}"
        ) from exc
    return RawTestCase(input=inp, output=out, testtype=tt, is_sample=is_sample)
