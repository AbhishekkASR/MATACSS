# Interviewer Agent

The bounded Interviewer Agent runs in the existing LangGraph orchestration
layer. It presents only the authoritative current assigned question, or returns
a safe non-question decision when an assessment is closed, empty, or fully
attempted. On a completed attempt it may also return a constrained advisory
continue/finish recommendation with optional topic, difficulty, and language
characteristics.

The node accepts the immutable `AssessmentState` and returns an immutable
`InterviewerDecision`. A presentation decision can include only the assigned
current question ID, sequence/index, title, public prompt, a concise reason,
and an optional candidate-facing message. It excludes candidate PII, source
code, submission output, test cases, expected outputs, credentials, and Docker
data.

`InterviewerProvider` is the injected provider boundary. The deterministic
provider uses only the supplied state. When a current question exists, the
agent validates every provider selection against assignments and rejects
selections outside the assessment or away from the current question. When all
assigned questions have been attempted, a provider may return only a
continuation recommendation; it cannot select a future question ID. The
Question Engine resolves that recommendation against active, non-repeated
questions.

The production orchestration service can use the configured OpenAI/Azure
provider through this narrow protocol. Recommendations and presentation
messages remain advisory; the agent has no persistence, execution, scoring, or
question-activation authority.
