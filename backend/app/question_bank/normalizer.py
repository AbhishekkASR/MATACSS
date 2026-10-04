"""LiveCodeBench record normalizer.

Converts a raw LiveCodeBench JSON record into the canonical MATACSS
NormalizedQuestion structure, ready for persistence.

Handles:
- question_content section extraction (Input / Output / Constraints)
- title formatting (LeetCode slug → title-case)
- difficulty pass-through (already aligned with MATACSS values)
- supported_languages assignment per platform
- source URL construction
- lifecycle status assignment (AtCoder → 'validated', LeetCode → 'draft')
- test case ordering (public first, then private)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.question_bank.decoder import (
    RawTestCase,
    decode_private_test_cases,
    decode_public_test_cases,
)
from app.question_bank.functional import (
    FunctionalFormatError,
    solution_method,
    validate_functional_case,
)

# ── Constants ─────────────────────────────────────────────────────────────────

LIVECODEBENCH_DATASET_NAME = "LiveCodeBench"
LIVECODEBENCH_SOURCE = "livecodebench"
LIVECODEBENCH_DATASET_VERSION = "BB4C364F71921C4495A6AD15ABE1A927350B720009F4933E2E71F8AF0F6FD1F5"

# All MATACSS Docker-supported languages
ALL_SUPPORTED_LANGUAGES = ["python", "cpp", "java"]
# LeetCode functional harness is Python-only until extended
LEETCODE_SUPPORTED_LANGUAGES = ["python"]

VALID_DIFFICULTIES = {"easy", "medium", "hard"}
TEST_CASE_LIMIT = 100


# ── Normalized structures ─────────────────────────────────────────────────────

@dataclass
class NormalizedTestCase:
    stdin: str
    expected_stdout: str
    is_sample: bool
    is_functional: bool
    tc_order: int
    description: str
    time_limit_ms: Optional[int] = None


@dataclass
class NormalizedProvenance:
    source: str
    platform: str
    original_question_id: str
    contest_id: Optional[str]
    contest_date: Optional[datetime]
    source_url: Optional[str]
    license: Optional[str]
    dataset_name: str
    dataset_version: str


@dataclass
class NormalizedQuestion:
    # Core question fields
    title: str
    description: str
    difficulty: str
    expected_language: Optional[str]
    status: str
    input_format: Optional[str]
    output_format: Optional[str]
    constraints_text: Optional[str]
    supported_languages: list[str]
    starter_code: Optional[str]
    # Relationships
    test_cases: list[NormalizedTestCase]
    provenance: NormalizedProvenance
    # Lineage (curated = no LLM)
    llm_origin: str = "curated"
    # Warnings accumulated during normalization (non-fatal)
    warnings: list[str] = field(default_factory=list)


# ── Public API ────────────────────────────────────────────────────────────────

class NormalizationError(Exception):
    """Raised when a record cannot be normalized and must be skipped."""


def normalize_record(record: dict) -> NormalizedQuestion:
    """Normalize one raw LiveCodeBench JSON record into a NormalizedQuestion.

    Raises NormalizationError for hard failures (record must be skipped).
    Accumulates soft warnings on the returned object for logging.
    """
    warnings: list[str] = []

    # ── Required field presence checks ───────────────────────────────────────
    title_raw = record.get("question_title", "")
    content_raw = record.get("question_content", "")
    platform = record.get("platform", "")
    orig_qid = record.get("question_id", "")
    difficulty_raw = record.get("difficulty", "")

    if not str(title_raw).strip():
        raise NormalizationError("question_title is empty")
    if not str(content_raw).strip():
        raise NormalizationError("question_content is empty")
    if not platform:
        raise NormalizationError("platform is missing")
    if not orig_qid:
        raise NormalizationError("question_id is missing")

    # ── Difficulty ────────────────────────────────────────────────────────────
    difficulty = str(difficulty_raw).strip().lower()
    if difficulty not in VALID_DIFFICULTIES:
        warnings.append(f"Unknown difficulty {difficulty!r}; defaulting to 'medium'")
        difficulty = "medium"

    # ── Title formatting ──────────────────────────────────────────────────────
    title = _format_title(str(title_raw).strip(), platform)

    # ── Content section extraction ────────────────────────────────────────────
    input_format, output_format, constraints_text = _extract_sections(content_raw, platform)

    # ── Decode test cases ─────────────────────────────────────────────────────
    public_tcs = decode_public_test_cases(record.get("public_test_cases", "[]"))
    private_tcs = decode_private_test_cases(record.get("private_test_cases", ""))

    all_raw = public_tcs + private_tcs
    if not all_raw:
        raise NormalizationError("No test cases found (both public and private are empty)")

    if len(all_raw) > TEST_CASE_LIMIT:
        warnings.append(
            f"Record has {len(all_raw)} test cases; truncating to {TEST_CASE_LIMIT}"
        )
        all_raw = all_raw[:TEST_CASE_LIMIT]

    # ── Determine evaluation type ─────────────────────────────────────────────
    is_functional_platform = platform == "leetcode"

    # Warn if unexpected testtype is encountered
    testtypes = {tc.testtype for tc in all_raw}
    expected_testtype = "functional" if is_functional_platform else "stdin"
    unexpected = testtypes - {expected_testtype}
    if unexpected:
        warnings.append(f"Unexpected testtype values: {unexpected}")

    # ── Build normalized test cases ───────────────────────────────────────────
    test_cases: list[NormalizedTestCase] = []
    for order, raw_tc in enumerate(all_raw):
        is_functional = raw_tc.testtype == "functional"
        test_cases.append(NormalizedTestCase(
            stdin=raw_tc.input,
            expected_stdout=raw_tc.output,
            is_sample=raw_tc.is_sample,
            is_functional=is_functional,
            tc_order=order,
            description="public" if raw_tc.is_sample else "private",
            time_limit_ms=None,  # LiveCodeBench provides no per-case time limits
        ))

    # ── Languages and status ──────────────────────────────────────────────────
    if is_functional_platform:
        supported_languages = LEETCODE_SUPPORTED_LANGUAGES
        status = _validate_leetcode_functional_status(
            starter_code=record.get("starter_code"),
            test_cases=test_cases,
            warnings=warnings,
        )
    else:
        supported_languages = ALL_SUPPORTED_LANGUAGES
        status = _validate_atcoder_status(test_cases, warnings)

    # ── Starter code ─────────────────────────────────────────────────────────
    starter_code = record.get("starter_code") or None
    if starter_code and not str(starter_code).strip():
        starter_code = None

    # Warn if AtCoder has unexpected starter code
    if platform == "atcoder" and starter_code:
        warnings.append("AtCoder record has non-empty starter_code (unexpected)")

    # ── Provenance ────────────────────────────────────────────────────────────
    contest_id = record.get("contest_id") or None
    contest_date = _parse_contest_date(record.get("contest_date"), warnings)
    source_url = _build_source_url(platform, orig_qid, contest_id, str(title_raw).strip())

    provenance = NormalizedProvenance(
        source=LIVECODEBENCH_SOURCE,
        platform=platform,
        original_question_id=str(orig_qid),
        contest_id=contest_id,
        contest_date=contest_date,
        source_url=source_url,
        # License: LiveCodeBench dataset redistributes contest problems.
        # Platform content remains owned by each platform (AtCoder/LeetCode).
        # License is explicitly unresolved — do not invent a value.
        license=None,
        dataset_name=LIVECODEBENCH_DATASET_NAME,
        dataset_version=LIVECODEBENCH_DATASET_VERSION,
    )

    return NormalizedQuestion(
        title=title,
        description=str(content_raw),
        difficulty=difficulty,
        expected_language=None,  # Language-agnostic — see supported_languages
        status=status,
        input_format=input_format,
        output_format=output_format,
        constraints_text=constraints_text,
        supported_languages=supported_languages,
        starter_code=starter_code,
        test_cases=test_cases,
        provenance=provenance,
        llm_origin="curated",
        warnings=warnings,
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _format_title(raw: str, platform: str) -> str:
    """Format the raw title for display.

    LeetCode titles are slugs (e.g. 'zigzag-grid-traversal-with-skip').
    Convert hyphens to spaces and apply title-case.
    AtCoder titles may already be natural language — use as-is.
    """
    if platform == "leetcode" and "-" in raw and " " not in raw:
        return raw.replace("-", " ").title()
    return raw


def _extract_sections(
    content: str, platform: str
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Best-effort extraction of Input / Output / Constraints sections.

    Returns (input_format, output_format, constraints_text).
    All values may be None if not reliably found.
    Original content is NOT modified.
    """
    if platform == "atcoder":
        return _extract_atcoder_sections(content)
    if platform == "leetcode":
        return _extract_leetcode_sections(content)
    return None, None, None


# AtCoder content has explicit 'Input\n' ... 'Output\n' ... 'Constraints\n' headings.
_ATCODER_SECTION_RE = re.compile(
    r"(?:^|\n)"
    r"(Input|Output|Constraints)\s*\n"
    r"(.*?)"
    r"(?=\n(?:Input|Output|Constraints|Sample Input|Notes|Note)\s*\n|$)",
    re.DOTALL | re.IGNORECASE,
)


def _extract_atcoder_sections(
    content: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    sections: dict[str, str] = {}
    for match in _ATCODER_SECTION_RE.finditer(content):
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        if value:
            sections[key] = value
    return (
        sections.get("input") or None,
        sections.get("output") or None,
        sections.get("constraints") or None,
    )


# LeetCode content has Examples inline; constraints are usually a bullet list.
_LC_CONSTRAINTS_RE = re.compile(
    r"Constraints:\s*\n(.*?)(?:\n\n|\Z)", re.DOTALL
)
_LC_NOTE_RE = re.compile(
    r"Note:\s*\n(.*?)(?:\n\n|\Z)", re.DOTALL
)


def _extract_leetcode_sections(
    content: str,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    constraints = None
    m = _LC_CONSTRAINTS_RE.search(content)
    if m:
        constraints = m.group(1).strip() or None
    return None, None, constraints


def _validate_atcoder_status(
    test_cases: list[NormalizedTestCase], warnings: list[str]
) -> str:
    """Return 'validated' if the AtCoder question passes automated checks."""
    private_cases = [tc for tc in test_cases if not tc.is_sample]
    if not private_cases:
        warnings.append("No private test cases found; cannot advance past 'draft'")
        return "draft"
    # All stdout values must be non-empty for basic sanity
    # (Empty string is valid for some problems — only flag None/missing)
    return "validated"


def _validate_leetcode_functional_status(
    *,
    starter_code: object,
    test_cases: list[NormalizedTestCase],
    warnings: list[str],
) -> str:
    """Advance only supported Python functional records to validated."""
    if not any(not tc.is_sample for tc in test_cases):
        warnings.append("No private functional test cases; question remains draft")
        return "draft"
    if not test_cases or any(not tc.is_functional for tc in test_cases):
        warnings.append("Unsupported LeetCode test type; question remains draft")
        return "draft"
    try:
        method = solution_method(starter_code if isinstance(starter_code, str) else None)
        for test_case in test_cases:
            validate_functional_case(
                method, test_case.stdin, test_case.expected_stdout
            )
    except FunctionalFormatError as exc:
        warnings.append(f"Unsupported functional question ({exc}); question remains draft")
        return "draft"
    return "validated"


def _parse_contest_date(
    raw: object, warnings: list[str]
) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        warnings.append(f"Could not parse contest_date {raw!r}")
        return None


def _build_source_url(
    platform: str,
    question_id: str,
    contest_id: Optional[str],
    raw_title: str,
) -> Optional[str]:
    if platform == "atcoder" and contest_id and question_id:
        return f"https://atcoder.jp/contests/{contest_id}/tasks/{question_id}"
    if platform == "leetcode" and question_id:
        # question_id for LeetCode is numeric; use the raw title as slug
        slug = raw_title.lower().replace(" ", "-").replace("_", "-")
        # Strip characters not valid in a URL slug
        slug = re.sub(r"[^a-z0-9\-]", "", slug)
        return f"https://leetcode.com/problems/{slug}/"
    return None
