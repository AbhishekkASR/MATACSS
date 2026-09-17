# AI Evaluation / Feedback foundation

Step 32 adds a bounded feedback aggregation layer after the existing
`assessment_context -> interviewer -> prepare_real_assessment_context ->
code_reviewer -> prepare_edge_case_context -> edge_case_generator ->
orchestrator` flow.

## Graph flow

```text
START
  -> assessment_context
  -> interviewer
  -> prepare_real_assessment_context
  -> code_reviewer
  -> prepare_edge_case_context
  -> edge_case_generator
  -> orchestrator
  -> feedback_aggregator
  -> END
```

The aggregation step does not execute candidate code, call Docker, access the
PostgreSQL database, or modify evaluation/scoring state. It only combines the
authoritative `AssessmentState` snapshot, the selected interviewer decision,
optional static review output, optional generated edge cases, and the latest
safe deterministic summary already recorded in the assessment data.

## Responsibility

The feedback layer is intentionally conservative:

- deterministic evaluation remains the source of truth for pass/fail counts,
  execution status, score, and correctness
- static review and edge-case generation remain advisory observations
- AI/agent output must never contradict official execution results
- unverified generated edge cases remain unverified until a separate explicit
  verification flow is implemented

## Typed output contract

The feedback layer uses typed Pydantic models:

- `AssessmentFeedback`: official evaluation summary plus advisory observations
- `QuestionFeedback`: selected-question guidance without mutating question state
- `CodeQualityFeedback`: static-review-derived observations and suggestions
- `EdgeCaseFeedback`: candidate edge-case categories and unverified status
- `FeedbackAggregationResult`: the final single result for the graph invocation

The result is bounded by maximum observation counts, maximum suggestion counts,
maximum text length, and a maximum total payload; malformed or oversized output
is rejected.

## Precedence rules

1. official execution/evaluation status and score win over AI correctness claims
2. AI observations are clearly labeled as advisory/static only
3. generated edge cases are never auto-verified or inserted into the official set
4. missing agent output stays incomplete rather than being fabricated

## Security boundaries

The feedback layer has no persistence model, no agent credentials, no Docker
access, no direct database access, and no scoring mutation path. It strictly
consumes already-authoritative runtime snapshots and public agent outputs.

## Future work

Real LLM-backed feedback, autonomous explanation generation, and automatic
generated-case verification remain future work. This step implements only the
deterministic aggregation foundation and the safety boundaries around it.
