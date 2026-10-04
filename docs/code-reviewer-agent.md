# Code Reviewer Agent

The bounded Code Reviewer Agent runs in the existing LangGraph orchestration
layer. It provides advisory static analysis after deterministic evaluation; it
is not an execution, evaluation, or submission-retrieval service.

`CodeReviewInput` is explicitly prepared by the caller and contains only a
question ID, matching public title/prompt, language, candidate source code, and
an optional safe aggregate execution/evaluation summary. It forbids additional
fields, so hidden test cases, expected outputs, credentials, Docker data, and
candidate PII cannot enter this contract. Source code is deliberately absent
from `AssessmentState` and is never fetched by the agent.

`CodeReviewResult` is immutable and bounded. It includes an explicit review
status, question ID when review ran, a conservative correctness summary,
categorized/severity-tagged static observations, suggestions, and a reason. It
never contains source code or hidden evaluation information.

`CodeReviewerProvider` is the injected provider boundary. A deterministic
provider remains available for local/test operation; configured OpenAI and
Azure OpenAI implementations can return structured advisory static-review
observations. Neither provider executes candidate code. Deterministic
evaluation, not LLM analysis, remains authoritative for correctness and score.

The agent validates the assessment snapshot, review input, matching assigned
public question context, and provider output. It rejects reviews for unassigned
questions or malformed provider results. If no review input is supplied, or the
assessment is closed, it returns a structured `not_run` result without calling
the provider.

The graph flow is:

```text
START -> assessment_context -> interviewer -> code_reviewer -> END
```

The reviewer has no Docker, Docker-socket, PostgreSQL, worker, execution,
evaluation, scoring, question-generation, authentication, or autonomous-action
authority. Provider output remains bounded by the same typed validation
boundaries.
