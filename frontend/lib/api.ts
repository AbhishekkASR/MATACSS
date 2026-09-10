import type {
  Candidate,
  CodeSubmissionRequest,
  CodeSubmissionResponse,
  ExecutionStatus,
  AssignedQuestion,
  InterviewSession,
  Language,
  Question,
  SubmissionAttempt,
  EvaluationResult,
  AssessmentResults,
  QuestionResult,
  SubmissionStatus,
} from "@/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";

export class ApiRequestError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiRequestError";
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

function isCodeSubmissionResponse(value: unknown): value is CodeSubmissionResponse {
  if (!value || typeof value !== "object") {
    return false;
  }

  const response = value as Record<string, unknown>;
  return (
    typeof response.submission_id === "string" &&
    typeof response.interview_session_id === "string" &&
    typeof response.question_id === "string" &&
    typeof response.job_id === "string" &&
    typeof response.job_status === "string" &&
    isExecutionStatus(response.status) &&
    typeof response.message === "string" &&
    typeof response.stdout === "string" &&
    typeof response.stderr === "string" &&
    (typeof response.exit_code === "number" || response.exit_code === null) &&
    (typeof response.execution_time_ms === "number" ||
      response.execution_time_ms === null) &&
    typeof response.timed_out === "boolean"
  );
}

function isSubmissionStatus(value: unknown): value is SubmissionStatus {
  if (!value || typeof value !== "object") return false;
  const response = value as Record<string, unknown>;
  return (
    typeof response.submission_id === "string" &&
    typeof response.job_id === "string" &&
    (response.job_status === "queued" ||
      response.job_status === "running" ||
      response.job_status === "succeeded" ||
      response.job_status === "failed") &&
    isExecutionStatus(response.submission_status) &&
    (typeof response.stdout === "string" || response.stdout === null) &&
    (typeof response.stderr === "string" || response.stderr === null) &&
    (typeof response.exit_code === "number" || response.exit_code === null) &&
    (typeof response.execution_time_ms === "number" ||
      response.execution_time_ms === null) &&
    (typeof response.timed_out === "boolean" || response.timed_out === null)
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
    (response.status === "active" ||
      response.status === "completed" ||
      response.status === "cancelled") &&
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
  if (!value || typeof value !== "object") return false;
  const question = value as Record<string, unknown>;
  return (
    typeof question.question_id === "string" &&
    typeof question.sequence_number === "number" &&
    typeof question.title === "string" &&
    typeof question.description === "string" &&
    (question.difficulty === "easy" ||
      question.difficulty === "medium" ||
      question.difficulty === "hard") &&
    (question.expected_language === null ||
      isLanguage(question.expected_language)) &&
    typeof question.created_at === "string"
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
    (result.evaluation_status === "not_attempted" ||
      result.evaluation_status === "attempted_not_evaluated" ||
      result.evaluation_status === "evaluated") &&
    (typeof result.score === "number" || result.score === null) &&
    typeof result.passed_test_cases === "number" &&
    typeof result.total_test_cases === "number"
  );
}

function messageForStatus(status: number): string {
  if (status === 404) return "The configured interview session or question was not found.";
  if (status === 409) return "This interview session is not active.";
  if (status === 422) return "The submission details are invalid.";
  if (status >= 500) return "The backend could not process the submission.";
  return "The backend rejected the request.";
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch {
    throw new ApiRequestError("Unable to connect to the backend.");
  }

  if (!response.ok) {
    throw new ApiRequestError(messageForStatus(response.status), response.status);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiRequestError("The backend returned an invalid response.", response.status);
  }
}

export function createCandidate(name: string, email: string): Promise<Candidate> {
  return request<Candidate>("/api/v1/candidates", {
    method: "POST",
    body: JSON.stringify({ name, email }),
  });
}

export function createInterview(candidateId: string): Promise<InterviewSession> {
  return request<InterviewSession>("/api/v1/interviews", {
    method: "POST",
    body: JSON.stringify({ candidate_id: candidateId }),
  });
}

export function createQuestion(
  title: string,
  description: string,
  difficulty: Question["difficulty"],
  expectedLanguage: Language,
): Promise<Question> {
  return request<Question>("/api/v1/questions", {
    method: "POST",
    body: JSON.stringify({
      title,
      description,
      difficulty,
      expected_language: expectedLanguage,
    }),
  });
}

export function submitCode(payload: CodeSubmissionRequest): Promise<CodeSubmissionResponse> {
  return request<unknown>("/api/v1/submissions", {
    method: "POST",
    body: JSON.stringify({ ...payload, stdin: payload.stdin ?? "" }),
  }).then((response) => {
    if (!isCodeSubmissionResponse(response)) {
      throw new ApiRequestError("The backend returned an invalid submission response.");
    }
    return response;
  });
}

export function getSubmissionStatus(
  submissionId: string,
): Promise<SubmissionStatus> {
  return request<unknown>(`/api/v1/submissions/${submissionId}/status`, {
    method: "GET",
  }).then((response) => {
    if (!isSubmissionStatus(response)) {
      throw new ApiRequestError("The backend returned an invalid submission status.");
    }
    return response;
  });
}

export function getInterview(interviewSessionId: string): Promise<InterviewSession> {
  return request<unknown>(`/api/v1/interviews/${interviewSessionId}`, {
    method: "GET",
  }).then((response) => {
    if (!isInterviewSession(response)) {
      throw new ApiRequestError("The backend returned an invalid interview response.");
    }
    return response;
  });
}

export function getAssessmentResults(
  interviewSessionId: string,
): Promise<AssessmentResults> {
  return request<unknown>(`/api/v1/interviews/${interviewSessionId}/results`, {
    method: "GET",
  }).then((response) => {
    if (!response || typeof response !== "object") {
      throw new ApiRequestError("The backend returned an invalid results response.");
    }
    const result = response as Record<string, unknown>;
    if (
      typeof result.interview_session_id !== "string" ||
      (result.interview_status !== "active" &&
        result.interview_status !== "completed" &&
        result.interview_status !== "cancelled") ||
      typeof result.total_questions !== "number" ||
      typeof result.attempted_questions !== "number" ||
      typeof result.evaluated_questions !== "number" ||
      typeof result.total_passed_test_cases !== "number" ||
      typeof result.total_test_cases !== "number" ||
      (typeof result.overall_score !== "number" && result.overall_score !== null) ||
      (result.status !== "scored" && result.status !== "not_scored") ||
      !Array.isArray(result.questions) ||
      !result.questions.every((question) => isQuestionResult(question))
    ) {
      throw new ApiRequestError("The backend returned an invalid results response.");
    }
    return result as unknown as AssessmentResults;
  });
}

export function getAssignedQuestions(
  interviewSessionId: string,
): Promise<AssignedQuestion[]> {
  return request<unknown>(`/api/v1/interviews/${interviewSessionId}/questions`, {
    method: "GET",
  }).then((response) => {
    if (
      !Array.isArray(response) ||
      !response.every((question) => isAssignedQuestion(question))
    ) {
      throw new ApiRequestError("The backend returned invalid interview questions.");
    }
    return [...response].sort((left, right) => left.sequence_number - right.sequence_number);
  });
}

export function getSubmissionAttempts(
  interviewSessionId: string,
  questionId: string,
): Promise<SubmissionAttempt[]> {
  return request<unknown>(
    `/api/v1/interviews/${interviewSessionId}/questions/${questionId}/submissions`,
    { method: "GET" },
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
    { method: "GET" },
  )
    .then((response) => {
      if (!isSubmissionAttempt(response)) {
        throw new ApiRequestError("The backend returned an invalid latest submission.");
      }
      return response;
    })
    .catch((error: unknown) => {
      if (error instanceof ApiRequestError && error.status === 404) {
        return null;
      }
      throw error;
    });
}

export function getSubmissionEvaluation(
  submissionId: string,
): Promise<EvaluationResult | null> {
  return request<unknown>(`/api/v1/submissions/${submissionId}/evaluation`, {
    method: "GET",
  })
    .then((response) => {
      if (!isEvaluationResult(response)) {
        throw new ApiRequestError("The backend returned an invalid evaluation response.");
      }
      return response;
    })
    .catch((error: unknown) => {
      if (error instanceof ApiRequestError && error.status === 404) {
        return null;
      }
      throw error;
    });
}
