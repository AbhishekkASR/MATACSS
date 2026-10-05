::: {align="center"}
# 🚀 MATACSS

### Multi-Agent Technical Assessment & Code Sandboxing System

**An AI-assisted technical interview platform combining multi-agent
reasoning, secure code execution, and deterministic evaluation.**

`<br>`{=html}

![MATACSS](https://img.shields.io/badge/MATACSS-Multi--Agent%20Technical%20Assessment%20%26%20Code%20Sandboxing%20System-0F172A?style=for-the-badge)

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.x-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Sandbox-2496ED?style=flat-square&logo=docker&logoColor=white)](https://www.docker.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Orchestration-FF6B6B?style=flat-square)](https://github.com/langchain-ai/langgraph)

`<br>`{=html}

> **Reason. Execute. Verify. Assess.**
:::

------------------------------------------------------------------------

## 🧭 What is MATACSS?

**MATACSS** is an AI-assisted technical interview and coding-assessment
platform designed around a strict separation between **AI reasoning and
official code correctness**.

The system combines:

-   🧠 **LangGraph multi-agent orchestration**
-   📚 **Question Bank & Question Engine**
-   🛡️ **Restricted Docker code execution**
-   ✅ **Deterministic executable evaluation**
-   🤖 **AI-powered advisory feedback**
-   🗃️ **PostgreSQL durable state**
-   🔐 **JWT authentication and role-aware authorization**

The core principle is:

> **LLMs make the assessment experience smarter. Deterministic execution
> decides whether the code is correct.**

------------------------------------------------------------------------

# 🎯 Why MATACSS?

Technical assessment platforms need to balance **intelligence, security,
reliability, and reproducibility**.

  -----------------------------------------------------------------------
  Challenge                           MATACSS Approach
  ----------------------------------- -----------------------------------
  Intelligent assessment              LangGraph multi-agent workflow

  Reliable questions                  Question Bank + lifecycle
                                      validation

  Question selection                  Dedicated Question Engine

  Untrusted candidate code            Restricted Docker sandbox

  Objective grading                   Deterministic executable tests

  AI feedback                         Separate advisory layer

  Durable state                       PostgreSQL + Alembic

  Authentication                      JWT + role-aware access control

  Traceability                        Persistent submissions,
                                      evaluations, provenance and lineage
  -----------------------------------------------------------------------

MATACSS deliberately separates **reasoning**, **execution**, and
**correctness**.

------------------------------------------------------------------------

# 🏗️ System Architecture

``` mermaid
flowchart TD
    Candidate[Candidate] --> Frontend[Next.js + Monaco Editor]
    Frontend --> API[FastAPI API]

    API --> DB[(PostgreSQL)]
    API --> Engine[Question Engine]
    Engine --> Bank[Question Bank]

    API --> Submission[Code Submission]
    Submission --> Job[Execution Job]
    Job --> Worker[Execution Worker]
    Worker --> Sandbox[Restricted Docker Sandbox]
    Sandbox --> Evaluation[Deterministic Evaluation]
    Evaluation --> Result[Official Result]

    API --> Graph[LangGraph Orchestration]
    Graph --> Interviewer[Interviewer Agent]
    Graph --> Reviewer[Code Reviewer Agent]
    Graph --> EdgeCases[Edge-Case Agent]

    Interviewer --> Feedback[AI Advisory Feedback]
    Reviewer --> Feedback
    EdgeCases --> Feedback

    Result --> Report[Assessment Report]
    Feedback --> Report
    DB --> Report
```

## Architectural Responsibilities

  -----------------------------------------------------------------------
  Layer                               Responsibility
  ----------------------------------- -----------------------------------
  **Next.js + Monaco**                Candidate-facing interview and
                                      coding experience

  **FastAPI**                         API, authentication, interview
                                      lifecycle and persistence

  **LangGraph**                       Multi-agent orchestration and
                                      validated state flow

  **Question Engine**                 Question retrieval, assignment and
                                      lifecycle-aware selection

  **Question Bank**                   Assessment questions, test cases,
                                      provenance and lineage

  **Execution Worker**                Durable execution-job processing

  **Docker Sandbox**                  Restricted environment for
                                      untrusted candidate code

  **Deterministic Evaluator**         Official correctness and scoring

  **PostgreSQL**                      Durable system state

  **AI Feedback**                     Advisory reasoning that complements
                                      official results
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 🧠 Multi-Agent Assessment System

MATACSS uses a bounded **LangGraph-based multi-agent workflow**.

### 🎤 Interviewer Agent

Provides a structured recommendation about whether the assessment should
continue or finish according to the current assessment state.

### 🔍 Code Reviewer Agent

Provides advisory analysis of submitted code using the available
assessment context.

### 🧪 Edge-Case Agent

Reasons about:

-   boundary conditions
-   potential hidden-test weaknesses
-   edge cases
-   possible failure scenarios

### 📝 Feedback Aggregator

Combines validated advisory outputs into structured assessment feedback.

### Important architectural rule

The agents are **advisory**.

They do **not** determine official code correctness.

``` text
LLM Reasoning
      │
      ▼
Advisory Feedback
      │
      ▼
Assessment Report

Official correctness
      ▲
      │
Deterministic Evaluation
```

------------------------------------------------------------------------

# 📚 Intelligent Question Bank

MATACSS maintains a structured Question Bank with lifecycle controls:

``` text
draft
  │
  ▼
validated
  │
  ▼
approved
  │
  ▼
active
  │
  ▼
deprecated
```

Questions can contain:

-   problem statement
-   title
-   difficulty
-   expected language
-   constraints
-   examples
-   starter code
-   executable test cases
-   provenance metadata
-   source information
-   LLM lineage
-   lifecycle status

## Question Engine

The Question Engine handles:

-   active-question retrieval
-   question assignment
-   repeat prevention
-   supported difficulty filtering
-   supported language filtering
-   question lifecycle checks
-   generated/adapted question validation

------------------------------------------------------------------------

# 📊 LiveCodeBench Integration

MATACSS uses **LiveCodeBench as an external question source** for the
Question Bank.

Imported content is normalized into MATACSS structures while preserving
source and provenance information.

The dataset is treated as a **source of assessment content**, while
MATACSS maintains its own question lifecycle and validation rules.

> Generated or adapted questions must pass validation before entering
> the approved assessment flow.

------------------------------------------------------------------------

# 🛡️ Secure Code Execution

Candidate code is treated as **untrusted input**.

MATACSS executes submissions inside short-lived Docker containers with
multiple defense-in-depth controls.

### Sandbox Controls

-   🌐 Network disabled
-   👤 Non-root execution (`65532:65532`)
-   🔒 Read-only root filesystem
-   📁 Bounded writable `/tmp`
-   🚫 `nosuid` / `nodev` protections where implemented
-   🚫 `no-new-privileges`
-   🧱 Dropped Linux capabilities
-   💾 Memory limits
-   ⚡ CPU limits
-   🔢 PID limits
-   ⏱️ Execution timeout
-   📤 Bounded stdout/stderr
-   📌 Fixed runtime commands and source paths
-   🧹 Container cleanup and teardown
-   🚫 No host Docker socket
-   🚫 No host bind-mount access

These controls form a **defense-in-depth execution boundary**. They are
not a claim that every possible Docker or host escape is impossible.

------------------------------------------------------------------------

# ⚙️ Deterministic Evaluation

MATACSS separates **execution** from **correctness**.

``` text
Candidate Submission
        │
        ▼
Persist Submission
        │
        ▼
Execution Job
        │
        ▼
Execution Worker
        │
        ▼
Docker Sandbox
        │
        ▼
Executable Test Cases
        │
        ▼
Deterministic Evaluation
        │
        ▼
Official Result
```

The result produced by deterministic evaluation is the **authoritative
assessment result**.

AI-generated feedback cannot override it.

> **AI explains. Tests decide.**

------------------------------------------------------------------------

# 🤖 AI Feedback

After deterministic evaluation, the multi-agent system can provide
advisory analysis around:

-   code quality
-   reasoning concerns
-   edge cases
-   hidden-test weaknesses
-   interview continuation recommendations
-   assessment observations

The feedback is persisted separately from the official evaluation.

``` text
Official Result
       +
AI Advisory Feedback
       │
       ▼
Assessment Report
```

------------------------------------------------------------------------

# 🔐 Authentication & Durable State

MATACSS includes JWT-based authentication and role-aware authorization.

### Security & State

-   JWT authentication
-   configurable JWT algorithm
-   configurable token expiry
-   role-aware protected endpoints
-   production configuration validation
-   backend-safe CORS configuration
-   PostgreSQL durable state
-   Alembic schema migrations

PostgreSQL acts as the durable system of record for the assessment
lifecycle.

------------------------------------------------------------------------

# 🔄 End-to-End Assessment Flow

``` text
Candidate
   │
   ▼
Interview
   │
   ▼
Question Engine
   │
   ▼
Active Question
   │
   ▼
Monaco Editor
   │
   ▼
Code Submission
   │
   ▼
Execution Job
   │
   ▼
Docker Sandbox
   │
   ▼
Executable Test Cases
   │
   ▼
Deterministic Evaluation
   │
   ├──────────────► Official Result
   │
   ▼
LangGraph Agents
   │
   ▼
AI Feedback
   │
   ▼
Assessment Report
```

### Core workflow

**Select → Solve → Execute → Verify → Explain → Assess**

------------------------------------------------------------------------

# 🧰 Technology Stack

  -----------------------------------------------------------------------
  Category                            Technologies
  ----------------------------------- -----------------------------------
  **Frontend**                        Next.js, React, TypeScript, Monaco
                                      Editor

  **Backend**                         FastAPI, Python, Pydantic

  **AI Orchestration**                LangGraph

  **Database**                        PostgreSQL

  **ORM**                             SQLAlchemy

  **Migrations**                      Alembic

  **Execution**                       Docker

  **LLM Provider Foundation**         Azure OpenAI / OpenAI-compatible
                                      configuration

  **Testing**                         Pytest, frontend lint/build checks

  **CI/CD**                           GitHub Actions where present
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 🚧 Implementation Status

## ✅ Implemented

-   FastAPI backend
-   Next.js frontend
-   Monaco coding interface
-   Candidate management
-   Interview lifecycle
-   Question Bank
-   Question Engine
-   Question lifecycle validation
-   LiveCodeBench integration
-   Persistent submissions
-   Durable execution jobs
-   Execution worker
-   Restricted Docker sandbox
-   Deterministic evaluation
-   Assessment results
-   Assessment feedback
-   LangGraph orchestration
-   Interviewer Agent
-   Code Reviewer Agent
-   Edge-Case Agent
-   Feedback aggregation
-   Azure/OpenAI provider foundation
-   JWT authentication
-   Role-aware authorization
-   PostgreSQL persistence
-   Alembic migrations
-   Production configuration validation
-   Security hardening
-   Automated backend/frontend verification

------------------------------------------------------------------------

# 🧪 Verified Engineering Status

The implementation has been verified through automated and integration
testing.

### Verification completed

-   **315 backend tests passed**
-   **29 PostgreSQL/Docker integration tests passed**
-   Frontend lint passed
-   Frontend build and TypeScript checks passed
-   Python compilation passed
-   `git diff --check` passed
-   Alembic has a single current migration head
-   Real Docker execution verified
-   Deterministic evaluation verified
-   LangGraph advisory feedback persisted
-   End-to-end assessment flow verified

### Verified assessment path

``` text
Submission
    ↓
Execution Job
    ↓
Docker
    ↓
Deterministic Evaluation
    ↓
Official Result
    ↓
LangGraph Advisory Feedback
    ↓
Assessment Completion
```

------------------------------------------------------------------------

# 🗺️ Future Roadmap

The following are **future directions**, not claims about the current
implementation.

## Intelligence

-   Adaptive interviewing
-   Dynamic difficulty rebalancing
-   Deeper autonomous question generation
-   More advanced multi-stage reasoning workflows

## Scale

-   Larger distributed execution infrastructure
-   Additional worker orchestration capabilities
-   Production-scale operational tooling

## Platform

-   Expanded assessment analytics
-   More advanced reviewer workflows
-   Additional programming-language support
-   Further security and infrastructure hardening

------------------------------------------------------------------------

# 🛠️ Local Development

## 1. Configure the backend

``` powershell
Copy-Item backend/.env.example backend/.env
```

Configure:

-   PostgreSQL
-   JWT settings
-   Docker execution settings
-   optional LLM provider settings

**Never commit real credentials or API keys.**

## 2. Start the development stack

``` powershell
docker compose --env-file backend/.env -f backend/docker-compose.yml up --build -d
```

## 3. Check services

``` powershell
docker compose --env-file backend/.env -f backend/docker-compose.yml ps
```

For schema changes, MATACSS uses Alembic migrations against the
configured PostgreSQL database.

------------------------------------------------------------------------

# 🧱 Repository Structure

``` text
MATACSS/
│
├── backend/
│   ├── app/
│   ├── alembic/
│   ├── scripts/
│   ├── tests/
│   ├── .env.example
│   ├── docker-compose.yml
│   └── requirements.txt
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── lib/
│   └── package.json
│
├── data/
├── docs/
├── .github/
├── README.md
└── .gitignore
```

------------------------------------------------------------------------

# 🎯 Design Principle

MATACSS is built around a strict architectural boundary:

``` text
                    AI
             Reason & Explain
                     │
                     ▼
             LangGraph Agents
                     │
                     ▼
             Assessment Logic
                     │
                     ▼
              Code Execution
                     │
                     ▼
              Docker Sandbox
                     │
                     ▼
          Deterministic Evaluation
                     │
                     ▼
               Official Result
```

### The philosophy

> **AI makes the assessment smarter.\
> Deterministic execution keeps it trustworthy.**

------------------------------------------------------------------------

# 🌟 Why MATACSS is Different

MATACSS is not simply an LLM wrapper around a coding editor.

It combines several engineering boundaries:

``` text
┌─────────────────────────────────────┐
│        Intelligent Assessment      │
│          LangGraph Agents           │
├─────────────────────────────────────┤
│         Question Intelligence       │
│       Question Bank + Engine        │
├─────────────────────────────────────┤
│          Secure Execution           │
│          Docker Sandbox             │
├─────────────────────────────────────┤
│         Objective Evaluation        │
│      Deterministic Test Engine      │
├─────────────────────────────────────┤
│          Durable State              │
│            PostgreSQL               │
└─────────────────────────────────────┘
```

The goal is to combine **AI reasoning with software-engineering
discipline** rather than allowing AI to become the grading authority.

------------------------------------------------------------------------

# 🔮 Project Vision

MATACSS is being developed toward a complete technical assessment
platform where:

``` text
Question Selection
       ↓
Candidate Interview
       ↓
Secure Code Execution
       ↓
Deterministic Evaluation
       ↓
Multi-Agent Analysis
       ↓
Assessment Report
```

can operate as one reliable, traceable system.

The long-term objective is not simply to add more AI.

It is to build a system where **AI reasoning, secure execution,
deterministic evaluation, and durable engineering architecture work
together.**

------------------------------------------------------------------------

::: {align="center"}
# MATACSS

### Reason. Execute. Verify. Assess.

**AI-assisted assessment with deterministic correctness.**
:::
