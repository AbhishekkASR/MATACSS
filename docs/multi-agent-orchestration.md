# Multi-Agent Orchestration foundation

Step 30 coordinates the deterministic Interviewer, Code Reviewer, and
Edge-Case Generator foundations without adding an LLM or a second assessment
model.

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

Step 32 adds a bounded `feedback_aggregator` node after the orchestrator. It
combines assessment, question, static-review, and edge-case outputs into one
final typed feedback result while preserving deterministic evaluation as the
only source of truth for correctness and score. The feedback layer is advisory
only and never writes persistence or mutates evaluation data.

## Security and persistence boundaries

The coordinator validates every handoff and provider result. It does not
execute candidate code, call Docker, access PostgreSQL, persist agent output,
modify scores/evaluations, or expose hidden tests, hidden outputs,
credentials, Docker internals, unrestricted database objects, or unnecessary
candidate PII.

All providers remain deterministic and dependency-injectable. Real LLM
integration, autonomous behavior, AI-output persistence, and generated-case
verification/execution remain future work.
