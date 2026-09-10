import type { AssessmentResults, QuestionResult } from "@/types";

interface ResultsPanelProps {
  results: AssessmentResults | null;
  isLoading: boolean;
  error: string | null;
}

function questionStatus(question: QuestionResult): string {
  if (question.evaluation_status === "evaluated") return "Evaluated";
  if (question.evaluation_status === "attempted_not_evaluated") {
    return "Attempted · awaiting evaluation";
  }
  return "Not attempted";
}

export function ResultsPanel({ results, isLoading, error }: ResultsPanelProps) {
  if (isLoading) {
    return <section className="results-panel"><div className="output-empty">Loading results…</div></section>;
  }
  if (error) {
    return <section className="results-panel"><p className="error-message">{error}</p></section>;
  }
  if (!results) return null;

  return (
    <section className="results-panel" aria-label="Assessment results">
      <div className="results-header">
        <div>
          <span className="eyebrow">ASSESSMENT RESULTS</span>
          <h1>{results.status === "scored" ? `${results.overall_score?.toFixed(1)}%` : "Not scored yet"}</h1>
        </div>
        <div className="results-summary">
          <span>Attempted {results.attempted_questions}/{results.total_questions}</span>
          <span>Evaluated {results.evaluated_questions}/{results.total_questions}</span>
          <span>Tests {results.total_passed_test_cases}/{results.total_test_cases}</span>
        </div>
      </div>
      <div className="results-list">
        {results.questions.map((question) => (
          <div className="result-row" key={question.question_id}>
            <div>
              <strong>Question {question.sequence_number}: {question.title}</strong>
              <span>{questionStatus(question)}</span>
            </div>
            <div className="result-score">
              {question.evaluation_status === "evaluated"
                ? `${question.score?.toFixed(1)}% · ${question.passed_test_cases}/${question.total_test_cases} tests`
                : "—"}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
