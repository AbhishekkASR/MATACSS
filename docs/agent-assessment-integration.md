# Agent assessment integration

Step 31 connects the deterministic multi-agent graph to a real MATACSS
assessment without changing the public API or persistence model.

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
outputs. Existing submission execution and evaluation services remain the
only authorized mechanisms for those operations.

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

The graph remains deterministic. Real LLM providers, authentication, new API
endpoints, AI-output persistence, autonomous execution, and generated-case
verification are intentionally deferred.
