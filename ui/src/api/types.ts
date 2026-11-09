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
  /** True: no request of this project may reach a model that is not served on this machine. */
  local_only?: boolean;
  /** True: a plain-language summary is written at each milestone ("Explique-moi"). */
  explain_mode?: boolean;
  /** True: the planner proposes mockup variants and the user picks one before planning. */
  mockups_enabled?: boolean;
  /** True: a reviewer agent reads each task's diff between CI green and merge. */
  review_enabled?: boolean;
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

export type JobKind = "reply" | "spec" | "plan" | "start" | "explain" | "mockups";

/** A mockup proposed by the planner: plain text only, always rendered as escaped text. */
export interface MockupVariant {
  id: string;
  position: number;
  title: string;
  summary: string;
  wireframe: string;
  chosen: boolean;
}

/** Scheduler task states (ADR 0006). */
export const TASK_STATES = [
  "todo",
  "writing_tests",
  "implementing",
  "ci",
  "review",
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

/** Latest verdict of the reviewer agent on a task. */
export interface TaskReview {
  verdict: "approve" | "request_changes";
  issues: string[];
  attempt: number;
  /** Set when the approval was not really given: review_unparsable, review_unavailable... */
  warning: string | null;
}

export interface TaskDetail extends Task {
  runs: TaskRun[];
  /** A stable code (task_timeout, task_budget_reached...) when the task failed for it. */
  last_error?: string | null;
  review?: TaskReview | null;
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
  /** Plain-language summary of what was built (explain mode), else null. */
  explanation?: string | null;
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
  /** The task's own cost cap (null: none, or planner calls). */
  cap_usd?: string | null;
}

/** Estimated electricity of local models, apart from the API spend (ADR 0021). */
export interface CostElectricity {
  usd: string;
  seconds: number;
  calls: number;
  counts_in_budget: boolean;
  estimated: boolean;
}

/** `GET/PUT /settings/costs`: electricity of local models and the per-task cap. */
export interface CostSettings {
  electricity_price_kwh_usd: string | null;
  electricity_watts: number | null;
  electricity_counts_in_budget: boolean;
  electricity_enabled?: boolean;
  task_budget_multiplier: string | null;
  effective_task_budget_multiplier?: string;
  task_budget_floor_usd?: string;
}
export interface CostByModel extends CostLine {
  model: string | null;
  /** A free-tier model: its calls are counted as free. */
  free?: boolean;
}

/** The last price seen of a model (USD per million tokens) and whether it changed lately. */
export interface ModelPriceLine {
  model: string;
  prompt_per_million_usd: string | null;
  completion_per_million_usd: string | null;
  free: boolean;
  changed: boolean;
  previous_prompt_per_million_usd: string | null;
  previous_completion_per_million_usd: string | null;
  changed_at: string | null;
}

export interface ModelPrices {
  prices: ModelPriceLine[];
  change_window_days: number;
}
export interface CostByRole extends CostLine {
  role: string | null;
}

export interface ProjectCosts {
  budget_usd: string | null;
  spent_usd: string;
  /** What the providers charged; `spent_usd` adds the electricity only when it is counted. */
  api_usd?: string;
  electricity?: CostElectricity;
  tokens: { prompt: number; completion: number };
  estimate_usd: string | null;
  by_task: CostByTask[];
  by_model: CostByModel[];
  by_role: CostByRole[];
  /** Calls to free-tier models (counted as free). */
  free_calls?: number;
  /** Models used by this project whose price changed lately. */
  price_changes?: ModelPriceLine[];
  /** Calls answered by another model because the one chosen for the role could not. */
  fallbacks?: CostFallbacks;
  /** Compared with doing every call with the strongest model; null when it cannot be priced. */
  savings?: CostSavings | null;
}

export interface CostSavings {
  reference_model: string;
  reference_cost_usd: string;
  actual_cost_usd: string;
  /** Negative (a leading "-") when the project cost more than the reference model would have. */
  saved_usd: string;
  saved_percent: number;
}

/** `GET /projects/{id}/report` (ADR 0014): the end-of-project report. */
export interface ReportMilestone {
  ref: string;
  title: string;
  status: "pending" | "built" | "validated";
  validated_at: string | null;
  tasks_total: number;
  tasks_done: number;
  tasks_failed: number;
}

export interface ProjectReport {
  project: { id: string; name: string; phase: string; status: string; finished: boolean };
  span: { started_at: string | null; ended_at: string | null; duration_seconds: number | null };
  build: {
    milestones: ReportMilestone[];
    milestones_validated: number;
    tasks: { total: number; done: number; failed: number; escalated: number; attempts: number };
  };
  costs: {
    spent_usd: string;
    budget_usd: string | null;
    estimate_usd: string | null;
    budget_used_percent: number | null;
    estimate_delta_percent: number | null;
    tokens: { prompt: number; completion: number };
    savings: CostSavings | null;
    by_model: CostByModel[];
    by_role: CostByRole[];
    fallbacks: CostFallbacks;
  };
}

export interface CostFallbackLine extends CostLine {
  model: string;
  /** The first model of the chain that could not answer. */
  fallback_from: string | null;
}

export interface CostFallbacks {
  calls: number;
  total_calls: number;
  by_model: CostFallbackLine[];
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
  web_ui: {
    service: string;
    port: number;
    path: string;
    strip_prefix: boolean;
    public?: boolean;
  } | null;
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

// --- Model connections ----------------------------------------------------------------------------

export type ModelProvider = "openai" | "anthropic" | "openrouter" | "custom";

/** A connected model service. The API key is never part of it: it is only ever sent. */
export interface ModelConnection {
  name: string;
  provider: ModelProvider;
  model: string;
  base_url: string | null;
  default: boolean;
}

export interface ModelListing {
  models: ModelConnection[];
  /** The connection used by default, or null when the configured one applies. */
  default: string | null;
  /** What answers when no connection is the default (the built-in demo model in development). */
  configured_default: string;
  /** Models served here by installed backends (a route may name them). */
  local?: LocalModel[];
}

export interface ModelRequest {
  provider: ModelProvider;
  model: string;
  api_key: string;
  base_url?: string | null;
  make_default?: boolean;
}

export type ProbeCode =
  "ok" | "auth_failed" | "model_not_found" | "rate_limited" | "unreachable" | "failed";

export interface ModelProbe {
  ok: boolean;
  code: ProbeCode;
}

/** Per-role model routes: ordered models to try, the first one, then each fallback. */
export interface RoleRoutes {
  roles: string[];
  max_chain: number;
  /** What was set in the product (only roles that have a route). */
  routes: Record<string, string[]>;
  /** What each role really uses now (a route, else the setting, else the default). */
  effective: Record<string, string[]>;
}

/** One model's latest local benchmark (share of hidden cases passed, speed). */
export interface BenchmarkResult {
  model: string;
  quality: number;
  seconds: number;
  tokens_per_second: number | null;
  created_at: string;
  failed_tasks: number;
  tasks: number;
}

export interface Benchmarks {
  version: number;
  results: BenchmarkResult[];
  suggested_worker: string | null;
}

/** The state of the local benchmark job (one run at a time). */
export interface BenchmarkStatus {
  state: "idle" | "running";
  models: string[];
  /** The model being measured, and its position among `models`. */
  model: string | null;
  model_index: number;
  /** Tasks done for this model, out of `tasks`. */
  task: number;
  tasks: number;
  started_at: string | null;
  finished_at: string | null;
  /** Why the last run stopped early (a code such as `sandbox_unavailable`), else null. */
  error: string | null;
}

/** A model served on this machine by an installed backend: free, no key. */
export interface LocalModel {
  name: string;
  model: string;
  module: string;
}

export type PresetSlot = "local" | "cheap" | "strong";

export interface PresetView {
  id: string;
  required: PresetSlot[];
  available: boolean;
  missing: PresetSlot[];
  /** The routes the preset would give for the chosen slots (empty when unavailable). */
  routes: Record<string, string[]>;
}

export interface PresetsData {
  slots: Record<PresetSlot, string | null>;
  suggested: Record<PresetSlot, string | null>;
  local: string[];
  models: string[];
  presets: PresetView[];
}
