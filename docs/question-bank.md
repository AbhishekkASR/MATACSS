# MATACSS Question Bank

## Overview

The MATACSS Question Bank is the authoritative source of coding problems that
flow into the Question Engine, candidate assessments, and Docker-backed
deterministic evaluation.

```
Question Bank (LiveCodeBench + future sources)
        ↓
  Normalizer / Importer
        ↓
  PostgreSQL (questions, question_test_cases, question_provenance, question_llm_lineage)
        ↓
  Question Engine  →  Interview Assignment  →  Candidate Assessment
        ↓
  Submission  →  Docker Sandbox  →  Deterministic Evaluation  →  Official Result
```

The Question Bank **does not replace** any part of the existing architecture. It
supplies `questions` and `question_test_cases` rows that the existing evaluation
pipeline already consumes unchanged.

---

## Current Dataset: LiveCodeBench

| Property | Value |
|---|---|
| File | `data/question_bank/livecodebench/LiveCodeBench.jsonl` |
| Size | 128.1 MB |
| Records | 175 |
| AtCoder problems | 112 (stdin/stdout evaluation) |
| LeetCode problems | 63 (functional evaluation — draft only) |
| Difficulty distribution | 43 Easy · 52 Medium · 80 Hard |
| Total test cases | 7,000 (463 public + 6,537 private) |
| SHA-256 | `BB4C364F71921C4495A6AD15ABE1A927350B720009F4933E2E71F8AF0F6FD1F5` |
| Dataset source | https://github.com/LiveCodeBench/LiveCodeBench |

**The raw JSONL file is NOT committed to Git.** It is excluded by `.gitignore`.
Obtain it via the download script or manually. See [Local Setup](#local-setup).

---

## Question Status Lifecycle

Every question has a `status` field that controls its eligibility for
assignment to live interview sessions.

```
draft  →  validated  →  approved  →  active  →  deprecated
```

| Status | Meaning |
|---|---|
| `draft` | Imported but not yet verified. Not assignable. |
| `validated` | Automated checks passed (AtCoder: has private test cases). |
| `approved` | Human admin has reviewed and approved. |
| `active` | Available for assignment to interview sessions. |
| `deprecated` | Retired. Historical results preserved. |

**Only `active` questions may be assigned to interview sessions.**

### Automatic promotion at import time

- **AtCoder (stdin)**: Questions with ≥1 private test case are automatically
  promoted from `draft` to `validated`.
- **LeetCode (functional)**: Questions stay at `draft` until a functional
  execution harness is implemented.

---

## Evaluation Modes

### AtCoder — stdin/stdout (immediately usable)

AtCoder problems use `testtype: "stdin"`. The `input` field is raw text fed
to process stdin; the `output` field is the expected stdout. These map
directly to the existing `QuestionTestCase.stdin` and
`QuestionTestCase.expected_stdout` fields and run through the unmodified
Docker sandbox and deterministic evaluator.

### LeetCode — functional (future)

LeetCode problems use `testtype: "functional"`. The `input` field is a
JSON-serialized argument list; the `output` field is a JSON-serialized return
value. These **cannot** be run through the current stdin/stdout evaluation
path. They are imported as `draft` with `is_functional = TRUE` on every test
case. A Python harness (not yet implemented) will bridge the functional format
to the Docker sandbox in a future additive capability.

---

## Private Test Cases — Decoding Pipeline

The `private_test_cases` field of each LiveCodeBench record uses a three-layer
encoding stack:

```
Base64 → zlib decompress → pickle.loads (protocol 4) → JSON parse → list[dict]
```

**Trust boundary:** The decoder in `app/question_bank/decoder.py` uses
`pickle.loads`, which executes arbitrary Python. This is only safe because:

1. The import script is offline-only (not exposed via any API or web endpoint).
2. The dataset file is SHA-256 verified before import.
3. The decoder is never called from user-supplied input.

The `# noqa: S301` annotation documents this trust boundary explicitly.

---

## Database Schema (Migration 006)

### New columns on `questions`

| Column | Type | Default | Purpose |
|---|---|---|---|
| `status` | VARCHAR(20) | `'draft'` | Lifecycle state |
| `input_format` | TEXT | NULL | Extracted Input section |
| `output_format` | TEXT | NULL | Extracted Output section |
| `constraints_text` | TEXT | NULL | Extracted Constraints block |
| `supported_languages` | JSON | NULL | `["python","cpp","java"]` etc. |
| `starter_code` | TEXT | NULL | Language-specific starter template |

### New columns on `question_test_cases`

| Column | Type | Default | Purpose |
|---|---|---|---|
| `is_sample` | BOOLEAN | `false` | TRUE = visible to candidate |
| `is_functional` | BOOLEAN | `false` | TRUE = functional testtype (LeetCode) |
| `tc_order` | INTEGER | NULL | Explicit evaluation ordering |

### New tables

- **`question_provenance`** — Dataset source, platform, contest, license, version.
- **`question_llm_lineage`** — LLM generation origin, model, parent question link.

All changes are fully additive. No existing columns, constraints, or
relationships are modified.

---

## Local Setup

### 1. Obtain the dataset

```powershell
# Option A: automated download + SHA-256 verification
cd backend
python scripts/download_livecodebench.py

# Option B: manual placement
# Place LiveCodeBench.jsonl at:
#   data/question_bank/livecodebench/LiveCodeBench.jsonl
# Verify SHA-256:
#   BB4C364F71921C4495A6AD15ABE1A927350B720009F4933E2E71F8AF0F6FD1F5
```

### 2. Apply the migration

```powershell
cd backend
python -m alembic upgrade head
```

### 3. Run the importer

```powershell
cd backend
# Preview (no writes)
python scripts/import_livecodebench.py --dry-run

# Full import
python scripts/import_livecodebench.py

# Custom dataset path
python scripts/import_livecodebench.py --path /path/to/LiveCodeBench.jsonl

# Verbose logging
python scripts/import_livecodebench.py --verbose
```

The importer is **idempotent**. Running it multiple times will not create
duplicate records. Already-imported questions are detected via
`question_provenance` and skipped.

---

## LLM-Generated Questions (Future)

The schema already supports LLM-generated and adapted questions in the same
normalized model:

- Curated questions: `question_llm_lineage.origin = 'curated'`
- Generated questions: `origin = 'generated'`, `model` and `generation_timestamp` populated
- Adapted questions: `origin = 'adapted'`, `parent_question_id` points to source

LLM-generated questions **always start at `draft`** and cannot be
auto-promoted. A human admin must advance them to `approved` → `active`.
This preserves the MATACSS design boundary: LLM outputs are advisory only and
never override official evaluation records.

---

## Files

| File | Purpose |
|---|---|
| `backend/app/question_bank/__init__.py` | Package marker |
| `backend/app/question_bank/decoder.py` | Base64/zlib/pickle/JSON decode pipeline |
| `backend/app/question_bank/normalizer.py` | Record → NormalizedQuestion |
| `backend/app/question_bank/importer.py` | Streaming, idempotent persistence |
| `backend/scripts/import_livecodebench.py` | CLI entry point |
| `backend/scripts/download_livecodebench.py` | Dataset download + SHA-256 verify |
| `backend/alembic/versions/006_question_bank.py` | Database migration |
| `backend/app/models/question.py` | Extended Question model |
| `backend/app/models/question_test_case.py` | Extended QuestionTestCase model |
| `backend/app/models/question_provenance.py` | New QuestionProvenance model |
| `backend/app/models/question_llm_lineage.py` | New QuestionLlmLineage model |
| `backend/tests/test_question_bank.py` | 71 unit tests (18 categories) |
| `data/question_bank/livecodebench/.gitkeep` | Preserves directory in Git |
