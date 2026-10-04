"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { CodeEditor } from "@/components/editor/CodeEditor";
import { OutputPanel } from "@/components/execution/OutputPanel";
import { ProblemPanel } from "@/components/problem/ProblemPanel";
import { EvaluationPanel } from "@/components/results/EvaluationPanel";
import { ResultsPanel } from "@/components/results/ResultsPanel";
import {
  ApiRequestError,
  clearAccessToken,
  completeInterview,
  continueCandidateAssessment,
  evaluateSubmission,
  getAssessmentResults,
  getAssignedQuestions,
  getCurrentUser,
  getInterview,
  getLatestSubmission,
  getSubmissionAttempts,
  getSubmissionEvaluation,
  getSubmissionStatus,
  login,
  restoreAccessToken,
  resumeCandidateAssessment,
  setAccessToken,
  startCandidateAssessment,
  submitCode,
} from "@/lib/api";
import type {
  AssessmentQuestionDetails,
  AssessmentStartResponse,
  AssessmentResults,
  AssignedQuestion,
  AuthenticatedUser,
  EvaluationResult,
  ExecutionOutput,
  InterviewSession,
  Language,
  Problem,
  SubmissionAttempt,
  SubmissionStatus,
} from "@/types";

const supportedLanguages: Language[] = ["python", "cpp", "java"];
const languageLabels: Record<Language, string> = {
  python: "Python",
  cpp: "C++",
  java: "Java",
};
const sessionIdStorageKey = "matacss.interview_session_id";
const pollIntervalMs = 500;
const maxPolls = 120;

function starterCode(question: AssignedQuestion, language: Language): string {
  if (question.expected_language === language && question.starter_code) {
    return question.starter_code;
  }
  if (language === "python") return "def solution():\n    pass\n";
  if (language === "cpp") {
    return "#include <iostream>\n\nint main() {\n    return 0;\n}\n";
  }
  return "public class Main {\n    public static void main(String[] args) {\n    }\n}\n";
}

function toProblem(question: AssignedQuestion): Problem {
  return {
    title: question.title,
    description: question.description,
    difficulty: question.difficulty,
    expectedLanguage: question.expected_language,
    inputFormat: question.input_format,
    outputFormat: question.output_format,
    constraints: question.constraints_text,
  };
}

function withCurrentQuestion(
  details: AssessmentQuestionDetails,
  assignments: AssignedQuestion[],
): AssignedQuestion[] {
  const existing = assignments.find(
    (question) => question.question_id === details.question_id,
  );
  const currentQuestion: AssignedQuestion = {
    ...existing,
    ...details,
    sequence_number: existing?.sequence_number ?? 1,
    created_at: existing?.created_at ?? "",
  };
  const questions = existing
    ? assignments.map((question) =>
        question.question_id === details.question_id ? currentQuestion : question,
      )
    : [...assignments, currentQuestion];
  return questions.sort((left, right) => left.sequence_number - right.sequence_number);
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

function toStatusOutput(status: SubmissionStatus): ExecutionOutput {
  return {
    status: status.job_status === "failed" ? "sandbox_error" : status.submission_status,
    stdout: status.stdout ?? "",
    stderr: status.stderr ?? "",
    exitCode: status.exit_code,
    executionTimeMs: status.execution_time_ms,
    timedOut: status.timed_out ?? false,
  };
}

function isPending(status: SubmissionStatus): boolean {
  return status.job_status === "queued" || status.job_status === "running";
}

function languagesForQuestion(question: {
  supported_languages?: Language[] | null;
}): Language[] {
  if (!question.supported_languages) return supportedLanguages;
  return supportedLanguages.filter((language) =>
    question.supported_languages?.includes(language),
  );
}

export default function Home() {
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [isCheckingSession, setIsCheckingSession] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [interviewId, setInterviewId] = useState("");
  const [interview, setInterview] = useState<InterviewSession | null>(null);
  const [questions, setQuestions] = useState<AssignedQuestion[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [sourceByQuestion, setSourceByQuestion] = useState<
    Record<string, Partial<Record<Language, string>>>
  >({});
  const [stdinByQuestion, setStdinByQuestion] = useState<Record<string, string>>({});
  const [language, setLanguage] = useState<Language>("python");
  const [output, setOutput] = useState<ExecutionOutput | null>(null);
  const [activeSubmissionId, setActiveSubmissionId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [isLoadingAssessment, setIsLoadingAssessment] = useState(false);
  const [isContinuingAssessment, setIsContinuingAssessment] = useState(false);
  const [assessmentError, setAssessmentError] = useState<string | null>(null);
  const [attemptCountByQuestion, setAttemptCountByQuestion] = useState<
    Record<string, number>
  >({});
  const [evaluation, setEvaluation] = useState<EvaluationResult | null>(null);
  const [isEvaluating, setIsEvaluating] = useState(false);
  const [evaluationError, setEvaluationError] = useState<string | null>(null);
  const [showResults, setShowResults] = useState(false);
  const [results, setResults] = useState<AssessmentResults | null>(null);
  const [isResultsLoading, setIsResultsLoading] = useState(false);
  const [resultsError, setResultsError] = useState<string | null>(null);
  const attemptedAutoResumeId = useRef<string | null>(null);

  const currentQuestion = questions[currentIndex] ?? null;
  const allowedLanguages = useMemo(
    () => (currentQuestion ? languagesForQuestion(currentQuestion) : []),
    [currentQuestion],
  );
  const sourceCode = currentQuestion
    ? sourceByQuestion[currentQuestion.question_id]?.[language] ??
      starterCode(currentQuestion, language)
    : "";
  const stdin = currentQuestion
    ? stdinByQuestion[currentQuestion.question_id] ?? ""
    : "";
  const problem = currentQuestion ? toProblem(currentQuestion) : null;
  const isInactive = interview !== null && interview.status !== "active";

  const handleUnauthorized = useCallback((error: unknown): boolean => {
    if (!(error instanceof ApiRequestError) || error.status !== 401) return false;
    clearAccessToken();
    setUser(null);
    setInterview(null);
    setQuestions([]);
    setAuthError("Your sign-in has expired. Sign in again to continue.");
    return true;
  }, []);

  const loadResults = useCallback(async (interviewSessionId: string) => {
    setIsResultsLoading(true);
    setResultsError(null);
    try {
      setResults(await getAssessmentResults(interviewSessionId));
    } catch (error) {
      if (!handleUnauthorized(error)) {
        setResultsError(
          error instanceof ApiRequestError ? error.message : "Results could not be loaded.",
        );
      }
    } finally {
      setIsResultsLoading(false);
    }
  }, [handleUnauthorized]);

  const openCandidateAssessment = useCallback(async (response: AssessmentStartResponse) => {
    const [interviewResponse, assignments] = await Promise.all([
      getInterview(response.interview_session_id),
      getAssignedQuestions(response.interview_session_id),
    ]);
    const assessmentQuestions = response.current_question
      ? withCurrentQuestion(response.current_question, assignments)
      : assignments;
    const questionIndex = response.current_question
      ? assessmentQuestions.findIndex(
          (question) => question.question_id === response.current_question?.question_id,
        )
      : -1;
    setInterview(interviewResponse);
    setQuestions(assessmentQuestions);
    setCurrentIndex(Math.max(0, questionIndex >= 0 ? questionIndex : assessmentQuestions.length - 1));
    setInterviewId(response.interview_session_id);
    setOutput(null);
    setActiveSubmissionId(null);
    setEvaluation(null);
    setEvaluationError(null);
    setAttemptCountByQuestion({});
    window.sessionStorage.setItem(
      sessionIdStorageKey,
      response.interview_session_id,
    );
    if (response.current_question) {
      const languages = languagesForQuestion(response.current_question);
      setLanguage(
        response.current_question.expected_language &&
          languages.includes(response.current_question.expected_language)
          ? response.current_question.expected_language
          : languages[0] ?? "python",
      );
      setShowResults(false);
    } else {
      setShowResults(true);
      await loadResults(response.interview_session_id);
    }
  }, [loadResults]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(async () => {
      const storedInterviewId = window.sessionStorage.getItem(sessionIdStorageKey);
      if (storedInterviewId && !cancelled) setInterviewId(storedInterviewId);
      const token = restoreAccessToken();
      if (!token) {
        if (!cancelled) setIsCheckingSession(false);
        return;
      }
      try {
        const currentUser = await getCurrentUser();
        if (!cancelled) {
          setUser(currentUser);
          setAuthError(null);
        }
      } catch (error) {
        if (cancelled) return;
        clearAccessToken();
        setAuthError(
          error instanceof ApiRequestError && error.status === 401
            ? "Your previous sign-in expired. Sign in again."
            : error instanceof ApiRequestError
              ? error.message
              : "Your saved session could not be restored. Sign in again.",
        );
      } finally {
        if (!cancelled) setIsCheckingSession(false);
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!user || user.role !== "candidate" || interview) return;
    const storedInterviewId = window.sessionStorage.getItem(sessionIdStorageKey);
    if (!storedInterviewId || attemptedAutoResumeId.current === storedInterviewId) return;
    const sessionIdToResume = storedInterviewId;
    attemptedAutoResumeId.current = sessionIdToResume;
    let cancelled = false;

    async function resumeStoredAssessment() {
      setIsLoadingAssessment(true);
      setAssessmentError(null);
      try {
        let resumed: AssessmentStartResponse;
        try {
          resumed = await resumeCandidateAssessment(sessionIdToResume);
        } catch (error) {
          if (!(error instanceof ApiRequestError) || error.status !== 409) throw error;
          resumed = await continueCandidateAssessment(sessionIdToResume);
        }
        if (cancelled) return;
        await openCandidateAssessment(resumed);
      } catch (error) {
        if (!cancelled && error instanceof ApiRequestError && error.status === 401) {
          clearAccessToken();
          setUser(null);
          setAuthError("Your sign-in has expired. Sign in again to resume the assessment.");
        } else if (!cancelled) {
          setAssessmentError(
            error instanceof ApiRequestError && error.status === 409
              ? "No active question is available to resume. Your assessment may have no unanswered questions remaining."
              : error instanceof ApiRequestError
                ? error.message
                : "The saved assessment could not be resumed.",
          );
        }
      } finally {
        if (!cancelled) setIsLoadingAssessment(false);
      }
    }

    void resumeStoredAssessment();
    return () => {
      cancelled = true;
    };
  }, [interview, user, openCandidateAssessment]);

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
        if (!latest) return;
        setOutput(toExecutionOutput(latest));
        setActiveSubmissionId(latest.submission_id);
        if (allowedLanguages.includes(latest.language)) setLanguage(latest.language);
        setSourceByQuestion((current) => ({
          ...current,
          [questionId]: {
            ...current[questionId],
            [latest.language]: latest.source_code,
          },
        }));
        setStdinByQuestion((current) => ({
          ...current,
          [questionId]: latest.stdin,
        }));

        if (latest.status === "queued" || latest.status === "running") {
          const status = await getSubmissionStatus(latest.submission_id);
          if (!cancelled) {
            setOutput(toStatusOutput(status));
            if (status.job_status === "failed") {
              setAssessmentError(
                "The execution worker marked this saved submission as failed.",
              );
            }
          }
        } else {
          const savedEvaluation = await getSubmissionEvaluation(latest.submission_id);
          if (!cancelled) setEvaluation(savedEvaluation);
        }
      } catch (error) {
        if (cancelled) return;
        if (!handleUnauthorized(error)) {
          setAssessmentError(
            error instanceof ApiRequestError
              ? error.message
              : "Submission history could not be loaded.",
          );
        }
      }
    }

    void loadLatestAttempt();
    return () => {
      cancelled = true;
    };
  }, [allowedLanguages, currentQuestion, handleUnauthorized, interview]);

  async function handleSignIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isSigningIn) return;
    setIsSigningIn(true);
    setAuthError(null);
    try {
      const token = await login(email.trim(), password);
      setPassword("");
      setAccessToken(token.access_token);
      const currentUser = await getCurrentUser();
      setUser(currentUser);
      setPassword("");
      setAuthError(null);
    } catch (error) {
      clearAccessToken();
      setAuthError(
        error instanceof ApiRequestError
          ? error.message
          : "Sign-in failed. Check your connection and try again.",
      );
    } finally {
      setIsSigningIn(false);
    }
  }

  function handleSignOut() {
    clearAccessToken();
    window.sessionStorage.removeItem(sessionIdStorageKey);
    setUser(null);
    setInterview(null);
    setQuestions([]);
    setInterviewId("");
    setAuthError(null);
    setAssessmentError(null);
    setResults(null);
  }

  async function handleLoadAssessment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const requestedId = interviewId.trim();
    if (!requestedId) {
      setAssessmentError("Enter the interview session ID provided by your assessor.");
      return;
    }
    setIsLoadingAssessment(true);
    setAssessmentError(null);
    setShowResults(false);
    setInterview(null);
    setQuestions([]);
    setResults(null);
    setOutput(null);
    setActiveSubmissionId(null);
    setEvaluation(null);
    setEvaluationError(null);
    setAttemptCountByQuestion({});
    try {
      const [interviewResponse, questionResponse] = await Promise.all([
        getInterview(requestedId),
        getAssignedQuestions(requestedId),
      ]);
      setInterview(interviewResponse);
      setQuestions(questionResponse);
      setCurrentIndex(0);
      setAttemptCountByQuestion({});
      window.sessionStorage.setItem(sessionIdStorageKey, requestedId);
      const firstQuestion = questionResponse[0];
      const firstLanguages = firstQuestion ? languagesForQuestion(firstQuestion) : supportedLanguages;
      setLanguage(
        firstQuestion?.expected_language &&
          firstLanguages.includes(firstQuestion.expected_language)
          ? firstQuestion.expected_language
          : firstLanguages[0] ?? "python",
      );
    } catch (error) {
      if (!handleUnauthorized(error)) {
        setAssessmentError(
          error instanceof ApiRequestError
            ? error.message
            : "The assessment could not be loaded.",
        );
      }
    } finally {
      setIsLoadingAssessment(false);
    }
  }

  async function handleStartAssessment() {
    if (isLoadingAssessment || user?.role !== "candidate") return;
    setIsLoadingAssessment(true);
    setAssessmentError(null);
    attemptedAutoResumeId.current = null;
    try {
      const started = await startCandidateAssessment();
      await openCandidateAssessment(started);
    } catch (error) {
      if (!handleUnauthorized(error)) {
        setAssessmentError(
          error instanceof ApiRequestError && error.status === 409
            ? "No active assessment question is available to start. You may have completed the available questions, or no eligible question is available. Contact your assessor."
            : error instanceof ApiRequestError
              ? error.message
              : "The assessment could not be started.",
        );
      }
    } finally {
      setIsLoadingAssessment(false);
    }
  }

  async function handleResumeAssessment() {
    const savedId = interviewId.trim();
    if (!savedId || isLoadingAssessment) {
      setAssessmentError("No saved assessment session ID is available to resume.");
      return;
    }
    setIsLoadingAssessment(true);
    setAssessmentError(null);
    try {
      const resumed = await resumeCandidateAssessment(savedId);
      await openCandidateAssessment(resumed);
    } catch (error) {
      if (!handleUnauthorized(error)) {
        setAssessmentError(
          error instanceof ApiRequestError && error.status === 409
            ? "No active question is available to resume. Your assessment may have no unanswered questions remaining."
            : error instanceof ApiRequestError
              ? error.message
              : "The assessment could not be resumed.",
        );
      }
    } finally {
      setIsLoadingAssessment(false);
    }
  }

  function changeQuestion(nextIndex: number) {
    if (isRunning || nextIndex < 0 || nextIndex >= questions.length) return;
    const nextQuestion = questions[nextIndex];
    const nextLanguages = languagesForQuestion(nextQuestion);
    setCurrentIndex(nextIndex);
    setAssessmentError(null);
    setOutput(null);
    setActiveSubmissionId(null);
    setEvaluation(null);
    setEvaluationError(null);
    setLanguage(
      nextQuestion.expected_language &&
        nextLanguages.includes(nextQuestion.expected_language)
        ? nextQuestion.expected_language
        : nextLanguages[0] ?? "python",
    );
  }

  function handleLanguageChange(nextLanguage: Language) {
    setLanguage(nextLanguage);
  }

  function handleSourceChange(nextSource: string) {
    if (!currentQuestion) return;
    setSourceByQuestion((current) => ({
      ...current,
      [currentQuestion.question_id]: {
        ...current[currentQuestion.question_id],
        [language]: nextSource,
      },
    }));
  }

  function handleStdinChange(nextStdin: string) {
    if (!currentQuestion) return;
    setStdinByQuestion((current) => ({
      ...current,
      [currentQuestion.question_id]: nextStdin,
    }));
  }

  async function handleResultsToggle() {
    const nextShowResults = !showResults;
    setShowResults(nextShowResults);
    if (nextShowResults && interview) {
      await loadResults(interview.interview_session_id);
    }
  }

  async function refreshInterviewResults(interviewSessionId: string) {
    try {
      setInterview(await getInterview(interviewSessionId));
      if (showResults) await loadResults(interviewSessionId);
    } catch (error) {
      if (!handleUnauthorized(error)) {
        setAssessmentError(
          error instanceof ApiRequestError ? error.message : "Assessment status could not be refreshed.",
        );
      }
    }
  }

  async function runEvaluation(submissionId: string, interviewSessionId: string) {
    setIsEvaluating(true);
    setEvaluationError(null);
    try {
      setEvaluation(await evaluateSubmission(submissionId));
      await refreshInterviewResults(interviewSessionId);
    } catch (error) {
      if (!handleUnauthorized(error)) {
        setEvaluationError(
          error instanceof ApiRequestError
            ? error.message
            : "Deterministic evaluation could not be completed.",
        );
      }
    } finally {
      setIsEvaluating(false);
    }
  }

  async function pollExecution(submissionId: string, interviewSessionId: string) {
    let status = await getSubmissionStatus(submissionId);
    setOutput(toStatusOutput(status));
    let pollCount = 0;
    while (isPending(status)) {
      if (pollCount++ >= maxPolls) {
        throw new ApiRequestError(
          "Execution is still pending after 60 seconds. Use Check status to resume polling.",
        );
      }
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
      status = await getSubmissionStatus(submissionId);
      setOutput(toStatusOutput(status));
    }
    if (status.job_status === "failed") {
      throw new ApiRequestError(
        "The execution worker marked this submission as failed. Your submission remains saved.",
      );
    }
    await runEvaluation(submissionId, interviewSessionId);
  }

  async function handleSubmitCode() {
    if (isRunning || !interview || !currentQuestion) return;
    if (interview.status !== "active") {
      setAssessmentError("This interview is no longer active. You can still review its results.");
      return;
    }
    if (!sourceCode.trim()) {
      setAssessmentError("Source code cannot be empty.");
      return;
    }
    setIsRunning(true);
    setAssessmentError(null);
    setOutput(null);
    setActiveSubmissionId(null);
    setEvaluation(null);
    setEvaluationError(null);
    try {
      const response = await submitCode({
        interview_session_id: interview.interview_session_id,
        question_id: currentQuestion.question_id,
        language,
        source_code: sourceCode,
        stdin,
      });
      setActiveSubmissionId(response.submission_id);
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
        [currentQuestion.question_id]:
          (current[currentQuestion.question_id] ?? 0) + 1,
      }));
      await pollExecution(response.submission_id, interview.interview_session_id);
    } catch (error) {
      if (!handleUnauthorized(error)) {
        setAssessmentError(
          error instanceof ApiRequestError
            ? error.message
            : "Submission failed. The code may not have been accepted by the backend.",
        );
      }
    } finally {
      setIsRunning(false);
    }
  }

  async function handleCheckStatus() {
    if (isRunning || !activeSubmissionId || !interview) return;
    setIsRunning(true);
    setAssessmentError(null);
    try {
      await pollExecution(activeSubmissionId, interview.interview_session_id);
    } catch (error) {
      if (!handleUnauthorized(error)) {
        setAssessmentError(
          error instanceof ApiRequestError
            ? error.message
            : "Execution status could not be refreshed.",
        );
      }
    } finally {
      setIsRunning(false);
    }
  }

  async function handleCompleteAssessment() {
    if (!interview) return;
    if (!window.confirm("Complete this assessment? This cannot be undone.")) return;
    try {
      const closed = await completeInterview(interview.interview_session_id);
      setInterview((current) =>
        current
          ? {
              ...current,
              status: closed.status,
              started_at: closed.started_at,
              created_at: closed.created_at,
              completed_at: closed.completed_at,
            }
          : current,
      );
      await loadResults(interview.interview_session_id);
      setShowResults(true);
    } catch (error) {
      if (!handleUnauthorized(error)) {
        setAssessmentError(
          error instanceof ApiRequestError
            ? error.message
            : "The assessment could not be completed.",
        );
      }
    }
  }

  async function handleContinueAssessment() {
    if (!interview || isContinuingAssessment || user?.role !== "candidate") return;
    setIsContinuingAssessment(true);
    setAssessmentError(null);
    try {
      const next = await continueCandidateAssessment(interview.interview_session_id);
      await openCandidateAssessment(next);
    } catch (error) {
      if (!handleUnauthorized(error)) {
        setAssessmentError(
          error instanceof ApiRequestError
            ? error.message
            : "The next assessment question could not be loaded.",
        );
      }
    } finally {
      setIsContinuingAssessment(false);
    }
  }

  const questionPosition = useMemo(
    () => (questions.length > 0 ? currentIndex + 1 : 0),
    [currentIndex, questions.length],
  );
  const executionPending =
    output?.status === "queued" || output?.status === "running";

  if (isCheckingSession) {
    return (
      <main className="auth-page">
        <section className="auth-card" aria-live="polite">Checking sign-in session…</section>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="auth-page">
        <section className="auth-card">
          <div className="brand auth-brand">
            <span className="brand-mark">M</span>
            <div><strong>MATACSS</strong><span>Technical Assessment Workspace</span></div>
          </div>
          <span className="eyebrow">CANDIDATE SIGN IN</span>
          <h1>Continue to your assessment</h1>
          <p className="auth-description">
            Sign in with the account provided to you. Your credentials are sent only to the configured MATACSS backend.
          </p>
          <form className="auth-form" onSubmit={(event) => void handleSignIn(event)}>
            <label>
              Email
              <input
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </label>
            <label>
              Password
              <input
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            {authError && <p className="error-message" role="alert">{authError}</p>}
            <button className="run-button" type="submit" disabled={isSigningIn}>
              {isSigningIn ? "Signing in…" : "Sign in"}
            </button>
          </form>
          <p className="session-security-note">
            Your sign-in token is kept for this browser tab and cleared when you sign out.
          </p>
        </section>
      </main>
    );
  }

  return (
    <main className="workspace">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">M</span>
          <div><strong>MATACSS</strong><span>Technical Assessment Workspace</span></div>
        </div>
        <div className="session-status">
          <span className="status-dot" aria-hidden="true" />
          {interview?.status === "active" ? "Workspace ready" : "Assessment not loaded"}
          <span className="signed-in-user">{user.email}</span>
          {interview && (
            <button type="button" className="results-button" onClick={() => void handleResultsToggle()}>
              {showResults ? "Back to workspace" : "View results"}
            </button>
          )}
          <button type="button" className="results-button" onClick={handleSignOut}>Sign out</button>
        </div>
      </header>

      {!interview ? (
        <section className="assessment-entry">
          <span className="eyebrow">
            {user.role === "candidate" ? "YOUR ASSESSMENT" : "LOAD AN ASSESSMENT"}
          </span>
          <h1>
            {user.role === "candidate"
              ? "Start or resume your assessment"
              : "Enter an interview session ID"}
          </h1>
          {user.role === "candidate" && (
            <p>
              Start uses your candidate account to find or create your assessment and present its current assigned question.
            </p>
          )}
          {user.role === "candidate" && (
            <div className="candidate-assessment-actions">
              <button
                type="button"
                className="run-button"
                disabled={isLoadingAssessment}
                onClick={() => void handleStartAssessment()}
              >
                {isLoadingAssessment ? "Starting assessment…" : "Start assessment"}
              </button>
              {interviewId && (
                <button
                  type="button"
                  className="secondary-button"
                  disabled={isLoadingAssessment}
                  onClick={() => void handleResumeAssessment()}
                >
                  Resume saved assessment
                </button>
              )}
            </div>
          )}
          <p className="assessor-session-note">
            {user.role === "candidate"
              ? "If your assessor gave you a specific session ID, you can load it below."
              : "Load the assessment session assigned to you."}
          </p>
          <form className="assessment-entry-form" onSubmit={(event) => void handleLoadAssessment(event)}>
            <label htmlFor="interview-session-id">Interview session ID</label>
            <input
              id="interview-session-id"
              autoComplete="off"
              spellCheck={false}
              value={interviewId}
              onChange={(event) => setInterviewId(event.target.value)}
              placeholder="UUID supplied by your assessor"
            />
            <button type="submit" className="run-button" disabled={isLoadingAssessment}>
              {isLoadingAssessment ? "Loading assessment…" : "Load assessment"}
            </button>
          </form>
          {assessmentError && <p className="error-message" role="alert">{assessmentError}</p>}
        </section>
      ) : showResults ? (
        <div className="results-layout">
          <ResultsPanel results={results} isLoading={isResultsLoading} error={resultsError} />
          <button type="button" className="secondary-button results-back" onClick={() => setShowResults(false)}>
            Back to workspace
          </button>
        </div>
      ) : (
        <>
          <div className="assessment-context">
            <span>Assessment session</span>
            <code>{interview.interview_session_id}</code>
            <span className={`assessment-status assessment-status-${interview.status}`}>
              {interview.status}
            </span>
            {interview.status === "active" && (
              <button type="button" className="secondary-button" onClick={() => void handleCompleteAssessment()}>
                Finish assessment
              </button>
            )}
          </div>
          {assessmentError && <p className="error-message page-error" role="alert">{assessmentError}</p>}
          {questions.length === 0 ? (
            <section className="assessment-entry">
              <span className="eyebrow">ASSESSMENT</span>
              <h1>No assigned questions</h1>
              <p>This session has no assigned questions to work on. Contact your assessor.</p>
            </section>
          ) : showResults ? (
            <div className="results-layout">
              <ResultsPanel results={results} isLoading={isResultsLoading} error={resultsError} />
            </div>
          ) : (
            <div className="workspace-grid">
              <aside className="problem-column">
                {problem && (
                  <ProblemPanel
                    problem={problem}
                    questionNumber={questionPosition}
                    totalQuestions={questions.length}
                  />
                )}
                <div className="workflow-card">
                  <span className="eyebrow">ASSESSMENT</span>
                  <p>
                    Read the assigned prompt, implement your solution, and submit it for execution.
                    Results are evaluated against the assessment&apos;s configured test cases.
                  </p>
                </div>
              </aside>

              <section className="coding-column" aria-label="Code editor">
                <div className="editor-toolbar">
                  <div className="file-label">
                    <span className="file-dot" aria-hidden="true" />
                    solution.{language === "python" ? "py" : language === "cpp" ? "cpp" : "java"}
                  </div>
                  <label className="language-control">
                    <span>Language</span>
                    <select
                      value={language}
                      onChange={(event) => handleLanguageChange(event.target.value as Language)}
                      aria-label="Select programming language"
                      disabled={isRunning || allowedLanguages.length === 0}
                    >
                      {allowedLanguages.map((item) => (
                        <option key={item} value={item}>{languageLabels[item]}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="editor-shell">
                  <CodeEditor language={language} value={sourceCode} onChange={handleSourceChange} />
                </div>
                <label className="stdin-control">
                  <span>Standard input</span>
                  <textarea
                    value={stdin}
                    onChange={(event) => handleStdinChange(event.target.value)}
                    placeholder="Optional input for your program"
                    rows={3}
                    disabled={isRunning}
                  />
                </label>
                <div className="question-navigation" aria-label="Question navigation">
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={currentIndex === 0 || isRunning}
                    onClick={() => changeQuestion(currentIndex - 1)}
                  >
                    Previous
                  </button>
                  <span>Question {questionPosition} of {questions.length}</span>
                  <span>Attempts: {attemptCountByQuestion[currentQuestion.question_id] ?? 0}</span>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={currentIndex === questions.length - 1 || isRunning}
                    onClick={() => changeQuestion(currentIndex + 1)}
                  >
                    Next
                  </button>
                </div>
                <div className="run-bar">
                  <span className="run-note">
                    {isInactive
                      ? `This assessment is ${interview.status}.`
                      : "Submission and evaluation use the configured assessment backend."}
                  </span>
                  <div className="run-actions">
                    {activeSubmissionId && executionPending && (
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={isRunning}
                        onClick={() => void handleCheckStatus()}
                      >
                        Check status
                      </button>
                    )}
                    <button
                      type="button"
                      className="run-button"
                      disabled={isRunning || isInactive || allowedLanguages.length === 0}
                      onClick={() => void handleSubmitCode()}
                    >
                      {isRunning ? "Working…" : "Submit code"}
                    </button>
                  </div>
                </div>
                {assessmentError && <p className="error-message" role="alert">{assessmentError}</p>}
                <OutputPanel output={output} />
                <EvaluationPanel
                  evaluation={evaluation}
                  isLoading={isEvaluating}
                  error={evaluationError}
                  canEvaluate={Boolean(
                    activeSubmissionId &&
                      !executionPending &&
                      output &&
                      output.status !== "sandbox_error",
                  )}
                  canContinue={Boolean(
                    user.role === "candidate" &&
                      interview.status === "active" &&
                      evaluation &&
                      currentIndex === questions.length - 1,
                  )}
                  isContinuing={isContinuingAssessment}
                  onContinue={() => void handleContinueAssessment()}
                  onEvaluate={() => {
                    if (activeSubmissionId) {
                      void runEvaluation(activeSubmissionId, interview.interview_session_id);
                    }
                  }}
                />
              </section>
            </div>
          )}
        </>
      )}
    </main>
  );
}
