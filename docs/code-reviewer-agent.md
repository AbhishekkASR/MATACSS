# Code Reviewer Agent foundation

Step 28 adds a bounded Code Reviewer Agent node to the existing LangGraph
orchestration layer. It performs deterministic static review only; it is not an
execution, evaluation, persistence, or submission-retrieval service.

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

`CodeReviewerProvider` is the injected future real-LLM integration boundary.
The current `DeterministicCodeReviewerProvider` requires no API key or network
access. It uses Python's standard-library parser for Python syntax, recognizes
empty source and a few conservative structural/readability signals, and treats
C++/Java as text without claiming to parse or prove their correctness. It never
executes candidate code.

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
authority. A future real LLM provider must implement the same narrow protocol
and remain subject to these validation boundaries.
