import type { AgentFeedback, AgentFeedbackValue, QuestionResult } from "@/types";

interface AgentFeedbackPanelProps {
  entries: AgentFeedback[];
  questions: QuestionResult[];
}

const textKeys = new Set([
  "summary",
  "message",
  "interviewer_message",
  "correctness_summary",
  "reason",
  "rationale",
]);
const listKeys = new Set([
  "observations",
  "improvement_suggestions",
  "suggestions",
  "guidance",
  "categories",
]);
const sensitiveOrError = /\b(?:api[_ -]?key|access[_ -]?token|bearer\s|password|secret|private[_ -]?key|traceback|stack trace|(?:provider|openai|anthropic|google|azure|bedrock).{0,40}(?:error|exception|fail)|(?:error|exception).{0,40}(?:provider|openai|anthropic|google|azure|bedrock))\b|sk-[A-Za-z0-9_-]{8,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/i;
const rawException = /^\s*(?:error|exception|traceback|valueerror|typeerror|keyerror)\s*:/i;

function safeAdvisoryText(value: string): string | null {
  const text = value.trim();
  if (!text || sensitiveOrError.test(text) || rawException.test(text)) return null;
  return text.length > 1000 ? `${text.slice(0, 997)}…` : text;
}

function isObject(value: AgentFeedbackValue): value is { [key: string]: AgentFeedbackValue } {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function extractAdvisory(value: AgentFeedbackValue): string[] {
  const output = new Set<string>();
  const visit = (current: AgentFeedbackValue, parentKey = "") => {
    if (typeof current === "string") {
      if (!parentKey || textKeys.has(parentKey)) {
        const safe = safeAdvisoryText(current);
        if (safe) output.add(safe);
      } else if (listKeys.has(parentKey)) {
        const safe = safeAdvisoryText(current);
        if (safe) output.add(safe);
      }
      return;
    }
    if (Array.isArray(current)) {
      current.forEach((item) => visit(item, parentKey));
      return;
    }
    if (!isObject(current)) return;
    for (const [key, child] of Object.entries(current)) {
      if (textKeys.has(key) || listKeys.has(key)) {
        visit(child, key);
      } else if (
        (key === "interviewer_decision" ||
          key === "code_review" ||
          key === "edge_case_generation" ||
          key === "feedback") &&
        isObject(child)
      ) {
        visit(child);
      } else if (key === "cases" && Array.isArray(child)) {
        for (const item of child) {
          if (isObject(item) && typeof item.category === "string") {
            const safe = safeAdvisoryText(item.category);
            if (safe) output.add(`Suggested category: ${safe}`);
          }
          if (isObject(item) && typeof item.rationale === "string") {
            const safe = safeAdvisoryText(item.rationale);
            if (safe) output.add(safe);
          }
        }
      } else if (
        (key === "assessment" ||
          key === "question" ||
          key === "code_quality" ||
          key === "edge_cases") &&
        isObject(child)
      ) {
        visit(child);
      }
    }
  };
  visit(value);
  return [...output];
}

export function AgentFeedbackPanel({ entries, questions }: AgentFeedbackPanelProps) {
  const titleBySubmission = new Map(
    questions
      .filter((question) => question.latest_submission_id)
      .map((question) => [
        question.latest_submission_id as string,
        `Question ${question.sequence_number}: ${question.title}`,
      ]),
  );

  return (
    <section className="agent-feedback-panel" aria-label="Advisory agent feedback">
      <div className="agent-feedback-heading">
        <div>
          <span className="eyebrow">ADVISORY FEEDBACK</span>
          <h2>Agent observations</h2>
        </div>
        <span className="advisory-badge">Not official correctness or scoring</span>
      </div>
      <p className="agent-feedback-disclaimer">
        These observations are advisory only. Deterministic execution and test-case scores above
        remain the only official correctness results. Suggested edge cases are not hidden tests
        and are not verified.
      </p>
      {entries.length === 0 ? (
        <p className="agent-feedback-empty">No agent feedback is available for this report.</p>
      ) : (
        <div className="agent-feedback-list">
          {entries.map((entry) => {
            const notes = entry.status === "completed"
              ? [
                  ...extractAdvisory(entry.interviewer_decision),
                  ...extractAdvisory(entry.code_review),
                  ...extractAdvisory(entry.edge_case_generation),
                  ...extractAdvisory(entry.feedback),
                ]
              : [];
            const uniqueNotes = [...new Set(notes)];
            return (
              <article className="agent-feedback-entry" key={`${entry.submission_id}-${entry.created_at}`}>
                <div className="agent-feedback-entry-heading">
                  <strong>
                    {titleBySubmission.get(entry.submission_id) ??
                      `Submission ${entry.submission_id.slice(0, 8)}`}
                  </strong>
                  <span className={`feedback-status feedback-status-${entry.status}`}>
                    {entry.status === "completed" ? "Advisory feedback available" : "Feedback unavailable"}
                  </span>
                </div>
                {entry.status === "failed" ? (
                  <p className="agent-feedback-empty">
                    Advisory feedback could not be generated. No provider diagnostics are shown.
                  </p>
                ) : uniqueNotes.length > 0 ? (
                  <ul>
                    {uniqueNotes.map((note, index) => <li key={`${index}-${note}`}>{note}</li>)}
                  </ul>
                ) : (
                  <p className="agent-feedback-empty">
                    Feedback completed, but no safe advisory text is available to display.
                  </p>
                )}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
