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

export type Phase = "interview" | "spec_review" | "plan_review" | "ready";
export const PHASES: readonly Phase[] = ["interview", "spec_review", "plan_review", "ready"];

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

export type JobKind = "reply" | "spec" | "plan";
