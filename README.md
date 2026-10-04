<div align="center">

# MATACSS

### Multi-Agent Technical Assessment & Code Sandboxing System

**An adaptive technical-assessment platform with a LangGraph multi-agent foundation, an LLM provider foundation, secure Docker execution, deterministic evaluation, and PostgreSQL-backed assessment state.**

[![Next.js](https://img.shields.io/badge/Next.js-000000?logo=next.js&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-1f6feb)](https://langchain-ai.github.io/langgraph/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Sandbox-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Monaco](https://img.shields.io/badge/Monaco-Editor-007ACC)](https://microsoft.github.io/monaco-editor/)

</div>

---

## ✦ What is MATACSS?

MATACSS is designed as an **AI-assisted technical interview and coding assessment platform**.

Instead of treating an assessment as a simple sequence of fixed coding questions, MATACSS combines:

| Layer | Responsibility |
|---|---|
| 🧠 **LLM Provider** | OpenAI and Azure OpenAI provider foundation; agent connections are the next implementation phase |
| 🔀 **LangGraph** | Multi-agent orchestration, state flow, and validated handoffs |
| 📚 **Question Engine** | Curated Question Bank with validated lifecycle; LLM generation/adaptation is a future source |
| 🛡️ **Docker Sandbox** | Isolated execution of untrusted candidate code |
| ✅ **Deterministic Evaluator** | Official correctness and scoring |
| 🗄️ **PostgreSQL** | Durable assessment and execution state |
| 🖥️ **Next.js + Monaco** | Candidate-facing assessment workspace |
| ⚡ **FastAPI + Workers** | API layer and asynchronous execution lifecycle |

> **Core principle:** The LLM provider foundation is not yet connected to the agents. Docker provides the execution boundary; deterministic tests remain the authority for correctness.

---

## 🚀 Architecture

```mermaid
flowchart TD
    A[Candidate] --> B[Next.js + Monaco Workspace]
    B --> C[FastAPI Backend]

    C --> D[LangGraph Orchestrator]

    D --> I[Interviewer Agent]
    D --> R[Code Reviewer Agent]
    D --> E[Edge-Case Agent]
    D --> F[Feedback Aggregator]

    I --> Q[Question Engine]
    Q --> QB[(PostgreSQL Question Bank)]
    Q --> LG[LLM Question Generation / Adaptation]
    QB --> V[Question Validation]
    LG --> V

    V --> B
    B --> S[Submission API]
    S --> J[Durable Execution Job]
    J --> W[Execution Worker]
    W --> X[Docker Sandbox]
    X --> T[Deterministic Test Evaluation]

    T --> DB[(PostgreSQL)]
    R --> DB
    E --> DB
    F --> DB
    T --> O[Assessment Results]
    F --> O
    O --> B
```

### Architecture at a glance

```text
                         ┌──────────────────────┐
                         │      Candidate       │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │  Next.js + Monaco    │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │       FastAPI        │
                         └──────────┬───────────┘
                                    │
                         ┌──────────▼───────────┐
                         │      LangGraph       │
                         │   Multi-Agent Flow   │
                         └──────────┬───────────┘
                                    │
             ┌──────────────────────┼──────────────────────┐
             ▼                      ▼                      ▼
      Interviewer Agent      Code Reviewer Agent    Edge-Case Agent
             │                      │                      │
             └──────────────────────┼──────────────────────┘
                                    ▼
                          ┌────────────────────┐
                          │  Question Engine   │
                          └─────────┬──────────┘
                                    │
                       ┌────────────┴────────────┐
                       ▼                         ▼
                Question Bank              LLM Generation
                       │                         │
                       └────────────┬────────────┘
                                    ▼
                           Question Validation
                                    │
                                    ▼
                             Code Submission
                                    │
                                    ▼
                         Durable Execution Job
                                    │
                                    ▼
                             Execution Worker
                                    │
                                    ▼
                             Docker Sandbox
                                    │
                                    ▼
                         Deterministic Evaluation
                                    │
                         ┌──────────┴───────────┐
                         ▼                      ▼
                  Official Results          AI Feedback
                         │                      │
                         └──────────┬───────────┘
                                    ▼
                           Assessment Report
                                    │
                                    ▼
                              PostgreSQL
```

---

## 🧠 Multi-Agent System

MATACSS has a LangGraph multi-agent architecture foundation with Interviewer, Code Reviewer, and Edge-Case agent roles. These agents are **not yet connected to the real LLM provider**; connecting them is the next implementation phase.

### 1. Interviewer Agent

The Interviewer Agent is intended to drive assessment progression.

**Responsibilities**

- Select the next question based on assessment context.
- Use the question bank for reliable problem retrieval.
- Generate or adapt a new problem when the assessment requires it.
- Adjust topic and difficulty progression.
- Maintain interview context through LangGraph state.

### 2. Code Reviewer Agent

The Code Reviewer Agent is intended to analyze candidate submissions after execution.

**Responsibilities**

- Review algorithmic approach.
- Identify potential correctness risks.
- Analyze time and space complexity.
- Identify implementation and maintainability issues.
- Produce structured technical feedback.

### 3. Edge-Case Agent

The Edge-Case Agent is intended to search for weaknesses that may not be covered by the original visible examples.

**Responsibilities**

- Analyze constraints and candidate code.
- Identify boundary conditions.
- Propose additional edge cases.
- Send candidate cases through the execution/validation boundary.
- Distinguish generated cases from verified cases.

### 4. Feedback Aggregator

The orchestration foundation includes feedback aggregation to combine agent outputs while keeping deterministic correctness separate from AI reasoning.

---

## 📚 Intelligent Question Engine

MATACSS currently uses a curated Question Bank, with LiveCodeBench as its dataset source. LLM generation and adaptation are planned as an additional source; generated or imported questions must pass validation before they become usable.

```text
                    Question Engine
                          │
             ┌────────────┴────────────┐
             ▼                         ▼
       Question Bank                    LLM Generation (future)
             │                         │
             └────────────┬────────────┘
                          ▼
                 Question Validation
                          │
                          ▼
                  Approved Question
```

A question can contain:

```text
question_id
 title
description
difficulty
topics
constraints
input_format
output_format
examples
expected_language
starter_code
reference_solution
test_cases
metadata
source
```

The Question Bank stores question provenance and lifecycle status. Questions follow this lifecycle:

```text
draft → validated → approved → active → deprecated
```

- **draft** — not assignable
- **validated** — automated validation passed
- **approved** — human/admin approval
- **active** — assignable; only active questions can be assigned
- **deprecated** — retired

### LiveCodeBench dataset

The current import contains **175 records**: **112 AtCoder** problems and **63 LeetCode** problems. AtCoder problems use stdin/stdout evaluation. LeetCode functional questions remain in draft because the functional execution harness is not yet implemented. The raw 128 MB+ JSONL dataset is not committed to Git and is SHA-256 verified before import.

### LLM provider foundation

MATACSS has an LLM provider abstraction with direct OpenAI and Azure OpenAI configuration, deployment/model configuration, and timeout/error handling. Credentials remain backend-side. The provider is not yet connected to the Interviewer, Code Reviewer, or Edge-Case agents.

---

## 🛡️ Secure Code Execution

Candidate source code is **untrusted input** and is never executed directly by the API process.

Each submission is executed inside a short-lived Docker sandbox with defense-in-depth controls:

- 🔒 Network disabled
- 👤 Non-root numeric user
- 📦 Read-only root filesystem
- 🗂️ Restricted temporary filesystem
- 🚫 No host bind mounts or Docker socket
- ⛔ `no-new-privileges`
- 🧩 Linux capabilities dropped
- 💾 Memory, CPU, and PID limits
- ⏱️ Execution timeout
- 📤 Bounded stdout/stderr capture
- 📌 Fixed runtime commands and source paths
- 🔄 Safe stdin transfer
- 🧹 Forced container cleanup

### Supported languages

| Language | Runtime | Execution boundary |
|---|---|---|
| Python | Python runtime image | Docker sandbox |
| C++ | GCC runtime image | Docker sandbox |
| Java | JDK runtime image | Docker sandbox |

> Docker is responsible for **safe execution**, not for deciding whether a solution is correct.

---

## ✅ Deterministic Evaluation

The official evaluator is intentionally independent of LLM reasoning.

```text
Candidate Code
      │
      ▼
Docker Execution
      │
      ▼
stdout / stderr / exit code
      │
      ▼
Official Test Cases
      │
      ▼
Exact Output Comparison
      │
      ▼
Deterministic Score
```

This separation prevents a language model from declaring an incorrect program correct simply because its explanation sounds convincing.

### Evaluation principles

- Official test cases are authoritative.
- Output comparison is deterministic.
- Execution failures are represented explicitly.
- AI feedback does not override official scoring.

---

## 🗃️ PostgreSQL Data Model

PostgreSQL acts as the durable system of record for the assessment platform.

Core data includes:

```text
Candidates
   │
   └── Interview Sessions
          │
          ├── Question Assignments
          │       │
          │       └── Question Bank
          │
          ├── Submissions
          │       │
          │       └── Execution Jobs
          │
          └── Assessment Results

Questions
   └── Test Cases

Evaluations
Agent / assessment metadata
```

Structured relational data is used for authoritative state, while flexible metadata can be represented in PostgreSQL JSONB where appropriate.

---

## 🔄 End-to-End Assessment Flow

The following describes the intended end-to-end flow; connecting the agent roles to the real LLM provider and completing LLM question generation are still planned.

1. **Candidate starts an assessment.**
2. **Interviewer Agent** reads the assessment context.
3. **Question Engine** retrieves or generates a suitable problem.
4. **Question Validation** checks the problem and executable test coverage.
5. Candidate receives the problem in the **Monaco workspace**.
6. Candidate submits code and optional standard input.
7. A durable execution job is created in **PostgreSQL**.
8. The **Execution Worker** processes the job.
9. **Docker Sandbox** executes the submission safely.
10. **Deterministic Evaluation** calculates official correctness.
11. **Code Reviewer Agent** analyzes the implementation.
12. **Edge-Case Agent** proposes additional boundary cases.
13. Verified execution data and AI feedback are combined into the assessment report.
14. **Next.js** presents question results and technical feedback.

---

## ⚙️ Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | Next.js, React, TypeScript, Monaco Editor |
| Backend | FastAPI, Python, SQLAlchemy, Pydantic, Alembic |
| Agent Orchestration | LangGraph |
| AI Layer | OpenAI/Azure OpenAI provider foundation; agent connections are planned |
| Database | PostgreSQL |
| Execution | Docker |
| Async Processing | Durable job queue + execution worker |
| Evaluation | Deterministic test-case execution |

---

## 🚧 Implementation Status

**Implemented**

- FastAPI backend and Next.js/Monaco frontend
- PostgreSQL persistence
- Docker sandbox and deterministic evaluation
- Durable execution jobs and workers
- Authentication and role-based access control (RBAC)
- LangGraph orchestration foundation
- Question Bank with LiveCodeBench import and validation
- LLM provider foundation for OpenAI and Azure OpenAI

**Next implementation phase**

- Connect the Interviewer Agent to the real LLM provider
- Connect the Code Reviewer Agent to the real LLM provider
- Connect the Edge-Case Agent to the real LLM provider
- Complete LLM-driven question generation and adaptation
- Complete remaining functional evaluation support where required

---

## 🧱 Repository Structure

```text
MATACSS/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── orchestration/
│   │   ├── question_bank/
│   │   ├── schemas/
│   │   └── services/
│   │
│   ├── alembic/
│   ├── scripts/
│   └── tests/
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   └── types/
│
├── docs/
└── README.md
```

---

## 🧪 Testing and CI

From the `backend/` directory, run the backend tests with:

```bash
python -m pytest tests --ignore=tests/integration -q
```

The project uses automated backend and frontend CI validation. This describes the validation setup and does not indicate the status of any particular CI run.

---

## 🧪 Local Development

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

### Worker

```powershell
cd backend
python scripts/run_worker.py
```

### Health check

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

---

## 🎯 Project Goal

MATACSS is intended to move technical assessments from a **static question → code → score** workflow toward an **adaptive, reasoning-driven technical interview**.

### The central design idea

```text
LLM Agents
   → reasoning & personalization

LangGraph
   → orchestration & state flow

Question Engine
   → retrieval & generation

Docker
   → secure execution

Deterministic Evaluation
   → trustworthy correctness

PostgreSQL
   → durable assessment state
```

---

## 🌟 Why MATACSS?

MATACSS brings together several systems that are often implemented separately:

**Generative AI** + **Multi-Agent Systems** + **LangGraph** + **Secure Code Sandboxing** + **Deterministic Evaluation** + **Technical Assessment Analytics**

into one end-to-end platform for adaptive programming assessments.

---

<div align="center">

### MATACSS
**Reason. Execute. Verify. Assess.**

</div>
