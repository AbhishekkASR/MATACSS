import type { EvaluationResult } from "@/types";

interface EvaluationPanelProps {
  evaluation: EvaluationResult | null;
  isLoading: boolean;
  error: string | null;
  onEvaluate: () => void;
  canEvaluate: boolean;
  onContinue: () => void;
  canContinue: boolean;
  isContinuing: boolean;
}

export function EvaluationPanel({
  evaluation,
  isLoading,
  error,
  onEvaluate,
  canEvaluate,
  onContinue,
  canContinue,
  isContinuing,
}: EvaluationPanelProps) {
  return (
    <section className="evaluation-panel" aria-label="Deterministic evaluation">
      <div className="evaluation-header">
        <div>
          <span className="eyebrow">DETERMINISTIC EVALUATION</span>
          <h2>
            {evaluation?.status === "scored"
              ? `${evaluation.score?.toFixed(1)}%`
              : evaluation
                ? "Not scored"
                : "Evaluation"}
          </h2>
        </div>
        {canEvaluate && (
          <button
            type="button"
            className="secondary-button"
            disabled={isLoading}
            onClick={onEvaluate}
          >
            {isLoading ? "Evaluating…" : evaluation ? "Recheck evaluation" : "Evaluate latest submission"}
          </button>
        )}
      </div>
      {error && <p className="error-message" role="alert">{error}</p>}
      {!evaluation && !isLoading && !error && (
        <p className="evaluation-note">
          Deterministic test-case feedback is available after execution completes.
        </p>
      )}
      {evaluation && (
        <p className="evaluation-summary">
          {evaluation.status === "scored"
            ? `${evaluation.passed_test_cases} of ${evaluation.total_test_cases} test cases passed.`
            : "No test cases are configured for this question, so this submission was not scored."}
        </p>
      )}
      {canContinue && (
        <button
          type="button"
          className="secondary-button"
          disabled={isContinuing}
          onClick={onContinue}
        >
          {isContinuing ? "Loading next question…" : "Next question"}
        </button>
      )}
    </section>
  );
}
