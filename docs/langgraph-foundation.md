# LangGraph foundation

Step 26 adds a minimal, deterministic LangGraph foundation in
`app.orchestration.assessment_graph`. It has no API route, database writes,
checkpointer, provider SDK, or network call.

The graph flow is:

```text
START -> assessment_context -> interviewer -> code_reviewer -> END
```

`AssessmentState` remains the sole application-level assessment snapshot.
The graph uses a small `TypedDict` adapter containing that immutable snapshot
and a `context_initialized` marker. The graph boundary revalidates the snapshot
before execution (including Pydantic models constructed without validation), and
the context node revalidates it again for direct graph use. The node returns the
same safe information without mutating it or writing it anywhere.

Step 27 adds the bounded Interviewer Agent after `assessment_context`; it uses
an injected deterministic provider and returns only a validated presentation
decision. Step 28 adds the Code Reviewer Agent after the interviewer. It accepts
only explicitly supplied review input and returns a validated static review (or
an explicit `not_run` result). The Edge-Case Generator remains unimplemented.
No real LLM integration is present.
