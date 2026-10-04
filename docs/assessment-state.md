# Assessment State contract

`app.schemas.assessment_state.AssessmentState` is a typed, immutable, sanitized
point-in-time view of one interview. It is the hand-off contract used by the
LangGraph orchestration service; it is not a persistence model or a separate
source of truth.

`build_assessment_state(session, interview_session_id)` in
`app.services.assessment_state_service` derives the snapshot from the existing
ordered-assignment service and assessment-results service. PostgreSQL/SQLAlchemy
models remain the only source of truth; this state is never persisted.

The contract includes interview and candidate IDs, lifecycle timestamps, ordered
public question context, first-unattempted current question for active sessions,
progress, and latest submission/evaluation identifiers, statuses, timestamps,
and aggregate scores. It deliberately excludes candidate PII, submission source,
stdin/stdout/stderr, test cases and expected outputs, Docker details, and
credentials.

Validation enforces unique ascending assignment ordering, progress consistency,
the latest-attempt/evaluation relationship, and lifecycle rules: active sessions
have no completion time and select their first unattempted question; completed
and cancelled sessions require a completion time and have no current question.
Empty and fully attempted active sessions have no current question.
