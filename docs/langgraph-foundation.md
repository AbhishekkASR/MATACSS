# LangGraph foundation

`app.orchestration.assessment_graph` implements the bounded LangGraph
orchestration used by the assessment service. Its public runtime state is the
sanitized `AssessmentState`; configured provider calls are made through the
existing OpenAI/Azure abstraction.

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

The Interviewer presents only the current assigned question and can return a
constrained next-step recommendation. The Code Reviewer accepts only
explicitly prepared source and public question context; the Edge-Case Generator
returns bounded, unverified proposals. Typed handoffs and a bounded feedback
aggregator preserve official execution/evaluation results as the sole source of
truth for correctness and score.

The graph never calls Docker, accesses PostgreSQL, or mutates official
test-case/evaluation records. The application service persists advisory graph
outputs per submission. Generated cases remain unverified and are not used for
scoring; autonomous test verification is not implemented.
