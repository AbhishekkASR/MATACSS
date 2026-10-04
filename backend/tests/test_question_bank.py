"""Tests for the LiveCodeBench Question Bank import pipeline.

Covers all 18 required test categories:
 1.  LiveCodeBench record parsing
 2.  Base64 decoding
 3.  zlib decompression
 4.  Pickle/JSON decoding
 5.  Invalid encoded data
 6.  Public test parsing
 7.  Private test parsing
 8.  AtCoder normalization
 9.  LeetCode normalization
10.  Question provenance
11.  Difficulty mapping
12.  Duplicate/idempotent imports
13.  Test-case ordering
14.  Sample/private classification
15.  Functional/stdin classification
16.  Validation status rules
17.  Test-case limit enforcement
18.  Import failure handling

All tests use small in-memory fixtures and do NOT require the 128 MB dataset.
"""

from __future__ import annotations

import asyncio
import base64
import json
import pickle
import zlib
from pathlib import Path

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, Question, QuestionTestCase
from app.models.question_provenance import QuestionProvenance
from app.models.question_llm_lineage import QuestionLlmLineage
from app.question_bank.decoder import (
    LiveCodeBenchDecodeError,
    RawTestCase,
    decode_private_test_cases,
    decode_public_test_cases,
)
from app.question_bank.normalizer import (
    NormalizationError,
    NormalizedQuestion,
    normalize_record,
    _format_title,
    _extract_sections,
)
from app.question_bank.importer import (
    ImportStats,
    _is_already_imported,
    _persist_question,
    import_livecodebench,
)
from app.question_bank import dataset_integrity


def _trust_fixture_dataset_for_import_test(
    monkeypatch: pytest.MonkeyPatch, path: Path
) -> None:
    monkeypatch.setattr(
        dataset_integrity,
        "EXPECTED_LIVECODEBENCH_SHA256",
        dataset_integrity.sha256_of_file(path),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

def _encode_private(cases: list[dict]) -> str:
    """Build the exact private_test_cases encoding: Base64(zlib(pickle(json_str)))."""
    json_str = json.dumps(cases)
    pickled = pickle.dumps(json_str, protocol=4)
    compressed = zlib.compress(pickled)
    return base64.b64encode(compressed).decode("ascii")


def _make_atcoder_record(
    question_id: str = "abc387_b",
    title: str = "9x9 Sum",
    difficulty: str = "easy",
    content: str = (
        "Find the sum.\n\nInput\n\nX\n\nOutput\n\nPrint the answer.\n\n"
        "Constraints\n\n- 1 <= X <= 81\n"
    ),
    public: list[dict] | None = None,
    private: list[dict] | None = None,
) -> dict:
    if public is None:
        public = [{"input": "1", "output": "2024", "testtype": "stdin"}]
    if private is None:
        private = [
            {"input": "26", "output": "2025\n", "testtype": "stdin"},
            {"input": "15", "output": "1995\n", "testtype": "stdin"},
        ]
    return {
        "question_title": title,
        "question_content": content,
        "platform": "atcoder",
        "question_id": question_id,
        "contest_id": "abc387",
        "contest_date": "2025-01-04T00:00:00",
        "starter_code": "",
        "difficulty": difficulty,
        "public_test_cases": json.dumps(public),
        "private_test_cases": _encode_private(private),
        "metadata": "{}",
    }


def _make_leetcode_record(
    question_id: str = "3708",
    title: str = "zigzag-grid-traversal-with-skip",
    difficulty: str = "easy",
    public: list[dict] | None = None,
    private: list[dict] | None = None,
) -> dict:
    if public is None:
        public = [{"input": "[[1, 2], [3, 4]]", "output": "[1, 4]", "testtype": "functional"}]
    if private is None:
        private = [{"input": "[[3,2],[3,2]]", "output": "[3,2]", "testtype": "functional"}]
    return {
        "question_title": title,
        "question_content": "Traverse the grid.\n\nConstraints:\n- 1 <= m, n <= 10\n",
        "platform": "leetcode",
        "question_id": question_id,
        "contest_id": "weekly-contest-469",
        "contest_date": "2025-01-05T00:00:00",
        "starter_code": "class Solution:\n    def zigzagTraversal(self, grid):\n        pass\n",
        "difficulty": difficulty,
        "public_test_cases": json.dumps(public),
        "private_test_cases": _encode_private(private),
        "metadata": "{}",
    }


def make_db():
    async def _setup():
        eng = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(eng.sync_engine, "connect")
        def _fk(conn, _):
            conn.execute("PRAGMA foreign_keys=ON")

        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(eng, expire_on_commit=False)

    return asyncio.run(_setup())


# ═══════════════════════════════════════════════════════════════════════════════
# 1. LiveCodeBench record parsing
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecordParsing:
    def test_atcoder_record_normalizes(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        assert nq.title == "9x9 Sum"
        assert nq.difficulty == "easy"
        assert nq.description == rec["question_content"]

    def test_leetcode_record_normalizes(self):
        rec = _make_leetcode_record()
        nq = normalize_record(rec)
        assert nq.title == "Zigzag Grid Traversal With Skip"

    def test_missing_title_raises(self):
        rec = _make_atcoder_record()
        rec["question_title"] = ""
        with pytest.raises(NormalizationError, match="question_title is empty"):
            normalize_record(rec)

    def test_missing_content_raises(self):
        rec = _make_atcoder_record()
        rec["question_content"] = "   "
        with pytest.raises(NormalizationError, match="question_content is empty"):
            normalize_record(rec)

    def test_missing_platform_raises(self):
        rec = _make_atcoder_record()
        rec["platform"] = ""
        with pytest.raises(NormalizationError, match="platform is missing"):
            normalize_record(rec)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Base64 decoding
# ═══════════════════════════════════════════════════════════════════════════════

class TestBase64Decoding:
    def test_valid_base64_decodes(self):
        cases = [{"input": "1", "output": "2024", "testtype": "stdin"}]
        encoded = _encode_private(cases)
        result = decode_private_test_cases(encoded)
        assert len(result) == 1

    def test_invalid_base64_raises(self):
        with pytest.raises(LiveCodeBenchDecodeError, match="Base64 decode failed"):
            decode_private_test_cases("!!!not-base64!!!")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. zlib decompression
# ═══════════════════════════════════════════════════════════════════════════════

class TestZlibDecompression:
    def test_non_zlib_data_raises(self):
        # Valid base64 but the payload is not zlib
        garbage = base64.b64encode(b"this is not zlib compressed data").decode()
        with pytest.raises(LiveCodeBenchDecodeError, match="zlib decompress failed"):
            decode_private_test_cases(garbage)

    def test_correct_zlib_header(self):
        # Verify that our encoder produces zlib magic bytes 0x78 0x9C
        cases = [{"input": "a", "output": "b", "testtype": "stdin"}]
        raw = base64.b64decode(_encode_private(cases))
        assert raw[0] == 0x78, "Expected zlib magic byte 0"
        assert raw[1] == 0x9C, "Expected zlib magic byte 1"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Pickle/JSON decoding
# ═══════════════════════════════════════════════════════════════════════════════

class TestPickleJsonDecoding:
    def test_pickle_wraps_json_string(self):
        cases = [{"input": "hello", "output": "world", "testtype": "stdin"}]
        encoded = _encode_private(cases)
        result = decode_private_test_cases(encoded)
        assert result[0].input == "hello"
        assert result[0].output == "world"

    def test_pickle_non_string_payload_raises(self):
        # Pickle wraps a list instead of a str
        pickled = pickle.dumps([1, 2, 3], protocol=4)
        compressed = zlib.compress(pickled)
        encoded = base64.b64encode(compressed).decode()
        with pytest.raises(LiveCodeBenchDecodeError, match="pickle payload must be a str"):
            decode_private_test_cases(encoded)

    def test_invalid_inner_json_raises(self):
        pickled = pickle.dumps("not valid json {{", protocol=4)
        compressed = zlib.compress(pickled)
        encoded = base64.b64encode(compressed).decode()
        with pytest.raises(LiveCodeBenchDecodeError, match="JSON parse of pickle payload failed"):
            decode_private_test_cases(encoded)

    def test_inner_json_non_list_raises(self):
        pickled = pickle.dumps('{"key": "val"}', protocol=4)
        compressed = zlib.compress(pickled)
        encoded = base64.b64encode(compressed).decode()
        with pytest.raises(LiveCodeBenchDecodeError, match="must be a list"):
            decode_private_test_cases(encoded)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Invalid encoded data
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvalidEncodedData:
    def test_empty_string_raises(self):
        with pytest.raises(LiveCodeBenchDecodeError):
            decode_private_test_cases("")

    def test_missing_required_key_raises(self):
        cases = [{"input": "1", "testtype": "stdin"}]  # missing 'output'
        encoded = _encode_private(cases)
        with pytest.raises(LiveCodeBenchDecodeError, match="missing required key 'output'"):
            decode_private_test_cases(encoded)

    def test_non_dict_element_raises(self):
        cases = ["not a dict"]
        encoded = _encode_private(cases)
        with pytest.raises(LiveCodeBenchDecodeError, match="must be a dict"):
            decode_private_test_cases(encoded)


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Public test parsing
# ═══════════════════════════════════════════════════════════════════════════════

class TestPublicTestParsing:
    def test_public_tests_marked_as_sample(self):
        cases = [{"input": "1", "output": "2024", "testtype": "stdin"}]
        result = decode_public_test_cases(json.dumps(cases))
        assert result[0].is_sample is True

    def test_multiple_public_tests_parsed(self):
        cases = [
            {"input": "1", "output": "A", "testtype": "stdin"},
            {"input": "2", "output": "B", "testtype": "stdin"},
        ]
        result = decode_public_test_cases(json.dumps(cases))
        assert len(result) == 2

    def test_invalid_public_json_raises(self):
        with pytest.raises(LiveCodeBenchDecodeError, match="public_test_cases JSON parse failed"):
            decode_public_test_cases("not valid json")

    def test_public_non_array_raises(self):
        with pytest.raises(LiveCodeBenchDecodeError, match="must be a JSON array"):
            decode_public_test_cases('{"key": "val"}')


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Private test parsing
# ═══════════════════════════════════════════════════════════════════════════════

class TestPrivateTestParsing:
    def test_private_tests_marked_not_sample(self):
        cases = [{"input": "26", "output": "2025\n", "testtype": "stdin"}]
        encoded = _encode_private(cases)
        result = decode_private_test_cases(encoded)
        assert result[0].is_sample is False

    def test_private_tests_preserve_trailing_newline(self):
        cases = [{"input": "x", "output": "abc\n", "testtype": "stdin"}]
        encoded = _encode_private(cases)
        result = decode_private_test_cases(encoded)
        assert result[0].output == "abc\n"

    def test_multiple_private_tests_all_decoded(self):
        cases = [{"input": str(i), "output": str(i * 2), "testtype": "stdin"} for i in range(40)]
        encoded = _encode_private(cases)
        result = decode_private_test_cases(encoded)
        assert len(result) == 40


# ═══════════════════════════════════════════════════════════════════════════════
# 8. AtCoder normalization
# ═══════════════════════════════════════════════════════════════════════════════

class TestAtCoderNormalization:
    def test_atcoder_status_validated(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        assert nq.status == "validated"

    def test_atcoder_languages_all_three(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        assert set(nq.supported_languages) == {"python", "cpp", "java"}

    def test_atcoder_expected_language_is_none(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        assert nq.expected_language is None

    def test_atcoder_extracts_input_format(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        assert nq.input_format is not None
        assert "X" in nq.input_format

    def test_atcoder_extracts_constraints(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        assert nq.constraints_text is not None
        assert "1 <= X <= 81" in nq.constraints_text

    def test_atcoder_no_private_cases_stays_draft(self):
        rec = _make_atcoder_record(private=[])
        # Only one public case; no private
        nq = normalize_record(rec)
        assert nq.status == "draft"
        assert any("No private test cases" in w for w in nq.warnings)

    def test_atcoder_stdin_testtype_classification(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        for tc in nq.test_cases:
            assert tc.is_functional is False


# ═══════════════════════════════════════════════════════════════════════════════
# 9. LeetCode normalization
# ═══════════════════════════════════════════════════════════════════════════════

class TestLeetCodeNormalization:
    def test_supported_leetcode_functional_question_is_validated(self):
        rec = _make_leetcode_record()
        nq = normalize_record(rec)
        assert nq.status == "validated"

    def test_unsupported_leetcode_functional_question_stays_draft(self):
        rec = _make_leetcode_record(
            public=[
                {
                    "input": "not a literal",
                    "output": "[]",
                    "testtype": "functional",
                }
            ]
        )
        nq = normalize_record(rec)
        assert nq.status == "draft"
        assert any("Unsupported functional question" in warning for warning in nq.warnings)

    def test_nonfunctional_leetcode_test_type_stays_draft(self):
        rec = _make_leetcode_record(
            public=[{"input": "1", "output": "1", "testtype": "stdin"}]
        )
        nq = normalize_record(rec)
        assert nq.status == "draft"

    def test_leetcode_slug_title_formatted(self):
        rec = _make_leetcode_record(title="zigzag-grid-traversal-with-skip")
        nq = normalize_record(rec)
        assert nq.title == "Zigzag Grid Traversal With Skip"

    def test_leetcode_languages_python_only(self):
        rec = _make_leetcode_record()
        nq = normalize_record(rec)
        assert nq.supported_languages == ["python"]

    def test_leetcode_starter_code_preserved(self):
        rec = _make_leetcode_record()
        nq = normalize_record(rec)
        assert nq.starter_code is not None
        assert "Solution" in nq.starter_code

    def test_leetcode_functional_testtype(self):
        rec = _make_leetcode_record()
        nq = normalize_record(rec)
        for tc in nq.test_cases:
            assert tc.is_functional is True

    def test_leetcode_extracts_constraints(self):
        rec = _make_leetcode_record()
        nq = normalize_record(rec)
        assert nq.constraints_text is not None
        assert "1 <= m, n <= 10" in nq.constraints_text

    def test_leetcode_source_url_constructed(self):
        rec = _make_leetcode_record(
            question_id="3708",
            title="zigzag-grid-traversal-with-skip",
        )
        nq = normalize_record(rec)
        assert nq.provenance.source_url is not None
        assert "leetcode.com" in nq.provenance.source_url


# ═══════════════════════════════════════════════════════════════════════════════
# 10. Question provenance
# ═══════════════════════════════════════════════════════════════════════════════

class TestProvenance:
    def test_atcoder_provenance_fields(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        p = nq.provenance
        assert p.source == "livecodebench"
        assert p.platform == "atcoder"
        assert p.original_question_id == "abc387_b"
        assert p.contest_id == "abc387"
        assert p.dataset_name == "LiveCodeBench"
        assert "BB4C364F" in p.dataset_version

    def test_atcoder_source_url(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        assert "atcoder.jp" in nq.provenance.source_url
        assert "abc387" in nq.provenance.source_url

    def test_license_is_none(self):
        # License must not be invented
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        assert nq.provenance.license is None

    def test_contest_date_parsed(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        assert nq.provenance.contest_date is not None
        assert nq.provenance.contest_date.year == 2025

    def test_llm_origin_is_curated(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        assert nq.llm_origin == "curated"


# ═══════════════════════════════════════════════════════════════════════════════
# 11. Difficulty mapping
# ═══════════════════════════════════════════════════════════════════════════════

class TestDifficultyMapping:
    @pytest.mark.parametrize("diff", ["easy", "medium", "hard"])
    def test_valid_difficulty_passes_through(self, diff):
        rec = _make_atcoder_record(difficulty=diff)
        nq = normalize_record(rec)
        assert nq.difficulty == diff

    def test_unknown_difficulty_defaults_medium(self):
        rec = _make_atcoder_record(difficulty="expert")
        nq = normalize_record(rec)
        assert nq.difficulty == "medium"
        assert any("Unknown difficulty" in w for w in nq.warnings)

    def test_uppercase_difficulty_normalized(self):
        rec = _make_atcoder_record(difficulty="EASY")
        nq = normalize_record(rec)
        assert nq.difficulty == "easy"


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Duplicate/idempotent imports
# ═══════════════════════════════════════════════════════════════════════════════

class TestDuplicateImport:
    def test_already_imported_returns_true_when_present(self):
        factory = make_db()

        async def _run():
            async with factory() as session:
                async with session.begin():
                    from app.models.question import Question as Q
                    q = Q(
                        title="T", description="D", difficulty="easy",
                        status="validated",
                    )
                    session.add(q)
                    await session.flush()
                    session.add(QuestionProvenance(
                        question_id=q.id,
                        source="livecodebench",
                        platform="atcoder",
                        original_question_id="abc_test_dupe",
                    ))
            async with factory() as session:
                result = await _is_already_imported(session, "atcoder", "abc_test_dupe")
            return result

        assert asyncio.run(_run()) is True

    def test_not_imported_returns_false(self):
        factory = make_db()

        async def _run():
            async with factory() as session:
                return await _is_already_imported(session, "atcoder", "nonexistent_id")

        assert asyncio.run(_run()) is False

    def test_import_twice_second_is_skipped(self, tmp_path, monkeypatch):
        """Import a one-record JSONL twice; second run must skip the record."""
        rec = _make_atcoder_record(question_id="idempotent_test_001")
        jsonl = tmp_path / "test.jsonl"
        jsonl.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        _trust_fixture_dataset_for_import_test(monkeypatch, jsonl)

        factory = make_db()

        async def _run():
            # Patch the global session factory in the importer module
            import app.question_bank.importer as imp
            orig = imp.async_session_factory
            imp.async_session_factory = factory
            try:
                s1 = await import_livecodebench(jsonl)
                s2 = await import_livecodebench(jsonl)
            finally:
                imp.async_session_factory = orig
            return s1, s2

        s1, s2 = asyncio.run(_run())
        assert s1.imported == 1
        assert s1.skipped == 0
        assert s2.imported == 0
        assert s2.skipped == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Test-case ordering
# ═══════════════════════════════════════════════════════════════════════════════

class TestTestCaseOrdering:
    def test_public_cases_ordered_first(self):
        rec = _make_atcoder_record(
            public=[
                {"input": "pub1", "output": "out1", "testtype": "stdin"},
                {"input": "pub2", "output": "out2", "testtype": "stdin"},
            ],
            private=[
                {"input": "priv1", "output": "pout1", "testtype": "stdin"},
            ],
        )
        nq = normalize_record(rec)
        assert nq.test_cases[0].stdin == "pub1"
        assert nq.test_cases[1].stdin == "pub2"
        assert nq.test_cases[2].stdin == "priv1"

    def test_tc_order_values_sequential(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        for i, tc in enumerate(nq.test_cases):
            assert tc.tc_order == i

    def test_order_preserved_across_pub_priv_boundary(self):
        pub = [{"input": "p", "output": "P", "testtype": "stdin"}]
        priv = [{"input": "r", "output": "R", "testtype": "stdin"}] * 3
        rec = _make_atcoder_record(public=pub, private=priv)
        nq = normalize_record(rec)
        assert nq.test_cases[0].tc_order == 0
        assert nq.test_cases[3].tc_order == 3


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Sample/private classification
# ═══════════════════════════════════════════════════════════════════════════════

class TestSamplePrivateClassification:
    def test_public_cases_are_samples(self):
        rec = _make_atcoder_record(
            public=[{"input": "1", "output": "A", "testtype": "stdin"}],
            private=[],
        )
        nq = normalize_record(rec)
        assert nq.test_cases[0].is_sample is True

    def test_private_cases_are_not_samples(self):
        rec = _make_atcoder_record(
            public=[],
            private=[{"input": "1", "output": "A", "testtype": "stdin"}],
        )
        nq = normalize_record(rec)
        assert nq.test_cases[0].is_sample is False

    def test_description_matches_tier(self):
        rec = _make_atcoder_record(
            public=[{"input": "1", "output": "A", "testtype": "stdin"}],
            private=[{"input": "2", "output": "B", "testtype": "stdin"}],
        )
        nq = normalize_record(rec)
        assert nq.test_cases[0].description == "public"
        assert nq.test_cases[1].description == "private"


# ═══════════════════════════════════════════════════════════════════════════════
# 15. Functional/stdin classification
# ═══════════════════════════════════════════════════════════════════════════════

class TestFunctionalStdinClassification:
    def test_atcoder_stdin_not_functional(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        for tc in nq.test_cases:
            assert tc.is_functional is False

    def test_leetcode_functional_flag_set(self):
        rec = _make_leetcode_record()
        nq = normalize_record(rec)
        for tc in nq.test_cases:
            assert tc.is_functional is True

    def test_mixed_testtype_warns(self):
        # Inject an unexpected testtype into an AtCoder record
        private = [
            {"input": "1", "output": "A", "testtype": "stdin"},
            {"input": "2", "output": "B", "testtype": "functional"},  # unexpected
        ]
        rec = _make_atcoder_record(private=private)
        nq = normalize_record(rec)
        assert any("Unexpected testtype" in w for w in nq.warnings)


# ═══════════════════════════════════════════════════════════════════════════════
# 16. Validation status rules
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidationStatus:
    def test_atcoder_with_private_cases_is_validated(self):
        rec = _make_atcoder_record()
        nq = normalize_record(rec)
        assert nq.status == "validated"

    def test_atcoder_without_private_cases_is_draft(self):
        rec = _make_atcoder_record(private=[])
        nq = normalize_record(rec)
        assert nq.status == "draft"

    def test_supported_leetcode_functional_cases_are_validated(self):
        rec = _make_leetcode_record()
        nq = normalize_record(rec)
        assert nq.status == "validated"

    def test_valid_lifecycle_values(self):
        for diff in ("easy", "medium", "hard"):
            rec = _make_atcoder_record(difficulty=diff)
            nq = normalize_record(rec)
            assert nq.status in {"draft", "validated", "approved", "active", "deprecated"}


# ═══════════════════════════════════════════════════════════════════════════════
# 17. Test-case limit enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestTestCaseLimit:
    def test_truncates_at_100(self):
        # 5 public + 100 private = 105 → truncated to 100
        pub = [{"input": "p", "output": "P", "testtype": "stdin"}] * 5
        priv = [{"input": str(i), "output": str(i), "testtype": "stdin"} for i in range(100)]
        rec = _make_atcoder_record(public=pub, private=priv)
        nq = normalize_record(rec)
        assert len(nq.test_cases) == 100
        assert any("truncating to 100" in w for w in nq.warnings)

    def test_exactly_100_not_truncated(self):
        pub = [{"input": "p", "output": "P", "testtype": "stdin"}] * 3
        priv = [{"input": str(i), "output": str(i), "testtype": "stdin"} for i in range(97)]
        rec = _make_atcoder_record(public=pub, private=priv)
        nq = normalize_record(rec)
        assert len(nq.test_cases) == 100
        assert not any("truncating" in w for w in nq.warnings)

    def test_no_test_cases_raises(self):
        rec = _make_atcoder_record(public=[], private=[])
        with pytest.raises(NormalizationError, match="No test cases found"):
            normalize_record(rec)


# ═══════════════════════════════════════════════════════════════════════════════
# 18. Import failure handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestImportFailureHandling:
    def test_missing_file_raises_file_not_found(self, tmp_path):
        missing = tmp_path / "does_not_exist.jsonl"

        async def _run():
            return await import_livecodebench(missing)

        with pytest.raises(FileNotFoundError):
            asyncio.run(_run())

    def test_invalid_json_line_counted_as_failed(self, tmp_path, monkeypatch):
        bad_file = tmp_path / "bad.jsonl"
        bad_file.write_text("not valid json\n", encoding="utf-8")
        _trust_fixture_dataset_for_import_test(monkeypatch, bad_file)

        factory = make_db()

        async def _run():
            import app.question_bank.importer as imp
            orig = imp.async_session_factory
            imp.async_session_factory = factory
            try:
                stats = await import_livecodebench(bad_file)
            finally:
                imp.async_session_factory = orig
            return stats

        stats = asyncio.run(_run())
        assert stats.failed == 1
        assert stats.imported == 0

    def test_normalization_failure_counted_as_failed(self, tmp_path, monkeypatch):
        bad_rec = _make_atcoder_record()
        bad_rec["question_title"] = ""  # will fail normalization
        jl = tmp_path / "bad.jsonl"
        jl.write_text(json.dumps(bad_rec) + "\n", encoding="utf-8")
        _trust_fixture_dataset_for_import_test(monkeypatch, jl)

        factory = make_db()

        async def _run():
            import app.question_bank.importer as imp
            orig = imp.async_session_factory
            imp.async_session_factory = factory
            try:
                stats = await import_livecodebench(jl)
            finally:
                imp.async_session_factory = orig
            return stats

        stats = asyncio.run(_run())
        assert stats.failed == 1

    def test_good_record_persisted_despite_earlier_failure(
        self, tmp_path, monkeypatch
    ):
        bad = _make_atcoder_record(question_id="bad_one")
        bad["question_title"] = ""  # fails
        good = _make_atcoder_record(question_id="good_one", title="Good Question")
        jl = tmp_path / "mixed.jsonl"
        jl.write_text(
            json.dumps(bad) + "\n" + json.dumps(good) + "\n",
            encoding="utf-8",
        )
        _trust_fixture_dataset_for_import_test(monkeypatch, jl)

        factory = make_db()

        async def _run():
            import app.question_bank.importer as imp
            orig = imp.async_session_factory
            imp.async_session_factory = factory
            try:
                stats = await import_livecodebench(jl)
            finally:
                imp.async_session_factory = orig
            return stats

        stats = asyncio.run(_run())
        assert stats.failed == 1
        assert stats.imported == 1

    def test_dry_run_imports_nothing(self, tmp_path, monkeypatch):
        rec = _make_atcoder_record(question_id="dry_run_test")
        jl = tmp_path / "dry.jsonl"
        jl.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        _trust_fixture_dataset_for_import_test(monkeypatch, jl)

        factory = make_db()

        async def _run():
            import app.question_bank.importer as imp
            orig = imp.async_session_factory
            imp.async_session_factory = factory
            try:
                stats = await import_livecodebench(jl, dry_run=True)
                # After dry run there should be nothing in the DB
                async with factory() as session:
                    count = await session.scalar(
                        select(Question).where(Question.title == "9x9 Sum")
                    )
            finally:
                imp.async_session_factory = orig
            return stats, count

        stats, count = asyncio.run(_run())
        # Dry run still counts as "imported" (meaning processed without error)
        assert stats.imported == 1
        assert count is None  # nothing persisted
