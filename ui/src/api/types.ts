import type { ThemeMode } from "../theme/store";
import type { Lang } from "../i18n";

export interface User {
  id: string;
  email: string;
  role: "admin";
  lang: Lang;
  theme: ThemeMode;
}

export interface Folder {
  id: string;
  name: string;
  position: number;
}

export type Phase = "interview" | "spec_review" | "plan_review" | "ready" | "building" | "done";
export const PHASES: readonly Phase[] = [
  "interview",
  "spec_review",
  "plan_review",
  "ready",
  "building",
  "done",
];

export interface Project {
  id: string;
  name: string;
  folder_id: string | null;
  created_at: string;
  /** Decimal serialized as a string (null = unlimited). */
  budget_usd?: string | null;
  status: "active" | "paused";
  phase: Phase;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  /** Client-only: an optimistic user message not yet confirmed by the server. */
  pending?: boolean;
}

export interface Spec {
  version: number;
  content: string;
  status: "draft" | "approved";
  created_at: string;
}

export type TaskSize = "S" | "M";
export type TaskRole = "backend" | "frontend" | "fullstack" | "devops" | "docs";

export interface PlanMilestone {
  id: string;
  title: string;
}

export interface PlanTask {
  id: string;
  title: string;
  milestone: string;
  depends_on: string[];
  files: string[];
  acceptance: string[];
  tests: string;
  size: TaskSize;
  role: TaskRole;
}

export interface PlanEstimate {
  tokens: number;
  /** Decimal serialized as a string. */
  cost_usd: string;
  milestones: { id: string; tokens: number; cost_usd: string }[];
}

export interface Plan {
  version: number;
  status: "draft" | "approved";
  plan: { milestones: PlanMilestone[]; tasks: PlanTask[] };
  estimate: PlanEstimate;
  created_at: string;
}

export type JobKind = "reply" | "spec" | "plan" | "start";

/** Scheduler task states (ADR 0006). */
export const TASK_STATES = [
  "todo",
  "writing_tests",
  "implementing",
  "ci",
  "merged",
  "failed",
  "blocked",
  "paused",
  "stopped",
] as const;
export type TaskState = (typeof TASK_STATES)[number];

export interface Task {
  ref: string;
  title: string;
  milestone: string;
  state: TaskState;
  attempts: number;
  escalated: boolean;
  /** Plan role (backend, frontend...) for planned tasks; free text, translated when known. */
  role: string;
  size: string;
  depends_on: string[];
}

export interface TaskRun {
  /** Which agent ran: test-writer, worker... */
  kind: string;
  attempt: number;
  model: string;
  state: string;
  started_at: string;
  finished_at: string | null;
  iterations: number;
  log_tail: string | null;
}

export interface TaskDetail extends Task {
  runs: TaskRun[];
}

export interface TaskDiff {
  diff: string;
  truncated: boolean;
}

export type MilestoneStatus = "pending" | "built" | "validated";

export interface Milestone {
  ref: string;
  title: string;
  status: MilestoneStatus;
  tag: string | null;
  /** Same-origin path of the running demo, e.g. /demo/<project>/M1/. */
  preview_path: string | null;
  built_at: string | null;
  validated_at: string | null;
}

/** Decimals travel as strings. */
export interface CostLine {
  cost_usd: string;
  prompt_tokens: number;
  completion_tokens: number;
  calls: number;
}
/** `ref` is null for planner calls (no task). */
export interface CostByTask extends CostLine {
  ref: string | null;
}
export interface CostByModel extends CostLine {
  model: string | null;
}
export interface CostByRole extends CostLine {
  role: string | null;
}

export interface ProjectCosts {
  budget_usd: string | null;
  spent_usd: string;
  tokens: { prompt: number; completion: number };
  estimate_usd: string | null;
  by_task: CostByTask[];
  by_model: CostByModel[];
  by_role: CostByRole[];
}

export interface GlobalCostRow {
  project_id: string;
  name: string;
  spent_usd: string;
  budget_usd: string | null;
  status: "active" | "paused";
}
