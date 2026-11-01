import type { ThemeMode } from "../theme/store";
import type { Lang } from "../i18n";

export interface User {
  id: string;
  email: string;
  role: "admin" | "user";
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

// --- Modules (the Store) -------------------------------------------------------------------------

export type ModuleState = "installing" | "running" | "removing" | "failed";

/** Why a module does not fit this machine: `ram` (MB) or `gpu` (kind). */
export interface ModuleProblem {
  code: "ram" | "gpu";
  needed: string;
  have: string;
}

export interface ModuleHardware {
  ok: boolean;
  variant: string | null;
  problems: ModuleProblem[];
}

export interface ModuleInstalled {
  state: ModuleState;
  explicit: boolean;
  variant: string | null;
  version: string;
  error: string | null;
}

export interface ModuleEntry {
  id: string;
  name: string;
  version: string;
  category: string;
  description: { fr: string; en: string };
  license: string;
  provides: string[];
  requires: string[];
  exclusive: string[];
  variants: string[];
  web_ui: { service: string; port: number; path: string; strip_prefix: boolean } | null;
  secrets: string[];
  host_access: string[];
  offline: boolean;
  hardware: ModuleHardware;
  installed: ModuleInstalled | null;
}

export interface ModuleCatalog {
  modules: ModuleEntry[];
  hardware: { ram_mb: number; gpu: string };
}

export type ModuleAction = "install" | "uninstall";

export interface ModuleOperationRequest {
  action: ModuleAction;
  modules: string[];
  choices?: Record<string, string>;
  replace?: boolean;
  confirm_cascade?: boolean;
}

export interface ModuleLink {
  consumer: string;
  provider: string;
  capability: string;
}

export interface ModulePlan {
  steps: { action: ModuleAction; module: string }[];
  explicit: string[];
  installed: string[];
  auto_added: string[];
  cascade: string[];
  replaced: string[];
  auto_removed: string[];
  links_added: ModuleLink[];
  links_removed: ModuleLink[];
}

export interface ModuleOperationError {
  module: string | null;
  step: string | null;
  code: string;
  rolled_back?: string[];
  partial?: boolean;
}

export interface ModuleOperation {
  id: string;
  action: ModuleAction;
  modules: string[];
  state: "running" | "done" | "failed";
  plan: ModulePlan | null;
  error: ModuleOperationError | null;
}

/** `module.step` of the modules stream: one step of an install or removal. */
export interface ModuleStepEvent {
  operation_id: string | null;
  module: string;
  kind: string;
  step: string | null;
  ok: boolean;
  code: string | null;
}

/** A starter pack: a ready-made set of modules, with its fit for this machine. */
export interface ModulePack {
  id: string;
  name: { fr: string; en: string };
  description: { fr: string; en: string };
  modules: string[];
  hardware: { min_ram_mb: number; gpu: string };
  priority: number;
  fit: {
    ok: boolean;
    /** `module` is null when the pack itself asks for it. */
    problems: { module: string | null; code: "ram" | "gpu"; needed: string; have: string }[];
  };
  recommended: boolean;
  installed: boolean;
  installed_modules: string[];
}

export interface ModulePacks {
  packs: ModulePack[];
  problems: Record<string, string[]>;
  recommended: string | null;
}
