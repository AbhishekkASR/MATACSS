# Interviewer Agent foundation

Step 27 adds a bounded Interviewer Agent node to the existing LangGraph
orchestration layer. Its sole responsibility is choosing presentation context
for the current assigned question, or returning a safe non-question decision
when an assessment is closed, empty, or fully attempted.

The node accepts the Step 25 immutable `AssessmentState` and returns an
immutable `InterviewerDecision`. The output can include only an assigned current
question ID, sequence/index, title, public prompt, a concise reason, and an
optional candidate-facing message. It excludes candidate PII, source code,
submission output, test cases, expected outputs, credentials, and Docker data.

`InterviewerProvider` is a small injected protocol for future provider-backed
selection. The current `DeterministicInterviewerProvider` uses only the supplied
state and selects the state-defined current question. The agent validates every
provider selection against assigned questions and rejects selections outside the
assessment or away from the current question.

The graph is now:

```text
START -> assessment_context -> interviewer -> END
```

There is no provider SDK, API key, network call, database write, Docker call,
question generation, adaptive difficulty, code review, scoring, or autonomous
workflow in this step. A future real LLM provider must implement the same narrow
protocol and remain subject to the agent's output validation.
