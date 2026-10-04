# Agent assessment integration

The assessment orchestration service connects the multi-agent graph to persisted
MATACSS assessments. The graph uses configured OpenAI/Azure providers and
retained the existing deterministic evaluation as the official score source.

## Application boundary

`assessment_orchestration_service` is the only integration layer. It:

1. Builds the immutable `AssessmentState` using
   `build_assessment_state`.
2. Uses the authoritative latest-submission service for the selected/current
   assigned question.
3. Uses the existing evaluation/results service for safe aggregate status,
   score, and passed/total counts.
4. Produces the existing narrow `CodeReviewInput` only when a submission
   exists.
5. Produces safe `EdgeCaseGeneratorInput` containing public question context
   and evaluation aggregates.

The service validates interview lifecycle, assignment boundaries, submission
interview/question ownership, and supported language before invoking the
graph.

## Data boundaries

Candidate source code is present only in `CodeReviewInput`. It is never copied
into `AssessmentState`, edge-case input, orchestration results, or persistence
by the orchestration layer. Hidden test cases, expected hidden outputs,
credentials, Docker internals, candidate PII, and ORM/database objects are
not passed to agents.

No agent receives a database session and no agent can write persistence,
execute code, call Docker, mutate evaluation/scoring, or persist generated
outputs. A separate feedback service persists validated agent results per
submission, including provider failure state, without changing official
evaluation data. Existing submission execution and evaluation services remain
the only authorized mechanisms for execution and scoring.

## Graph integration

```text
START
  -> assessment_context
  -> interviewer
  -> prepare_real_assessment_context
  -> code_reviewer
  -> prepare_edge_case_context
  -> edge_case_generator
  -> orchestrator
  -> END
```

The orchestration remains bounded by typed contracts. Candidate-authenticated
assessment routes call the existing Question Engine to resolve persisted
continue/finish recommendations. Generated edge cases remain unverified and
are not added to official test cases or evaluation.
