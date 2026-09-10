"use client";

import { useEffect, useMemo, useState } from "react";

import { CodeEditor } from "@/components/editor/CodeEditor";
import { OutputPanel } from "@/components/execution/OutputPanel";
import { ProblemPanel } from "@/components/problem/ProblemPanel";
import { ResultsPanel } from "@/components/results/ResultsPanel";
import {
  ApiRequestError,
  getAssessmentResults,
  getAssignedQuestions,
  getInterview,
  getLatestSubmission,
  getSubmissionAttempts,
  getSubmissionStatus,
  submitCode,
} from "@/lib/api";
import type {
  AssignedQuestion,
  CodeSubmissionResponse,
  ExecutionOutput,
  InterviewSession,
  Language,
  Problem,
  SubmissionAttempt,
  AssessmentResults,
} from "@/types";

const starterCode: Record<Language, string> = {
  python: "print('Write your solution here')\n",
  cpp: '#include <iostream>\n\nint main() {\n    // Write your solution here\n    return 0;\n}\n',
  java: "public class Main {\n    public static void main(String[] args) {\n        // Write your solution here\n    }\n}\n",
};

const demoInterviewSessionId =
  process.env.NEXT_PUBLIC_DEMO_INTERVIEW_SESSION_ID ?? "";

function toProblem(question: AssignedQuestion): Problem {
  return {
    title: question.title,
    description: question.description,
    difficulty: question.difficulty,
    expectedLanguage: question.expected_language ?? "python",
  };
}

function toExecutionOutput(attempt: SubmissionAttempt): ExecutionOutput {
  return {
    status: attempt.status,
    stdout: attempt.stdout,
    stderr: attempt.stderr,
    exitCode: attempt.exit_code,
    executionTimeMs: attempt.execution_time_ms,
    timedOut: attempt.timed_out,
  };
}

export default function Home() {
  const [interview, setInterview] = useState<InterviewSession | null>(null);
  const [questions, setQuestions] = useState<AssignedQuestion[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [sourceByQuestion, setSourceByQuestion] = useState<Record<string, string>>(
    {},
  );
  const [stdinByQuestion, setStdinByQuestion] = useState<Record<string, string>>({});
  const [language, setLanguage] = useState<Language>("python");
  const [output, setOutput] = useState<ExecutionOutput | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attemptCountByQuestion, setAttemptCountByQuestion] = useState<
    Record<string, number>
  >({});
  const [results, setResults] = useState<AssessmentResults | null>(null);
  const [showResults, setShowResults] = useState(false);
  const [isResultsLoading, setIsResultsLoading] = useState(false);
  const [resultsError, setResultsError] = useState<string | null>(null);

  const currentQuestion = questions[currentIndex] ?? null;
  const sourceCode = currentQuestion
    ? sourceByQuestion[currentQuestion.question_id] ??
      starterCode[currentQuestion.expected_language ?? "python"]
    : "";
  const stdin = currentQuestion
    ? stdinByQuestion[currentQuestion.question_id] ?? ""
    : "";
  const problem = currentQuestion ? toProblem(currentQuestion) : null;

  useEffect(() => {
    let cancelled = false;

    async function loadAssessment() {
      if (!demoInterviewSessionId) {
        setError("Configure a real demo interview session ID before loading the assessment.");
        setIsLoading(false);
        return;
      }

      try {
        const [interviewResponse, questionResponse] = await Promise.all([
          getInterview(demoInterviewSessionId),
          getAssignedQuestions(demoInterviewSessionId),
        ]);
        if (cancelled) return;

        setInterview(interviewResponse);
        setQuestions(questionResponse);
        setSourceByQuestion(
          Object.fromEntries(
            questionResponse.map((question) => [
              question.question_id,
              starterCode[question.expected_language ?? "python"],
            ]),
          ),
        );
        if (questionResponse[0]?.expected_language) {
          setLanguage(questionResponse[0].expected_language);
        }
        setError(null);
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof ApiRequestError
              ? loadError.message
              : "The assessment could not be loaded.",
          );
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void loadAssessment();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!interview || !currentQuestion) return;
    let cancelled = false;
    const interviewSessionId = interview.interview_session_id;
    const questionId = currentQuestion.question_id;

    async function loadLatestAttempt() {
      try {
        const [latest, attempts] = await Promise.all([
          getLatestSubmission(interviewSessionId, questionId),
          getSubmissionAttempts(interviewSessionId, questionId),
        ]);
        if (cancelled) return;
        setAttemptCountByQuestion((current) => ({
          ...current,
          [questionId]: attempts.length,
        }));
        setOutput(latest ? toExecutionOutput(latest) : null);
      } catch (attemptError) {
        if (!cancelled) {
          setOutput(null);
          setError(
            attemptError instanceof ApiRequestError
              ? attemptError.message
              : "Submission history could not be loaded.",
          );
        }
      }
    }

    void loadLatestAttempt();
    return () => {
      cancelled = true;
    };
  }, [currentQuestion, interview]);

  function changeQuestion(nextIndex: number) {
    if (nextIndex < 0 || nextIndex >= questions.length || nextIndex === currentIndex) {
      return;
    }
    const nextQuestion = questions[nextIndex];
    setCurrentIndex(nextIndex);
    setOutput(null);
    setError(null);
    if (nextQuestion.expected_language) {
      setLanguage(nextQuestion.expected_language);
    }
  }

  function handleLanguageChange(nextLanguage: Language) {
    setLanguage(nextLanguage);
  }

  function handleSourceChange(nextSource: string) {
    if (!currentQuestion) return;
    setSourceByQuestion((current) => ({
      ...current,
      [currentQuestion.question_id]: nextSource,
    }));
  }

  function handleStdinChange(nextStdin: string) {
    if (!currentQuestion) return;
    setStdinByQuestion((current) => ({
      ...current,
      [currentQuestion.question_id]: nextStdin,
    }));
  }

  async function loadResults(interviewSessionId: string) {
    setIsResultsLoading(true);
    setResultsError(null);
    try {
      setResults(await getAssessmentResults(interviewSessionId));
    } catch (resultsLoadError) {
      setResultsError(
        resultsLoadError instanceof ApiRequestError
          ? resultsLoadError.message
          : "Assessment results could not be loaded.",
      );
    } finally {
      setIsResultsLoading(false);
    }
  }

  async function handleResultsToggle() {
    const nextShowResults = !showResults;
    setShowResults(nextShowResults);
    if (nextShowResults && interview) {
      await loadResults(interview.interview_session_id);
    }
  }

  async function handleRunCode() {
    if (isRunning) return;
    if (!interview || interview.status !== "active") {
      setError("This interview is not active.");
      return;
    }
    if (!currentQuestion) {
      setError("There are no assigned questions to run.");
      return;
    }
    if (!sourceCode.trim()) {
      setError("Source code cannot be empty.");
      return;
    }

    setIsRunning(true);
    setError(null);
    const interviewSessionId = interview.interview_session_id;
    const questionId = currentQuestion.question_id;

    try {
      const result: CodeSubmissionResponse = await submitCode({
        interview_session_id: interviewSessionId,
        question_id: questionId,
        language,
        source_code: sourceCode,
        stdin,
      });

      setOutput({
        status: "queued",
        stdout: "",
        stderr: "",
        exitCode: null,
        executionTimeMs: null,
        timedOut: false,
      });
      setAttemptCountByQuestion((current) => ({
        ...current,
        [questionId]: (current[questionId] ?? 0) + 1,
      }));
      let finalStatus = await getSubmissionStatus(result.submission_id);
      let pollCount = 0;
      while (finalStatus.job_status === "queued" || finalStatus.job_status === "running") {
        if (pollCount++ >= 120) {
          throw new ApiRequestError("Execution is taking longer than expected.");
        }
        await new Promise((resolve) => setTimeout(resolve, 500));
        finalStatus = await getSubmissionStatus(result.submission_id);
        setOutput({
          status: finalStatus.submission_status,
          stdout: finalStatus.stdout ?? "",
          stderr: finalStatus.stderr ?? "",
          exitCode: finalStatus.exit_code,
          executionTimeMs: finalStatus.execution_time_ms,
          timedOut: finalStatus.timed_out ?? false,
        });
      }
      if (finalStatus.job_status === "failed") {
        throw new ApiRequestError("The execution worker could not complete the submission.");
      }
      setOutput({
        status: finalStatus.submission_status,
        stdout: finalStatus.stdout ?? "",
        stderr: finalStatus.stderr ?? "",
        exitCode: finalStatus.exit_code,
        executionTimeMs: finalStatus.execution_time_ms,
        timedOut: finalStatus.timed_out ?? false,
      });
      setInterview(await getInterview(interviewSessionId));
      if (showResults) {
        await loadResults(interviewSessionId);
      }
    } catch (submissionError) {
      setOutput(null);
      setError(
        submissionError instanceof ApiRequestError
          ? submissionError.message
          : "The submission could not be completed.",
      );
    } finally {
      setIsRunning(false);
    }
  }

  const questionPosition = useMemo(
    () => (questions.length > 0 ? currentIndex + 1 : 0),
    [currentIndex, questions.length],
  );
  const isInactive = interview !== null && interview.status !== "active";

  return (
    <main className="workspace">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">M</span>
          <div>
            <strong>MATACSS</strong>
            <span>Technical Assessment Workspace</span>
          </div>
        </div>
        <div className="session-status">
          <span className="status-dot" aria-hidden="true" />
          {interview?.status === "active" ? "Workspace ready" : "Assessment unavailable"}
          {interview && (
            <button type="button" className="results-button" onClick={() => void handleResultsToggle()}>
              {showResults ? "Back to workspace" : "View results"}
            </button>
          )}
        </div>
      </header>

      {isLoading ? (
        <div className="assessment-state">Loading assessment…</div>
      ) : (
        showResults ? (
          <div className="results-layout">
            <ResultsPanel results={results} isLoading={isResultsLoading} error={resultsError} />
          </div>
        ) : (
        <div className="workspace-grid">
          <aside className="problem-column">
            {problem ? (
              <ProblemPanel
                problem={problem}
                questionNumber={questionPosition}
                totalQuestions={questions.length}
              />
            ) : (
              <section className="problem-panel">
                <span className="eyebrow">ASSESSMENT</span>
                <h1>No assigned questions</h1>
                <p>This interview does not have any questions assigned yet.</p>
              </section>
            )}
            <div className="workflow-card">
              <span className="eyebrow">ASSESSMENT</span>
              <p>
                Read the prompt, implement your solution, and run it when the execution
                service is connected.
              </p>
            </div>
          </aside>

          <section className="coding-column" aria-label="Code editor">
            {problem && currentQuestion ? (
              <>
                <div className="editor-toolbar">
                  <div className="file-label">
                    <span className="file-dot" aria-hidden="true" />
                    solution.
                    {language === "python" ? "py" : language === "cpp" ? "cpp" : "java"}
                  </div>
                  <label className="language-control">
                    <span>Language</span>
                    <select
                      value={language}
                      onChange={(event) =>
                        handleLanguageChange(event.target.value as Language)
                      }
                      aria-label="Select programming language"
                    >
                      <option value="python">Python</option>
                      <option value="cpp">C++</option>
                      <option value="java">Java</option>
                    </select>
                  </label>
                </div>
                <div className="editor-shell">
                  <CodeEditor
                    language={language}
                    value={sourceCode}
                    onChange={handleSourceChange}
                  />
                </div>
                <label className="stdin-control">
                  <span>Standard input</span>
                  <textarea
                    value={stdin}
                    onChange={(event) => handleStdinChange(event.target.value)}
                    placeholder="Optional input for your program"
                    rows={3}
                  />
                </label>
                <div className="question-navigation" aria-label="Question navigation">
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={currentIndex === 0}
                    onClick={() => changeQuestion(currentIndex - 1)}
                  >
                    Previous
                  </button>
                  <span>Question {questionPosition} of {questions.length}</span>
                  <span>
                    Attempts: {attemptCountByQuestion[currentQuestion.question_id] ?? 0}
                  </span>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={currentIndex === questions.length - 1}
                    onClick={() => changeQuestion(currentIndex + 1)}
                  >
                    Next
                  </button>
                </div>
                <div className="run-bar">
                  <span className="run-note">
                    {isInactive
                      ? "This interview is no longer active."
                      : "Execution uses the configured assessment context."}
                  </span>
                  <button
                    type="button"
                    className="run-button"
                    disabled={isRunning || isInactive}
                    onClick={handleRunCode}
                  >
                    <span aria-hidden="true">▶</span>
                    {isRunning ? "Running..." : "Run Code"}
                  </button>
                </div>
                {error && <p className="error-message" role="alert">{error}</p>}
                <OutputPanel output={output} />
              </>
            ) : (
              <>
                {error && <p className="error-message" role="alert">{error}</p>}
                <section className="output-panel">
                  <div className="output-empty">
                    {error ? "The assessment is unavailable." : "No assigned questions are available."}
                  </div>
                </section>
              </>
            )}
          </section>
        </div>
        )
      )}
    </main>
  );
}
