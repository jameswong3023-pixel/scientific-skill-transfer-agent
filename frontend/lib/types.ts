export type Arm = "base" | "skill";

export interface Provenance { quote: string; page: number }

export interface AlgorithmStep {
  order: number;
  operation: string;
  equation?: string | null;
  notes?: string | null;
  inferred: boolean;
  provenance?: Provenance | null;
}

export interface SkillParameter {
  symbol: string;
  name?: string;
  value: string;
  units?: string;
  role?: string;
  inferred: boolean;
  provenance?: Provenance | null;
}

export interface SkillPayload {
  name: string;
  description: string;
  intended_task: string;
  modality: string;
  input_requirements: string[];
  output_specification: string[];
  preprocessing_steps: AlgorithmStep[];
  algorithm_steps: AlgorithmStep[];
  equations: string[];
  initialization: string;
  parameters: SkillParameter[];
  stopping_criteria: string;
  postprocessing: string[];
  required_dependencies: string[];
  validation_checks: { name: string; description: string; expected: string }[];
  known_failure_modes: string[];
  citations: Provenance[];
}

export interface ValidationIssue { severity: string; field: string; message: string }

export interface Validation {
  ok: boolean;
  verified_quotes: number;
  unverified_quotes: number;
  inferred_ratio: number;
  issues: ValidationIssue[];
}

export interface Paper {
  id: string;
  title: string | null;
  filename: string;
  page_count: number;
  status: "uploaded" | "parsing" | "parsed" | "extracting" | "extracted" | "failed";
  error: string | null;
  created_at: string;
}

export interface SkillDetail {
  id: string;
  skill_id: string;
  version: number;
  model: string;
  validation: Validation;
  payload: SkillPayload;
  markdown: string;
  skill_name: string;
  paper_id: string | null;
  created_at: string;
}

export interface DatasetFile {
  id: string;
  filename: string;
  role: "input" | "ground_truth" | "aux";
  bytes: number;
  media_type: string;
  file_metadata: Record<string, unknown>;
  created_at: string;
}

export interface Dataset {
  id: string;
  name: string;
  modality: string;
  description: string;
  created_at: string;
  files?: DatasetFile[];
}

export interface Run {
  id: string;
  arm: Arm;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  error: string | null;
  totals: {
    summary?: string;
    iterations?: number;
    executions?: number;
    failed_executions?: number;
    duration_seconds?: number;
    usage?: { total_tokens?: number; cost?: number };
  };
  started_at: string | null;
  finished_at: string | null;
}

export interface Artifact {
  id: string;
  run_id: string | null;
  kind: "code" | "output" | "figure" | "report" | "log";
  path: string;
  media_type: string;
  bytes: number;
  artifact_metadata: { description?: string; declared?: boolean };
}

export interface Experiment {
  id: string;
  task_prompt: string;
  status: "pending" | "running" | "evaluating" | "completed" | "failed";
  config: Record<string, unknown>;
  paper_id: string | null;
  skill_version_id: string | null;
  dataset_id: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface MetricEntry { value: number | null; detail?: Record<string, unknown> }

export interface Comparison {
  experiment: Experiment;
  runs: Run[];
  /** The input dataset with its files, so the comparison can show the original. */
  dataset: Dataset | null;
  artifacts: Record<string, Artifact[]>;
  metrics: {
    system: Record<string, Record<string, MetricEntry>>;
    quality: Record<string, Record<string, MetricEntry>>;
    comparison: Record<string, { value: number } & Record<string, unknown>>;
  };
}

export interface RunEvent {
  run_id: string;
  arm: Arm;
  seq: number;
  node: string;
  kind: string;
  title: string;
  detail: string;
  payload: Record<string, unknown>;
  ts: string;
}

/** Where the agent asked the slice viewers to move, from a `show_slice` call. */
export interface ViewDirective {
  index: number;
  axis?: "axial" | "coronal" | "sagittal";
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  tool_calls: { used?: string[]; view?: ViewDirective };
  created_at: string;
}

export interface Conversation {
  id: string;
  experiment_id: string | null;
  title: string;
  created_at: string;
  messages?: Message[];
}
