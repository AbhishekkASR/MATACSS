export type Language = "python" | "cpp" | "java";
export type InterviewStatus = "active" | "completed" | "cancelled";
export type ExecutionStatus =
  | "queued"
  | "running"
  | "success"
  | "compilation_error"
  | "runtime_error"
  | "timeout"
  | "output_limit_exceeded"
  | "sandbox_error";

export interface Candidate {
  candidate_id: string;
  name: string;
  email: string;
  created_at: string;
}

export interface InterviewSession {
  interview_session_id: string;
  candidate_id: string;
  status: InterviewStatus;
  started_at: string | null;
  created_at: string;
  completed_at: string | null;
  total_questions: number;
  submitted_questions: number;
  attempted_questions: number;
  submission_count: number;
}

export interface Question {
  question_id: string;
  title: string;
  description: string;
  difficulty: "easy" | "medium" | "hard";
  expected_language: Language | null;
  created_at: string;
}

export interface AssignedQuestion extends Question {
  sequence_number: number;
}

export interface CodeSubmissionRequest {
  interview_session_id: string;
  question_id: string;
  language: Language;
  source_code: string;
  stdin?: string;
}

export interface CodeSubmissionResponse {
  submission_id: string;
  interview_session_id: string;
  question_id: string;
  status: ExecutionStatus;
  message: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  execution_time_ms: number | null;
  timed_out: boolean;
}

export interface SubmissionStatus {
  submission_id: string;
  job_id: string;
  job_status: "queued" | "running" | "succeeded" | "failed";
  submission_status: ExecutionStatus;
  stdout: string | null;
  stderr: string | null;
  exit_code: number | null;
  execution_time_ms: number | null;
  timed_out: boolean | null;
}

export interface SubmissionAttempt {
  submission_id: string;
  question_id: string;
  language: Language;
  source_code: string;
  stdin: string;
  status: ExecutionStatus;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  execution_time_ms: number | null;
  timed_out: boolean;
  created_at: string;
}

export interface EvaluationCase {
  test_case_id: string;
  description: string | null;
  passed: boolean;
  status: Exclude<ExecutionStatus, "pending">;
  stdout: string;
  stderr: string;
}

export interface EvaluationResult {
  submission_id: string;
  evaluation_result_id: string;
  status: "scored" | "not_scored";
  total_test_cases: number;
  passed_test_cases: number;
  failed_test_cases: number;
  score: number | null;
  test_cases: EvaluationCase[];
  created_at: string;
}

export type QuestionResultStatus =
  | "not_attempted"
  | "attempted_not_evaluated"
  | "evaluated";

export interface QuestionResult {
  question_id: string;
  sequence_number: number;
  title: string;
  difficulty: string;
  latest_submission_id: string | null;
  latest_submission_status: ExecutionStatus | null;
  evaluation_status: QuestionResultStatus;
  score: number | null;
  passed_test_cases: number;
  total_test_cases: number;
}

export interface AssessmentResults {
  interview_session_id: string;
  interview_status: InterviewStatus;
  total_questions: number;
  attempted_questions: number;
  evaluated_questions: number;
  total_passed_test_cases: number;
  total_test_cases: number;
  overall_score: number | null;
  status: "scored" | "not_scored";
  questions: QuestionResult[];
}

export interface Problem {
  title: string;
  description: string;
  difficulty: string;
  expectedLanguage: Language;
}

export interface ExecutionOutput {
  status: ExecutionStatus;
  stdout: string;
  stderr: string;
  exitCode: number | null;
  executionTimeMs: number | null;
  timedOut: boolean;
}
