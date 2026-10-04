import type { Problem } from "@/types";

interface ProblemPanelProps {
  problem: Problem;
  questionNumber?: number;
  totalQuestions?: number;
}

export function ProblemPanel({
  problem,
  questionNumber,
  totalQuestions,
}: ProblemPanelProps) {
  return (
    <section className="problem-panel" aria-labelledby="problem-title">
      <span className="eyebrow">
        {questionNumber && totalQuestions
          ? `QUESTION ${questionNumber} OF ${totalQuestions}`
          : "QUESTION"}
      </span>
      <h1 id="problem-title">{problem.title}</h1>
      <p>{problem.description}</p>
      <span className="difficulty">{problem.difficulty}</span>
      <div className="expected-language">
        <span>Expected language</span>
        <strong>{problem.expectedLanguage ?? "Any supported language"}</strong>
      </div>
      {(problem.inputFormat || problem.outputFormat || problem.constraints) && (
        <div className="question-contract">
          {problem.inputFormat && (
            <div>
              <h2>Input format</h2>
              <p>{problem.inputFormat}</p>
            </div>
          )}
          {problem.outputFormat && (
            <div>
              <h2>Output format</h2>
              <p>{problem.outputFormat}</p>
            </div>
          )}
          {problem.constraints && (
            <div>
              <h2>Constraints</h2>
              <p>{problem.constraints}</p>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
