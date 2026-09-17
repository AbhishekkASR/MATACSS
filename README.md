MATACSS

Multi-Agent Technical Assessment & Code Sandboxing System

MATACSS is an AI-powered technical assessment platform that combines multi-agent reasoning, a structured coding-question bank, secure code execution, deterministic evaluation, and personalized candidate feedback in a single assessment workflow.

The platform is designed around a clear separation of responsibilities:

LLM agents handle question selection/generation, code reasoning, review, and edge-case reasoning.

LangGraph orchestrates the multi-agent workflow and validates agent handoffs.

PostgreSQL stores candidates, assessment sessions, questions, submissions, test cases, evaluations, and assessment results.

Docker provides the isolated execution boundary for untrusted candidate code.

Deterministic evaluation remains the authority for whether submitted code passes the official test cases.

Next.js + Monaco provide the candidate-facing coding workspace.

FastAPI exposes the backend APIs and coordinates the assessment lifecycle.

Architecture

                         MATACSS
                            │
                    ┌───────▼────────┐
                    │    LangGraph   │
                    │ Multi-Agent AI │
                    └───────┬────────┘
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
          ▼                 ▼                 ▼
   Interviewer Agent  Code Reviewer Agent  Edge-Case Agent
          │                 │                 │
          └─────────────────┼─────────────────┘
                            │
                    ┌───────▼────────┐
                    │ Question Engine│
                    └───────┬────────┘
                            │
                ┌───────────┴───────────┐
                │                       │
                ▼                       ▼
          Question Bank            LLM Generation
                │                       │
                └───────────┬───────────┘
                            ▼
                  Question Validation
                            │
                            ▼
                    Candidate Assessment
                            │
                     Code Submission
                            │
                            ▼
                    Docker Sandbox
                            │
                            ▼
                 Deterministic Evaluation
                            │
                 ┌──────────┴──────────┐
                 ▼                     ▼
           Official Results      AI Feedback
                 │                     │
                 └──────────┬──────────┘
                            ▼
                  Assessment Report

        ┌─────────────────────────────────────────┐
        │              PostgreSQL                 │
        │ candidates • sessions • questions       │
        │ submissions • test cases • evaluations │
        │ results • assessment metadata          │
        └─────────────────────────────────────────┘

Core Workflow

1. Candidate starts an assessment

The platform loads the candidate profile, assessment context, and historical performance relevant to the session.

2. Interviewer Agent selects or generates the next question

The Interviewer Agent uses the assessment context and question bank to select an appropriate problem. The LLM can also generate or adapt a problem when the workflow requires a new challenge.

3. Question validation

Generated or adapted questions pass through validation before they are used in an assessment. Validation covers structure, constraints, expected behavior, reference material, and executable test coverage.

4. Candidate solves the problem

The candidate works inside the Monaco-based coding workspace and can submit Python, C++, or Java solutions.

5. Docker Sandbox executes the submission

Every submission is executed inside a short-lived isolated container with resource and security restrictions.

6. Deterministic evaluation decides correctness

Official test cases remain the source of truth. The platform compares execution results against expected outputs and produces a deterministic score.

7. Code Reviewer Agent analyzes the submission

The Code Reviewer Agent reasons about the submitted code, including algorithmic approach, complexity, implementation risks, maintainability, and potential correctness issues.

8. Edge-Case Agent searches for weaknesses

The Edge-Case Agent analyzes the problem, code, and review context and proposes additional edge cases. Candidate-generated cases are treated as advisory until they are verified by the execution/evaluation pipeline.

9. Assessment report is generated

The system combines deterministic execution results and AI-generated analysis into an assessment report containing performance, code-quality feedback, edge-case observations, and question-level results.

Multi-Agent Responsibilities

Interviewer Agent

Responsibilities:

Select an appropriate question from the question bank.

Adapt difficulty and topic progression to assessment context.

Generate a new question when the workflow requires one.

Maintain interview progression through LangGraph state.

Code Reviewer Agent

Responsibilities:

Analyze submitted source code.

Identify correctness risks.

Review algorithmic complexity.

Identify code-quality and maintainability issues.

Produce structured review feedback.

Edge-Case Generator Agent

Responsibilities:

Analyze problem constraints and candidate code.

Identify missing boundary conditions.

Generate candidate edge cases.

Pass cases to the execution/validation boundary for verification.

Feedback Aggregator

Responsibilities:

Combine structured agent outputs.

Keep AI feedback separate from deterministic correctness.

Produce a consistent question-level and assessment-level feedback model.

Question Bank

The question engine is backed by a structured PostgreSQL question bank.

Each question can contain:

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

The question bank supports both reliable assessment content and LLM-assisted question generation/selection.

The intended question lifecycle is:

Question Bank
      │
      ├── Retrieval / selection
      │
      └── LLM generation or adaptation
                    │
                    ▼
             Question Validation
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
       Structure         Executable tests
       validation            │
          │                   ▼
          └────────────► Docker execution
                              │
                              ▼
                       Approved question

Secure Code Execution

Candidate code is treated as untrusted input and is never executed directly on the API host.

Docker provides the execution boundary with controls including:

Network isolation

Non-root execution

Read-only root filesystem

Restricted temporary filesystem

Dropped Linux capabilities

no-new-privileges

CPU, memory, and PID limits

Execution timeout

Bounded stdout/stderr capture

Fixed runtime commands

Safe stdin handling

Short-lived containers

Forced cleanup after execution

Supported languages:

Python

C++

Java

Docker is responsible for safe execution. It does not make assessment decisions.

Deterministic Evaluation

The official evaluator remains independent of LLM reasoning.

A submission is evaluated against authoritative test cases using exact normalized output comparison.

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
Deterministic Score

This separation prevents an LLM from declaring an incorrect program correct merely because the reasoning sounds convincing.

Technology Stack

Frontend

Next.js

React

TypeScript

Monaco Editor

Backend

FastAPI

Python

SQLAlchemy

Pydantic

Alembic

AI / Agent Layer

LangGraph

LLM-powered Interviewer Agent

LLM-powered Code Reviewer Agent

LLM-powered Edge-Case Agent

Structured feedback aggregation

Database

PostgreSQL

Execution Infrastructure

Docker

Isolated short-lived execution containers

Durable asynchronous execution jobs

Worker-based execution lifecycle

Data Flow

Candidate
   │
   ▼
Next.js + Monaco
   │
   ▼
FastAPI
   │
   ├──────────────► PostgreSQL
   │
   ▼
LangGraph Assessment Workflow
   │
   ├── Interviewer Agent
   ├── Code Reviewer Agent
   ├── Edge-Case Agent
   └── Feedback Aggregator
   │
   ▼
Submission Job Queue
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
   ├──────────────► PostgreSQL
   │
   ▼
Assessment Results
   │
   ▼
Next.js Results UI

Why This Architecture

MATACSS intentionally separates intelligence from execution and correctness:

LLM / Agents
    = reasoning, personalization, generation, review

Docker
    = isolated execution

Deterministic evaluator
    = official correctness

PostgreSQL
    = durable application state

LangGraph
    = agent orchestration and state flow

This makes the platform capable of using LLM reasoning without allowing model output to become the unchecked source of truth for code execution or assessment correctness.

API and Application Layers

The FastAPI backend coordinates:

Authentication and authorization

Candidate management

Interview lifecycle

Question management

Question assignment

Submission creation

Durable execution jobs

Worker processing

Docker sandbox execution

Deterministic evaluation

Agent orchestration

Assessment results

The Next.js application provides:

Assessment workspace

Monaco code editor

Language selection

Standard input

Execution status

Submission history

Question navigation

Assessment results

AI feedback presentation

Project Goal

MATACSS is designed to provide a complete AI-assisted technical assessment workflow rather than a simple online code runner.

The central idea is:

Use LLMs for reasoning and personalization, LangGraph for agent orchestration, PostgreSQL for durable assessment state, Docker for safe code execution, and deterministic evaluation for trustworthy correctness.

Repository Structure

MATACSS/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   ├── orchestration/
│   │   ├── schemas/
│   │   └── services/
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

Development

Backend

cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m uvicorn app.main:app --reload

Frontend

cd frontend
npm install
npm run dev

Worker

cd backend
python scripts/run_worker.py

Project Vision

MATACSS combines:

Generative AI + Multi-Agent Systems + Secure Code Execution + Deterministic Evaluation + Technical Assessment Analytics

into one end-to-end platform for adaptive programming interviews and technical assessments.
