"""Security checks for the trusted LiveCodeBench importer boundary."""

import asyncio
import sys

import pytest

from app.question_bank import dataset_integrity
from app.question_bank.dataset_integrity import DatasetIntegrityError
from app.question_bank.importer import import_livecodebench


def test_exact_dataset_checksum_is_accepted(tmp_path, monkeypatch) -> None:
    dataset = tmp_path / "verified.jsonl"
    dataset.write_bytes(b"verified fixture")
    monkeypatch.setattr(
        dataset_integrity,
        "EXPECTED_LIVECODEBENCH_SHA256",
        dataset_integrity.sha256_of_file(dataset),
    )

    dataset_integrity.verify_livecodebench_dataset(dataset)


def test_tampered_import_is_rejected_before_pickle_loads(
    tmp_path, monkeypatch
) -> None:
    dataset = tmp_path / "tampered.jsonl"
    dataset.write_text("untrusted contents", encoding="utf-8")
    called = False

    def forbidden_pickle_loads(_payload: bytes) -> object:
        nonlocal called
        called = True
        raise AssertionError("pickle.loads must not run for an unverified file")

    monkeypatch.setattr("app.question_bank.decoder.pickle.loads", forbidden_pickle_loads)

    with pytest.raises(DatasetIntegrityError, match="verification failed"):
        asyncio.run(import_livecodebench(dataset))

    assert called is False


def test_custom_cli_path_cannot_bypass_checksum_verification(
    tmp_path, monkeypatch, capsys
) -> None:
    dataset = tmp_path / "custom.jsonl"
    dataset.write_text("tampered dataset contents", encoding="utf-8")
    called = False

    def forbidden_pickle_loads(_payload: bytes) -> object:
        nonlocal called
        called = True
        raise AssertionError("pickle.loads must not run for an unverified file")

    monkeypatch.setattr("app.question_bank.decoder.pickle.loads", forbidden_pickle_loads)
    monkeypatch.setattr(
        sys,
        "argv",
        ["import_livecodebench.py", "--path", str(dataset)],
    )

    from scripts.import_livecodebench import main

    with pytest.raises(SystemExit) as error:
        asyncio.run(main())

    assert error.value.code == 1
    assert called is False
    stderr = capsys.readouterr().err
    assert "SHA-256 verification failed" in stderr
    assert "tampered dataset contents" not in stderr
