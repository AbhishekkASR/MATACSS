"""CLI entry point for the LiveCodeBench Question Bank importer.

Usage (from the backend/ directory):

    python scripts/import_livecodebench.py
    python scripts/import_livecodebench.py --dry-run
    python scripts/import_livecodebench.py --path /custom/path/LiveCodeBench.jsonl
    python scripts/import_livecodebench.py --verbose

This script uses the configured DATABASE_URL and is intentionally not
imported or executed by the FastAPI application.

The raw dataset file must be placed (or downloaded) at the expected path
before running this script.  See scripts/download_livecodebench.py.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Make ``python scripts/import_livecodebench.py`` work from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import engine
from app.question_bank.dataset_integrity import DatasetIntegrityError
from app.question_bank.importer import DEFAULT_DATASET_PATH, import_livecodebench


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import LiveCodeBench dataset into the MATACSS Question Bank."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help=f"Path to LiveCodeBench.jsonl (default: {DEFAULT_DATASET_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and normalize all records without writing to the database.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.dry_run:
        print("DRY RUN — no database changes will be made.\n")

    try:
        stats = await import_livecodebench(args.path, dry_run=args.dry_run)
    except (DatasetIntegrityError, FileNotFoundError) as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        await engine.dispose()

    print(stats.report())
    if stats.failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
