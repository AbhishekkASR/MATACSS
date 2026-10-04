"""Download and verify the LiveCodeBench dataset.

Usage (from the backend/ or repo root directory):

    python scripts/download_livecodebench.py

This script downloads the LiveCodeBench dataset from its canonical Hugging Face
source, verifies the SHA-256 checksum, and places the file at the expected path.

If the file already exists and its checksum matches, the download is skipped.

Note on canonical source
------------------------
LiveCodeBench is published at:

    https://huggingface.co/datasets/livecodebench/code_generation_lite

The JSONL export format used by MATACSS is derived from that dataset.
The exact download URL below points to the standard JSONL export.

If the URL changes or access is unavailable, obtain the file manually from:

    https://github.com/LiveCodeBench/LiveCodeBench

and place it at:

    data/question_bank/livecodebench/LiveCodeBench.jsonl

Then verify its SHA-256 matches the pinned value in this script before importing.
"""

from __future__ import annotations

import logging
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.question_bank.dataset_integrity import (
    DatasetIntegrityError,
    EXPECTED_LIVECODEBENCH_SHA256,
    sha256_of_file,
    verify_livecodebench_dataset,
)

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

# Pinned SHA-256 of the verified local copy of this dataset version.
EXPECTED_SHA256 = EXPECTED_LIVECODEBENCH_SHA256

# Canonical Hugging Face export URL for the code_generation_lite JSONL.
# This points to the standard JSONL snapshot used by MATACSS.
# Update this URL if a newer pinned version is adopted.
DOWNLOAD_URL = (
    "https://huggingface.co/datasets/livecodebench/code_generation_lite"
    "/resolve/main/release_v6.jsonl"
)

DEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "data" / "question_bank" / "livecodebench" / "LiveCodeBench.jsonl"
)
CHUNK_SIZE = 1 << 20  # 1 MB

# ── Checksum ──────────────────────────────────────────────────────────────────

def verify_checksum(path: Path) -> bool:
    try:
        verify_livecodebench_dataset(path)
    except DatasetIntegrityError:
        logger.error("LiveCodeBench SHA-256 verification failed.")
        return False
    logger.info("SHA-256 verified: %s", EXPECTED_SHA256)
    return True


# ── Download ──────────────────────────────────────────────────────────────────

def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    logger.info("Downloading %s → %s", url, dest)
    try:
        with urllib.request.urlopen(url) as response, tmp.open("wb") as out:  # noqa: S310
            downloaded = 0
            while chunk := response.read(CHUNK_SIZE):
                out.write(chunk)
                downloaded += len(chunk)
                print(f"\r  {downloaded / 1_048_576:.1f} MB downloaded", end="", flush=True)
        print()
        tmp.rename(dest)
        logger.info("Download complete: %s", dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    if DEST_PATH.exists():
        logger.info("File already exists at %s — checking checksum…", DEST_PATH)
        if verify_checksum(DEST_PATH):
            print("Dataset already present and verified. Nothing to do.")
            return
        else:
            logger.warning("Existing file has wrong checksum — re-downloading.")
            DEST_PATH.unlink()

    try:
        download_file(DOWNLOAD_URL, DEST_PATH)
    except Exception as exc:
        print(
            f"\nDownload failed: {exc}\n\n"
            "Please obtain LiveCodeBench.jsonl manually from:\n"
            "  https://github.com/LiveCodeBench/LiveCodeBench\n"
            f"and place it at:\n  {DEST_PATH}\n"
            f"Expected SHA-256: {EXPECTED_SHA256}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not verify_checksum(DEST_PATH):
        print(
            "\nERROR: Downloaded file checksum does not match the pinned value.\n"
            "The file may have changed at the source.  Review before importing.",
            file=sys.stderr,
        )
        DEST_PATH.unlink(missing_ok=True)
        sys.exit(1)

    print(f"\nDataset downloaded and verified at:\n  {DEST_PATH}")


if __name__ == "__main__":
    main()
