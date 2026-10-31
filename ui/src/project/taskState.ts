import type { Task, TaskState } from "../api/types";

/** Board columns of the Agents tab, in display order. */
export const TASK_GROUPS = ["todo", "running", "ci", "merged", "attention"] as const;
export type TaskGroup = (typeof TASK_GROUPS)[number];

const GROUP_OF: Record<TaskState, TaskGroup> = {
  todo: "todo",
  writing_tests: "running",
  implementing: "running",
  ci: "ci",
  merged: "merged",
  failed: "attention",
  blocked: "attention",
  paused: "attention",
  stopped: "attention",
};

export function groupOf(state: TaskState): TaskGroup {
  return GROUP_OF[state] ?? "attention";
}

export function groupTasks(tasks: Task[]): Record<TaskGroup, Task[]> {
  const out: Record<TaskGroup, Task[]> = {
    todo: [],
    running: [],
    ci: [],
    merged: [],
    attention: [],
  };
  for (const task of tasks) out[groupOf(task.state)].push(task);
  return out;
}

/** States where an agent is writing: the live log is polled only then. */
export function isRunning(state: TaskState): boolean {
  return state === "writing_tests" || state === "implementing";
}

export type TaskAction = "pause" | "resume" | "stop" | "retry";
export const TASK_ACTIONS: readonly TaskAction[] = ["pause", "resume", "stop", "retry"];

const ALLOWED: Record<TaskAction, readonly TaskState[]> = {
  pause: ["todo", "writing_tests", "implementing", "ci", "paused"],
  resume: ["paused"],
  stop: ["todo", "writing_tests", "implementing", "ci", "paused"],
  retry: ["paused", "stopped", "failed", "blocked"],
};

/** Mirror of the transitions the API accepts; the server stays the judge (409 wrong_state). */
export function canDo(action: TaskAction, state: TaskState): boolean {
  return ALLOWED[action].includes(state);
}

export type StateTone = "neutral" | "primary" | "success" | "warning" | "destructive";

export function stateTone(state: TaskState): StateTone {
  switch (state) {
    case "merged":
      return "success";
    case "writing_tests":
    case "implementing":
    case "ci":
      return "primary";
    case "failed":
    case "blocked":
      return "destructive";
    case "paused":
    case "stopped":
      return "warning";
    default:
      return "neutral";
  }
}
