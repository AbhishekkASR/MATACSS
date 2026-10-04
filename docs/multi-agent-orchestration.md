# Multi-Agent Orchestration foundation

The existing LangGraph flow coordinates the Interviewer, Code Reviewer, and
Edge-Case Generator using the immutable assessment snapshot and narrow provider
contracts. Configured OpenAI/Azure providers supply advisory outputs; the
deterministic providers remain injectable for tests and local use.

## Flow and handoffs

```text
START
  -> assessment_context
  -> interviewer
  -> prepare_review_context
  -> code_reviewer
  -> prepare_edge_case_context
  -> edge_case_generator
  -> orchestrator
  -> feedback_aggregator
  -> END
```

The coordinator keeps `AssessmentState` authoritative and immutable. The
Interviewer decision identifies the only valid question for the run.
`prepare_review_context` permits review only when explicitly supplied input
matches that selected question. `prepare_edge_case_context` passes only the
selected public question and safe reviewer/evaluation summaries.

The final typed result includes the assessment state, interviewer decision,
optional agent results, bounded execution statuses, and an orchestration
status. Closed assessments produce safe `not_run` outputs and do not invoke
inappropriate provider work.

Step 31 adds `assessment_orchestration_service`, an application boundary that
builds the immutable `AssessmentState` through the existing assessment-state
service, then obtains the selected question's latest submission and evaluation
through the existing submission/results services. The graph receives those
prepared values; agents never receive an `AsyncSession` or ORM object.

The bounded `feedback_aggregator` node combines assessment, question,
static-review, and edge-case outputs into one typed feedback result while
preserving deterministic evaluation as the only source of truth for correctness
and score. The feedback layer is advisory only and never mutates evaluation
data. A separate application service persists results per submission.

## Security and persistence boundaries

The coordinator validates every handoff and provider result. It does not
execute candidate code, call Docker, access PostgreSQL, modify
scores/evaluations, or expose hidden tests, hidden outputs, credentials, Docker
internals, unrestricted database objects, or unnecessary candidate PII.

The Interviewer may return a bounded continuation recommendation. The Question
Engine, not the model, resolves the next active, non-repeated question.
Generated edge cases remain unverified and are not official evaluation inputs.
