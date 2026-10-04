import type {
  AssessmentResults,
  AssessmentQuestionDetails,
  AssessmentStartResponse,
  AgentFeedback,
  AgentFeedbackValue,
  AssignedQuestion,
  AuthenticatedUser,
  AuthToken,
  CodeSubmissionRequest,
  CodeSubmissionResponse,
  EvaluationResult,
  ExecutionStatus,
  InterviewSession,
  InterviewStatusResponse,
  Language,
  QuestionResult,
  SubmissionAttempt,
  SubmissionStatus,
} from "@/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const AUTH_TOKEN_STORAGE_KEY = "matacss.access_token";
let accessToken: string | null = null;

export class ApiRequestError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiRequestError";
  }
}

export function restoreAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  accessToken = window.sessionStorage.getItem(AUTH_TOKEN_STORAGE_KEY);
  return accessToken;
}

export function setAccessToken(token: string): void {
  accessToken = token;
  if (typeof window !== "undefined") {
    window.sessionStorage.setItem(AUTH_TOKEN_STORAGE_KEY, token);
  }
}

export function clearAccessToken(): void {
  accessToken = null;
  if (typeof window !== "undefined") {
    window.sessionStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  }
}

function isExecutionStatus(value: unknown): value is ExecutionStatus {
  return (
    typeof value === "string" &&
    [
      "queued",
      "running",
      "success",
      "compilation_error",
      "runtime_error",
      "timeout",
      "output_limit_exceeded",
      "sandbox_error",
    ].includes(value)
  );
}

function isLanguage(value: unknown): value is Language {
  return value === "python" || value === "cpp" || value === "java";
}

function isInterviewSession(value: unknown): value is InterviewSession {
  if (!value || typeof value !== "object") return false;
  const response = value as Record<string, unknown>;
  return (
    typeof response.interview_session_id === "string" &&
    typeof response.candidate_id === "string" &&
    ["active", "completed", "cancelled"].includes(String(response.status)) &&
    (typeof response.started_at === "string" || response.started_at === null) &&
    typeof response.created_at === "string" &&
    (typeof response.completed_at === "string" || response.completed_at === null) &&
    typeof response.total_questions === "number" &&
    typeof response.submitted_questions === "number" &&
    typeof response.attempted_questions === "number" &&
    typeof response.submission_count === "number"
  );
}

function isAssignedQuestion(value: unknown): value is AssignedQuestion {
  if (!isQuestionDetails(value)) return false;
  const question = value as Record<string, unknown>;
  return typeof question.sequence_number === "number" &&
    typeof question.created_at === "string";
}

function isQuestionDetails(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const question = value as Record<string, unknown>;
  return (
    typeof question.question_id === "string" &&
    typeof question.title === "string" &&
    typeof question.description === "string" &&
    ["easy", "medium", "hard"].includes(String(question.difficulty)) &&
    (question.expected_language === null || isLanguage(question.expected_language)) &&
    (question.input_format === undefined ||
      question.input_format === null ||
      typeof question.input_format === "string") &&
    (question.output_format === undefined ||
      question.output_format === null ||
      typeof question.output_format === "string") &&
    (question.constraints_text === undefined ||
      question.constraints_text === null ||
      typeof question.constraints_text === "string") &&
    (question.starter_code === undefined ||
      question.starter_code === null ||
      typeof question.starter_code === "string") &&
    (question.supported_languages === undefined ||
      question.supported_languages === null ||
      (Array.isArray(question.supported_languages) &&
        question.supported_languages.every(isLanguage))) &&
    (question.status === undefined || typeof question.status === "string") &&
    (question.created_at === undefined || typeof question.created_at === "string") &&
    (question.sequence_number === undefined ||
      typeof question.sequence_number === "number")
  );
}

function isAssessmentStartResponse(value: unknown): value is AssessmentStartResponse {
  if (!value || typeof value !== "object") return false;
  const response = value as Record<string, unknown>;
  const question = response.current_question;
  return (
    typeof response.interview_session_id === "string" &&
    typeof response.candidate_id === "string" &&
    ["active", "completed", "cancelled"].includes(String(response.status)) &&
    (question === null ||
      (isQuestionDetails(question) &&
        typeof (question as AssessmentQuestionDetails).status === "string" &&
        (question as AssessmentQuestionDetails).input_format !== undefined &&
        (question as AssessmentQuestionDetails).output_format !== undefined &&
        (question as AssessmentQuestionDetails).constraints_text !== undefined &&
        ((question as AssessmentQuestionDetails).supported_languages === null ||
          Array.isArray(
            (question as AssessmentQuestionDetails).supported_languages,
          )) &&
        ((question as AssessmentQuestionDetails).starter_code === null ||
          typeof (question as AssessmentQuestionDetails).starter_code === "string")))
  );
}

function isSubmissionAttempt(value: unknown): value is SubmissionAttempt {
  if (!value || typeof value !== "object") return false;
  const attempt = value as Record<string, unknown>;
  return (
    typeof attempt.submission_id === "string" &&
    typeof attempt.question_id === "string" &&
    isLanguage(attempt.language) &&
    typeof attempt.source_code === "string" &&
    typeof attempt.stdin === "string" &&
    isExecutionStatus(attempt.status) &&
    typeof attempt.stdout === "string" &&
    typeof attempt.stderr === "string" &&
    (typeof attempt.exit_code === "number" || attempt.exit_code === null) &&
    (typeof attempt.execution_time_ms === "number" ||
      attempt.execution_time_ms === null) &&
    typeof attempt.timed_out === "boolean" &&
    typeof attempt.created_at === "string"
  );
}

function isSubmissionStatus(value: unknown): value is SubmissionStatus {
  if (!value || typeof value !== "object") return false;
  const response = value as Record<string, unknown>;
  return (
    typeof response.submission_id === "string" &&
    typeof response.job_id === "string" &&
    ["queued", "running", "succeeded", "failed"].includes(
      String(response.job_status),
    ) &&
    isExecutionStatus(response.submission_status) &&
    (typeof response.stdout === "string" || response.stdout === null) &&
    (typeof response.stderr === "string" || response.stderr === null) &&
    (typeof response.exit_code === "number" || response.exit_code === null) &&
    (typeof response.execution_time_ms === "number" ||
      response.execution_time_ms === null) &&
    (typeof response.timed_out === "boolean" || response.timed_out === null)
  );
}

function isEvaluationResult(value: unknown): value is EvaluationResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Record<string, unknown>;
  return (
    typeof result.submission_id === "string" &&
    typeof result.evaluation_result_id === "string" &&
    (result.status === "scored" || result.status === "not_scored") &&
    typeof result.total_test_cases === "number" &&
    typeof result.passed_test_cases === "number" &&
    typeof result.failed_test_cases === "number" &&
    (typeof result.score === "number" || result.score === null) &&
    Array.isArray(result.test_cases) &&
    result.test_cases.every((item) => {
      if (!item || typeof item !== "object") return false;
      const testCase = item as Record<string, unknown>;
      return (
        typeof testCase.test_case_id === "string" &&
        (typeof testCase.description === "string" ||
          testCase.description === null) &&
        typeof testCase.passed === "boolean" &&
        isExecutionStatus(testCase.status) &&
        typeof testCase.stdout === "string" &&
        typeof testCase.stderr === "string"
      );
    }) &&
    typeof result.created_at === "string"
  );
}

function isQuestionResult(value: unknown): value is QuestionResult {
  if (!value || typeof value !== "object") return false;
  const result = value as Record<string, unknown>;
  return (
    typeof result.question_id === "string" &&
    typeof result.sequence_number === "number" &&
    typeof result.title === "string" &&
    typeof result.difficulty === "string" &&
    (typeof result.latest_submission_id === "string" ||
      result.latest_submission_id === null) &&
    (typeof result.latest_submission_status === "string" ||
      result.latest_submission_status === null) &&
    ["not_attempted", "attempted_not_evaluated", "evaluated"].includes(
      String(result.evaluation_status),
    ) &&
    (typeof result.score === "number" || result.score === null) &&
    typeof result.passed_test_cases === "number" &&
    typeof result.total_test_cases === "number"
  );
}

function isAgentFeedbackValue(value: unknown): value is AgentFeedbackValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return true;
  }
  if (Array.isArray(value)) return value.every(isAgentFeedbackValue);
  if (typeof value === "object") {
    return Object.values(value).every(isAgentFeedbackValue);
  }
  return false;
}

function isAgentFeedback(value: unknown): value is AgentFeedback {
  if (!value || typeof value !== "object") return false;
  const entry = value as Record<string, unknown>;
  return (
    typeof entry.submission_id === "string" &&
    (entry.status === "completed" || entry.status === "failed") &&
    isAgentFeedbackValue(entry.interviewer_decision) &&
    isAgentFeedbackValue(entry.code_review) &&
    isAgentFeedbackValue(entry.edge_case_generation) &&
    isAgentFeedbackValue(entry.feedback) &&
    (typeof entry.failure_kind === "string" || entry.failure_kind === null) &&
    typeof entry.created_at === "string"
  );
}

function messageForStatus(status: number): string {
  if (status === 401) return "Your session is invalid or has expired. Sign in again.";
  if (status === 403) return "You do not have permission to access this assessment.";
  if (status === 404) return "The interview session, question, or submission was not found.";
  if (status === 409) return "There is no active assessment with a question available to start.";
  if (status === 422) return "The request details are invalid.";
  if (status >= 500) return "The backend could not process the request.";
  return "The backend rejected the request.";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken && !headers.has("Authorization")) {
    headers.set("Authorization", "Bearer ".concat(accessToken));
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiRequestError("Unable to connect to the backend.");
  }

  if (!response.ok) {
    if (response.status === 401) clearAccessToken();
    let message = messageForStatus(response.status);
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string" && payload.detail.trim()) {
        message = payload.detail;
      }
    } catch {
      // Use the status-specific message for non-JSON errors.
    }
    throw new ApiRequestError(message, response.status);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiRequestError("The backend returned an invalid response.", response.status);
  }
}

export function login(email: string, password: string): Promise<AuthToken> {
  return request<unknown>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  }).then((response) => {
    if (
      !response ||
      typeof response !== "object" ||
      typeof (response as Record<string, unknown>).access_token !== "string" ||
      typeof (response as Record<string, unknown>).expires_in !== "number" ||
      (response as Record<string, unknown>).token_type !== "bearer"
    ) {
      throw new ApiRequestError("The backend returned an invalid sign-in response.");
    }
    return response as AuthToken;
  });
}

export function getCurrentUser(): Promise<AuthenticatedUser> {
  return request<unknown>("/api/v1/auth/me").then((response) => {
    if (!response || typeof response !== "object") {
      throw new ApiRequestError("The backend returned an invalid user response.");
    }
    const user = response as Record<string, unknown>;
    if (
      typeof user.user_id !== "string" ||
      typeof user.email !== "string" ||
      !["admin", "interviewer", "candidate"].includes(String(user.role)) ||
      typeof user.active !== "boolean" ||
      typeof user.created_at !== "string"
    ) {
      throw new ApiRequestError("The backend returned an invalid user response.");
    }
    return user as unknown as AuthenticatedUser;
  });
}

export function startCandidateAssessment(): Promise<AssessmentStartResponse> {
  return request<unknown>("/api/v1/question-engine/assessments/start", {
    method: "POST",
    body: JSON.stringify({}),
  }).then((response) => {
    if (!isAssessmentStartResponse(response)) {
      throw new ApiRequestError("The backend returned an invalid assessment start response.");
    }
    return response;
  });
}

export function resumeCandidateAssessment(
  interviewSessionId: string,
): Promise<AssessmentStartResponse> {
  return request<unknown>(
    `/api/v1/question-engine/assessments/${interviewSessionId}/resume`,
  ).then((response) => {
    if (!isAssessmentStartResponse(response)) {
      throw new ApiRequestError("The backend returned an invalid assessment resume response.");
    }
    return response;
  });
}

export function continueCandidateAssessment(
  interviewSessionId: string,
): Promise<AssessmentStartResponse> {
  return request<unknown>(
    `/api/v1/question-engine/assessments/${interviewSessionId}/next`,
    { method: "POST", body: JSON.stringify({}) },
  ).then((response) => {
    if (!isAssessmentStartResponse(response)) {
      throw new ApiRequestError("The backend returned an invalid next-question response.");
    }
    return response;
  });
}

export function getInterview(interviewSessionId: string): Promise<InterviewSession> {
  return request<unknown>(`/api/v1/interviews/${interviewSessionId}`).then((response) => {
    if (!isInterviewSession(response)) {
      throw new ApiRequestError("The backend returned an invalid interview response.");
    }
    return response;
  });
}

export function getAssignedQuestions(
  interviewSessionId: string,
): Promise<AssignedQuestion[]> {
  return request<unknown>(`/api/v1/interviews/${interviewSessionId}/questions`).then(
    (response) => {
      if (
        !Array.isArray(response) ||
        !response.every((question) => isAssignedQuestion(question))
      ) {
        throw new ApiRequestError("The backend returned invalid interview questions.");
      }
      return [...response].sort(
        (left, right) => left.sequence_number - right.sequence_number,
      );
    },
  );
}

export function getAssessmentResults(
  interviewSessionId: string,
): Promise<AssessmentResults> {
  return request<unknown>(`/api/v1/interviews/${interviewSessionId}/results`).then(
    (response) => {
      if (!response || typeof response !== "object") {
        throw new ApiRequestError("The backend returned an invalid results response.");
      }
      const result = response as Record<string, unknown>;
      if (
        typeof result.interview_session_id !== "string" ||
        !["active", "completed", "cancelled"].includes(
          String(result.interview_status),
        ) ||
        typeof result.total_questions !== "number" ||
        typeof result.attempted_questions !== "number" ||
        typeof result.evaluated_questions !== "number" ||
        typeof result.total_passed_test_cases !== "number" ||
        typeof result.total_test_cases !== "number" ||
        (typeof result.overall_score !== "number" &&
          result.overall_score !== null) ||
        (result.status !== "scored" && result.status !== "not_scored") ||
        !Array.isArray(result.questions) ||
        !result.questions.every((question) => isQuestionResult(question)) ||
        (result.agent_feedback !== undefined &&
          (!Array.isArray(result.agent_feedback) ||
            !result.agent_feedback.every((entry) => isAgentFeedback(entry))))
      ) {
        throw new ApiRequestError("The backend returned an invalid results response.");
      }
      return result as unknown as AssessmentResults;
    },
  );
}

export function submitCode(
  payload: CodeSubmissionRequest,
): Promise<CodeSubmissionResponse> {
  return request<unknown>("/api/v1/submissions", {
    method: "POST",
    body: JSON.stringify({ ...payload, stdin: payload.stdin ?? "" }),
  }).then((response) => {
    if (!response || typeof response !== "object") {
      throw new ApiRequestError("The backend returned an invalid submission response.");
    }
    const submission = response as Record<string, unknown>;
    if (
      typeof submission.submission_id !== "string" ||
      typeof submission.interview_session_id !== "string" ||
      typeof submission.question_id !== "string" ||
      typeof submission.job_id !== "string" ||
      typeof submission.job_status !== "string" ||
      !isExecutionStatus(submission.status) ||
      typeof submission.message !== "string" ||
      typeof submission.stdout !== "string" ||
      typeof submission.stderr !== "string" ||
      (typeof submission.exit_code !== "number" && submission.exit_code !== null) ||
      (typeof submission.execution_time_ms !== "number" &&
        submission.execution_time_ms !== null) ||
      typeof submission.timed_out !== "boolean"
    ) {
      throw new ApiRequestError("The backend returned an invalid submission response.");
    }
    return response as CodeSubmissionResponse;
  });
}

export function getSubmissionStatus(submissionId: string): Promise<SubmissionStatus> {
  return request<unknown>(`/api/v1/submissions/${submissionId}/status`).then(
    (response) => {
      if (!isSubmissionStatus(response)) {
        throw new ApiRequestError("The backend returned an invalid submission status.");
      }
      return response;
    },
  );
}

export function getSubmissionAttempts(
  interviewSessionId: string,
  questionId: string,
): Promise<SubmissionAttempt[]> {
  return request<unknown>(
    `/api/v1/interviews/${interviewSessionId}/questions/${questionId}/submissions`,
  ).then((response) => {
    if (
      !Array.isArray(response) ||
      !response.every((attempt) => isSubmissionAttempt(attempt))
    ) {
      throw new ApiRequestError("The backend returned invalid submission history.");
    }
    return response;
  });
}

export function getLatestSubmission(
  interviewSessionId: string,
  questionId: string,
): Promise<SubmissionAttempt | null> {
  return request<unknown>(
    `/api/v1/interviews/${interviewSessionId}/questions/${questionId}/latest-submission`,
  )
    .then((response) => {
      if (!isSubmissionAttempt(response)) {
        throw new ApiRequestError("The backend returned an invalid latest submission.");
      }
      return response;
    })
    .catch((error: unknown) => {
      if (error instanceof ApiRequestError && error.status === 404) return null;
      throw error;
    });
}

export function getSubmissionEvaluation(
  submissionId: string,
): Promise<EvaluationResult | null> {
  return request<unknown>(`/api/v1/submissions/${submissionId}/evaluation`)
    .then((response) => {
      if (!isEvaluationResult(response)) {
        throw new ApiRequestError("The backend returned an invalid evaluation response.");
      }
      return response;
    })
    .catch((error: unknown) => {
      if (error instanceof ApiRequestError && error.status === 404) return null;
      throw error;
    });
}

export function evaluateSubmission(submissionId: string): Promise<EvaluationResult> {
  return request<unknown>(`/api/v1/submissions/${submissionId}/evaluate`, {
    method: "POST",
  }).then((response) => {
    if (!isEvaluationResult(response)) {
      throw new ApiRequestError("The backend returned an invalid evaluation response.");
    }
    return response;
  });
}

export function completeInterview(
  interviewSessionId: string,
): Promise<InterviewStatusResponse> {
  return request<unknown>(`/api/v1/interviews/${interviewSessionId}/complete`, {
    method: "POST",
  }).then((response) => {
    if (!response || typeof response !== "object") {
      throw new ApiRequestError("The backend returned an invalid interview response.");
    }
    const interview = response as Record<string, unknown>;
    if (
      typeof interview.interview_session_id !== "string" ||
      typeof interview.candidate_id !== "string" ||
      !["active", "completed", "cancelled"].includes(String(interview.status)) ||
      (typeof interview.started_at !== "string" && interview.started_at !== null) ||
      typeof interview.created_at !== "string" ||
      (typeof interview.completed_at !== "string" && interview.completed_at !== null)
    ) {
      throw new ApiRequestError("The backend returned an invalid interview response.");
    }
    return interview as unknown as InterviewStatusResponse;
  });
}
