"""Question Bank importer — streaming, idempotent, transactional.

Usage (from the backend/ directory):

    python scripts/import_livecodebench.py

    # Dry run (no database writes):
    python scripts/import_livecodebench.py --dry-run

    # Custom dataset path:
    python scripts/import_livecodebench.py --path /path/to/LiveCodeBench.jsonl

The importer:
- Streams the JSONL file line by line (no full 128 MB load into memory).
- Normalizes each record via the question_bank.normalizer.
- Checks for existing provenance records to skip already-imported questions.
- Persists question + test_cases + provenance + llm_lineage in a single
  transaction per record.
- Prints a final summary: imported / updated / skipped / failed / warnings.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Make ``python scripts/import_livecodebench.py`` work from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import async_session_factory, engine
from app.models.question import Question
from app.models.question_llm_lineage import QuestionLlmLineage
from app.models.question_provenance import QuestionProvenance
from app.models.question_test_case import QuestionTestCase
from app.question_bank.decoder import LiveCodeBenchDecodeError
from app.question_bank.dataset_integrity import verify_livecodebench_dataset
from app.question_bank.normalizer import (
    NormalizedQuestion,
    NormalizationError,
    normalize_record,
)

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[2]
    / "data" / "question_bank" / "livecodebench" / "LiveCodeBench.jsonl"
)
LIVECODEBENCH_SOURCE = "livecodebench"


# ── Import statistics ─────────────────────────────────────────────────────────

@dataclass
class ImportStats:
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    warnings: int = 0
    warning_details: list[str] = field(default_factory=list)
    failure_details: list[str] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            "─" * 56,
            "LiveCodeBench import complete",
            f"  Imported : {self.imported}",
            f"  Skipped  : {self.skipped}  (already in database)",
            f"  Failed   : {self.failed}",
            f"  Warnings : {self.warnings}",
        ]
        if self.failure_details:
            lines.append("\nFailures:")
            for detail in self.failure_details[:20]:
                lines.append(f"  • {detail}")
        if self.warning_details:
            lines.append("\nWarnings (first 20):")
            for detail in self.warning_details[:20]:
                lines.append(f"  ⚠ {detail}")
        lines.append("─" * 56)
        return "\n".join(lines)


# ── Duplicate detection ───────────────────────────────────────────────────────

async def _is_already_imported(
    session: AsyncSession,
    platform: str,
    original_question_id: str,
) -> bool:
    """Return True if provenance record already exists for this (source, platform, qid)."""
    existing = await session.scalar(
        select(QuestionProvenance).where(
            QuestionProvenance.source == LIVECODEBENCH_SOURCE,
            QuestionProvenance.platform == platform,
            QuestionProvenance.original_question_id == original_question_id,
        )
    )
    return existing is not None


# ── Single-record persistence ─────────────────────────────────────────────────

async def _persist_question(
    session: AsyncSession,
    nq: NormalizedQuestion,
    *,
    dry_run: bool,
) -> None:
    """Persist one NormalizedQuestion within the caller's transaction."""
    if dry_run:
        return

    question = Question(
        title=nq.title,
        description=nq.description,
        difficulty=nq.difficulty,
        expected_language=nq.expected_language,
        status=nq.status,
        input_format=nq.input_format,
        output_format=nq.output_format,
        constraints_text=nq.constraints_text,
        supported_languages=nq.supported_languages,
        starter_code=nq.starter_code,
    )
    session.add(question)
    await session.flush()  # Assigns question.id without committing

    # Test cases
    for tc in nq.test_cases:
        session.add(QuestionTestCase(
            question_id=question.id,
            stdin=tc.stdin,
            expected_stdout=tc.expected_stdout,
            time_limit_ms=tc.time_limit_ms,
            description=tc.description,
            is_sample=tc.is_sample,
            is_functional=tc.is_functional,
            tc_order=tc.tc_order,
        ))

    # Provenance
    p = nq.provenance
    session.add(QuestionProvenance(
        question_id=question.id,
        source=p.source,
        platform=p.platform,
        original_question_id=p.original_question_id,
        contest_id=p.contest_id,
        contest_date=p.contest_date,
        source_url=p.source_url,
        license=p.license,
        dataset_name=p.dataset_name,
        dataset_version=p.dataset_version,
    ))

    # LLM lineage (curated — all LLM fields are NULL)
    session.add(QuestionLlmLineage(
        question_id=question.id,
        origin=nq.llm_origin,
        model=None,
        generation_timestamp=None,
        parent_question_id=None,
        generation_metadata=None,
    ))


# ── Main importer ─────────────────────────────────────────────────────────────

async def import_livecodebench(
    dataset_path: Path,
    *,
    dry_run: bool = False,
) -> ImportStats:
    """Stream and import all records from a LiveCodeBench JSONL file.

    Each record is processed in its own transaction so a single bad record
    does not abort the entire import.
    """
    stats = ImportStats()

    if not dataset_path.exists():
        raise FileNotFoundError(
            f"Dataset file not found: {dataset_path}\n"
            "Run scripts/download_livecodebench.py to fetch it."
        )
    verify_livecodebench_dataset(dataset_path)

    logger.info("Starting LiveCodeBench import from %s (dry_run=%s)", dataset_path, dry_run)

    with dataset_path.open(encoding="utf-8") as fh:
        for line_num, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue

            # ── Parse raw JSON ──────────────────────────────────────────────
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                msg = f"Line {line_num}: JSON parse error: {exc}"
                stats.failed += 1
                stats.failure_details.append(msg)
                logger.warning(msg)
                continue

            platform = record.get("platform", "?")
            orig_qid = str(record.get("question_id", "?"))

            # ── Duplicate check ─────────────────────────────────────────────
            async with async_session_factory() as session:
                already = await _is_already_imported(session, platform, orig_qid)

            if already:
                logger.debug("Skipping already-imported %s/%s", platform, orig_qid)
                stats.skipped += 1
                continue

            # ── Normalize ───────────────────────────────────────────────────
            try:
                nq = normalize_record(record)
            except (NormalizationError, LiveCodeBenchDecodeError) as exc:
                msg = f"Line {line_num} ({platform}/{orig_qid}): normalization failed: {exc}"
                stats.failed += 1
                stats.failure_details.append(msg)
                logger.warning(msg)
                continue

            if nq.warnings:
                stats.warnings += len(nq.warnings)
                for w in nq.warnings:
                    stats.warning_details.append(f"Line {line_num} ({platform}/{orig_qid}): {w}")
                    logger.debug("Warning %s/%s: %s", platform, orig_qid, w)

            # ── Persist (single transaction per record) ─────────────────────
            try:
                async with async_session_factory() as session:
                    async with session.begin():
                        await _persist_question(session, nq, dry_run=dry_run)
            except Exception as exc:
                msg = f"Line {line_num} ({platform}/{orig_qid}): persistence error: {exc}"
                stats.failed += 1
                stats.failure_details.append(msg)
                logger.warning(msg)
                continue

            stats.imported += 1
            action = "[DRY RUN]" if dry_run else "Imported"
            logger.info(
                "%s [%d] %s/%s — %s (%s, %d TCs, status=%s)",
                action,
                stats.imported,
                platform,
                orig_qid,
                nq.title,
                nq.difficulty,
                len(nq.test_cases),
                nq.status,
            )

    return stats
