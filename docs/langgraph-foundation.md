# LangGraph foundation

Step 26 adds a minimal, deterministic LangGraph foundation in
`app.orchestration.assessment_graph`. It has no API route, database writes,
checkpointer, provider SDK, or network call.

The graph flow is:

```text
START -> assessment_context -> interviewer -> prepare_real_assessment_context
     -> code_reviewer -> prepare_edge_case_context -> edge_case_generator
     -> orchestrator -> feedback_aggregator -> END
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
an explicit `not_run` result). Step 29 adds a bounded deterministic Edge-Case
Generator after the reviewer. Step 30 adds explicit review and edge-case
handoff preparation plus a typed deterministic coordinator result. Step 32 adds
a bounded feedback aggregator that combines assessment, review, edge-case, and
interviewer outputs while keeping official execution/evaluation results as the
source of truth for correctness and score. The workflow remains deterministic,
non-persistent, and non-executing.

The graph never calls Docker, never writes to PostgreSQL, and never mutates the
official test-case or evaluation records. Real LLM integration, autonomous
behavior, AI-output persistence, and generated-case verification remain future
work.
