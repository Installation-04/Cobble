import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../auth/AuthProvider";
import type {
  Milestone,
  Phase,
  Project,
  ProjectCosts,
  Task,
  TaskDetail,
  TaskState,
} from "../api/types";
import { setLang } from "../i18n";
import { GlobalView } from "../pages/GlobalViews";
import { ProjectPage } from "../pages/ProjectPage";
import { FakeEventSource, installFakeEventSource } from "../test/fakeEventSource";
import { WorkspaceProvider } from "../workspace/WorkspaceProvider";
import { classifyLine } from "./DiffView";
import { budgetState } from "./CostsTab";
import { canDo, groupTasks } from "./taskState";

const ID = "p1";

interface Reply {
  status?: number;
  json?: unknown;
  text?: string;
  headers?: Record<string, string>;
}
interface Call {
  method: string;
  path: string;
  body: unknown;
}

const error = (status: number, code: string): Reply => ({
  status,
  json: { error: { code, params: {} } },
});

const task = (ref: string, state: TaskState, over: Partial<Task> = {}): Task => ({
  ref,
  title: `Title of ${ref}`,
  milestone: "M1",
  state,
  attempts: 1,
  escalated: false,
  role: "backend",
  size: "S",
  depends_on: [],
  ...over,
});

const milestone = (ref: string, status: Milestone["status"], over: Partial<Milestone> = {}) => ({
  ref,
  title: `Milestone ${ref}`,
  status,
  tag: `milestone-${ref}`,
  preview_path: status === "pending" ? null : `/demo/${ID}/${ref}/`,
  built_at: status === "pending" ? null : "2026-03-01T10:00:00Z",
  validated_at: null,
  ...over,
});

const COSTS: ProjectCosts = {
  budget_usd: "10.00",
  spent_usd: "2.50",
  tokens: { prompt: 120000, completion: 30000 },
  estimate_usd: "2.00",
  by_task: [
    { ref: "T-001", cost_usd: "1.25", prompt_tokens: 60000, completion_tokens: 10000, calls: 4 },
    { ref: null, cost_usd: "0.0215", prompt_tokens: 5000, completion_tokens: 900, calls: 2 },
  ],
  by_model: [
    {
      model: "cheap-coder",
      cost_usd: "2.00",
      prompt_tokens: 90000,
      completion_tokens: 20000,
      calls: 9,
    },
  ],
  by_role: [{ role: "worker", cost_usd: "2.00", prompt_tokens: 1, completion_tokens: 2, calls: 3 }],
};

interface World {
  project: Project;
  tasks: Task[];
  milestones: Milestone[];
  costs: ProjectCosts;
  logs: Record<string, string>;
  diffs: Record<string, { diff: string; truncated: boolean }>;
  extra: (call: Call) => Reply | undefined;
}

function makeWorld(over: Partial<World> & { phase?: Phase } = {}): World {
  const { phase, ...rest } = over;
  return {
    project: {
      id: ID,
      name: "Todo",
      folder_id: null,
      created_at: "2026-01-01T00:00:00Z",
      status: "active",
      phase: phase ?? "building",
      budget_usd: "10.00",
    },
    tasks: [],
    milestones: [],
    costs: COSTS,
    logs: {},
    diffs: {},
    extra: () => undefined,
    ...rest,
  };
}

function stubFetch(world: World): { calls: Call[] } {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = (init.method ?? "GET").toUpperCase();
      const path = url.replace(/^\/api\/v1/, "");
      const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      const call = { method, path, body };
      calls.push(call);
      let reply = world.extra(call);
      if (!reply) {
        const key = `${method} ${path}`;
        const detail = /^GET \/projects\/p1\/tasks\/([\w-]+)$/.exec(key);
        const logs = /^GET \/projects\/p1\/tasks\/([\w-]+)\/logs\?offset=(\d+)$/.exec(key);
        const diff = /^GET \/projects\/p1\/tasks\/([\w-]+)\/diff$/.exec(key);
        if (key === "GET /folders") reply = { json: [] };
        else if (key === "GET /projects") reply = { json: [world.project] };
        else if (key === "GET /auth/me")
          reply = {
            json: { id: "u", email: "a@b.co", role: "admin", lang: "en", theme: "system" },
          };
        else if (key === "GET /projects/p1/messages") reply = { json: [] };
        else if (key === "GET /projects/p1/tasks") reply = { json: world.tasks };
        else if (key === "GET /projects/p1/milestones") reply = { json: world.milestones };
        else if (key === "GET /projects/p1/costs") reply = { json: world.costs };
        else if (key === "GET /costs")
          reply = {
            json: [
              {
                project_id: ID,
                name: "Todo",
                spent_usd: "2.50",
                budget_usd: "10.00",
                status: "active",
              },
              {
                project_id: "p2",
                name: "Blog",
                spent_usd: "0.10",
                budget_usd: null,
                status: "paused",
              },
            ],
          };
        else if (detail) {
          const found = world.tasks.find((t) => t.ref === detail[1]);
          reply = found
            ? {
                json: {
                  ...found,
                  runs: [
                    {
                      kind: "worker",
                      attempt: 1,
                      model: "cheap-coder",
                      state: "running",
                      started_at: "2026-03-01T10:00:00Z",
                      finished_at: null,
                      iterations: 3,
                      log_tail: null,
                    },
                  ],
                } satisfies TaskDetail,
              }
            : error(404, "not_found");
        } else if (logs) {
          const full = world.logs[logs[1]] ?? "";
          reply = {
            text: full.slice(Number(logs[2])),
            headers: { "X-Next-Offset": String(full.length), "Content-Type": "text/plain" },
          };
        } else if (diff) reply = { json: world.diffs[diff[1]] ?? { diff: "", truncated: false } };
        else reply = error(404, "not_found");
      }
      const status = reply.status ?? 200;
      return new Response(reply.text ?? JSON.stringify(reply.json ?? {}), {
        status,
        headers: { "Content-Type": "application/json", ...reply.headers },
      });
    }),
  );
  return { calls };
}

async function renderAt(route: string) {
  await setLang("en");
  render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>
        <WorkspaceProvider>
          <Routes>
            <Route path="projects/:id" element={<ProjectPage />} />
            <Route path="agents" element={<GlobalView view="agents" />} />
            <Route path="demos" element={<GlobalView view="demos" />} />
            <Route path="costs" element={<GlobalView view="costs" />} />
          </Routes>
        </WorkspaceProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

async function renderProject(tab: string) {
  await renderAt(`/projects/${ID}?tab=${tab}`);
  await screen.findByTestId("project-page");
  await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
}

const count = (calls: Call[], suffix: string) =>
  calls.filter((c) => c.method === "GET" && c.path.endsWith(suffix)).length;

beforeEach(() => installFakeEventSource());
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("task helpers", () => {
  it("groups states into board columns", () => {
    const g = groupTasks([
      task("T-001", "todo"),
      task("T-002", "writing_tests"),
      task("T-003", "implementing"),
      task("T-004", "ci"),
      task("T-005", "merged"),
      task("T-006", "failed"),
      task("T-007", "paused"),
      task("T-008", "stopped"),
      task("T-009", "blocked"),
    ]);
    expect(g.todo).toHaveLength(1);
    expect(g.running.map((t) => t.ref)).toEqual(["T-002", "T-003"]);
    expect(g.ci).toHaveLength(1);
    expect(g.merged).toHaveLength(1);
    expect(g.attention).toHaveLength(4);
  });

  it("allows only the valid actions per state", () => {
    expect(canDo("pause", "implementing")).toBe(true);
    expect(canDo("retry", "implementing")).toBe(false);
    expect(canDo("resume", "paused")).toBe(true);
    expect(canDo("retry", "stopped")).toBe(true);
    expect(canDo("stop", "failed")).toBe(false);
    expect(canDo("pause", "merged")).toBe(false);
  });

  it("classifies unified diff lines", () => {
    expect(classifyLine("+++ b/a.py")).toBe("meta");
    expect(classifyLine("@@ -1 +1 @@")).toBe("hunk");
    expect(classifyLine("+x = 1")).toBe("added");
    expect(classifyLine("-x = 0")).toBe("removed");
    expect(classifyLine(" x = 2")).toBe("context");
  });

  it("computes budget levels at 80 % and 100 %", () => {
    expect(budgetState("1", "10")?.level).toBe("ok");
    expect(budgetState("8", "10")?.level).toBe("warning");
    expect(budgetState("10", "10")?.level).toBe("danger");
    expect(budgetState("1", null)).toBeNull();
  });
});

describe("Plan tab: start building", () => {
  it("starts the build, shows progress and follows the phase events", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    const world = makeWorld({ phase: "ready" });
    const { calls } = stubFetch(world);
    world.extra = (call) => {
      if (call.method === "GET" && call.path === "/projects/p1/plan")
        return {
          json: {
            version: 1,
            status: "approved",
            created_at: "2026-01-01T00:00:00Z",
            plan: { milestones: [], tasks: [] },
            estimate: { tokens: 1, cost_usd: "0.1", milestones: [] },
          },
        };
      return undefined;
    };
    const original = fetch;
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) =>
      init?.method === "POST" ? gate.then(() => original(url, init)) : original(url, init),
    );
    await renderProject("plan");
    const button = await screen.findByTestId("start-building");
    expect(button).toBeEnabled();
    await userEvent.click(button);
    expect(screen.getByTestId("start-building")).toBeDisabled();
    expect(screen.getByTestId("start-building")).toHaveTextContent("Starting…");
    release();
    await waitFor(() =>
      expect(calls.some((c) => c.method === "POST" && c.path === "/projects/p1/start")).toBe(true),
    );
    // Still waiting for the worker: the spinner stays until the stream says otherwise.
    FakeEventSource.last.emit("job.started", { kind: "start" });
    FakeEventSource.last.emit("phase.changed", { phase: "building" });
    expect(await screen.findByTestId("plan-building")).toBeVisible();
    expect(screen.queryByTestId("start-building")).not.toBeInTheDocument();
  });

  it("shows API errors and translated start job failures", async () => {
    const world = makeWorld({ phase: "ready" });
    stubFetch(world);
    world.extra = (call) => {
      if (call.path === "/projects/p1/plan" && call.method === "GET")
        return {
          json: {
            version: 1,
            status: "approved",
            created_at: "2026-01-01T00:00:00Z",
            plan: { milestones: [], tasks: [] },
            estimate: { tokens: 1, cost_usd: "0.1", milestones: [] },
          },
        };
      if (call.method === "POST" && call.path === "/projects/p1/start")
        return error(503, "queue_unavailable");
      return undefined;
    };
    await renderProject("plan");
    await userEvent.click(await screen.findByTestId("start-building"));
    expect(await screen.findByTestId("plan-error")).toHaveTextContent(
      "The job queue is unavailable",
    );
    expect(screen.getByTestId("start-building")).toBeEnabled();

    FakeEventSource.last.emit("job.failed", { kind: "start", code: "repo_error" });
    const banner = await screen.findByTestId("job-failed");
    expect(banner).toHaveAttribute("data-code", "repo_error");
    expect(banner).toHaveTextContent("repository could not be created");
  });

  it("adds Building and Done to the phase stepper", async () => {
    stubFetch(makeWorld({ phase: "building" }));
    await renderProject("chat");
    expect(await screen.findByTestId("phase-step-building")).toHaveAttribute(
      "data-state",
      "current",
    );
    expect(screen.getByTestId("phase-step-done")).toHaveAttribute("data-state", "upcoming");
    expect(screen.getByTestId("phase-step-ready")).toHaveAttribute("data-state", "done");
    expect(screen.getByTestId("phase-step-building")).toHaveTextContent("Building");
  });
});

describe("Agents tab", () => {
  const tasks = [
    task("T-001", "merged"),
    task("T-002", "implementing", {
      escalated: true,
      attempts: 3,
      role: "frontend",
      size: "M",
      milestone: "M2",
    }),
    task("T-003", "todo"),
    task("T-004", "failed"),
  ];

  it("shows an idle state before the build, with the right reason per phase", async () => {
    stubFetch(makeWorld({ phase: "plan_review" }));
    await renderProject("agents");
    expect(await screen.findByTestId("agents-empty")).toHaveAttribute("data-reason", "notStarted");
  });

  it("groups tasks in columns with counters and rich cards", async () => {
    stubFetch(makeWorld({ tasks }));
    await renderProject("agents");
    await screen.findByTestId("agent-card-T-001");
    expect(screen.getByTestId("agents-count-merged")).toHaveTextContent("1");
    expect(screen.getByTestId("agents-count-running")).toHaveTextContent("1");
    expect(screen.getByTestId("agents-count-todo")).toHaveTextContent("1");
    expect(screen.getByTestId("agents-count-ci")).toHaveTextContent("0");
    expect(screen.getByTestId("agents-count-attention")).toHaveTextContent("1");
    expect(screen.getByTestId("agents-summary")).toHaveTextContent("1 of 4 tasks merged");

    const running = within(screen.getByTestId("agents-col-running")).getByTestId(
      "agent-card-T-002",
    );
    expect(running).toHaveAttribute("data-state", "implementing");
    expect(running).toHaveTextContent("Title of T-002");
    expect(within(running).getByTestId("card-milestone")).toHaveTextContent("M2");
    expect(within(running).getByTestId("card-role")).toHaveTextContent("Frontend");
    expect(within(running).getByTestId("card-size")).toHaveTextContent("M");
    expect(within(running).getByTestId("card-attempts")).toHaveTextContent("3 attempts");
    expect(within(running).getByTestId("card-escalated")).toBeVisible();
    expect(within(running).getByTestId("card-state")).toHaveTextContent("Implementing");
  });

  it("moves a card when task.updated arrives and fetches unknown tasks", async () => {
    const world = makeWorld({ tasks });
    const { calls } = stubFetch(world);
    await renderProject("agents");
    await screen.findByTestId("agent-card-T-003");
    FakeEventSource.last.emit("task.updated", { task_id: "T-003", state: "ci", attempts: 2 });
    const moved = within(await screen.findByTestId("agents-col-ci")).getByTestId(
      "agent-card-T-003",
    );
    expect(moved).toHaveTextContent("2 attempts");
    expect(screen.getByTestId("agents-count-todo")).toHaveTextContent("0");

    const before = count(calls, "/tasks");
    world.tasks = [...tasks, task("C-001", "todo")];
    FakeEventSource.last.emit("task.updated", { task_id: "C-001", state: "todo", attempts: 0 });
    expect(await screen.findByTestId("agent-card-C-001")).toBeVisible();
    expect(count(calls, "/tasks")).toBe(before + 1);
  });

  it("polls the log every 2 s while running, appends, and stops when the task leaves running", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const world = makeWorld({ tasks, logs: { "T-002": "line one\n" } });
    const { calls } = stubFetch(world);
    await renderProject("agents");
    const user = userEvent.setup({ advanceTimers: (ms) => vi.advanceTimersByTime(ms) });
    await user.click(await screen.findByTestId("agent-card-T-002"));

    const log = await screen.findByTestId("task-log");
    expect(log).toHaveAttribute("aria-live", "polite");
    await waitFor(() => expect(log).toHaveTextContent("line one"));
    expect(screen.getByTestId("log-live")).toBeVisible();
    const logCalls = () => calls.filter((c) => c.path.includes("/T-002/logs"));
    expect(logCalls().length).toBeGreaterThan(0);
    expect(logCalls()[0].path).toBe("/projects/p1/tasks/T-002/logs?offset=0");
    expect(await screen.findByTestId("run-row")).toHaveTextContent("cheap-coder");

    world.logs["T-002"] = "line one\nline two\n";
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    await waitFor(() => expect(log).toHaveTextContent("line two"));
    expect(log.textContent?.match(/line one/g)).toHaveLength(1);
    expect(logCalls().at(-1)?.path).toBe("/projects/p1/tasks/T-002/logs?offset=9");

    // The task leaves the running state: one final read, then no more polling.
    world.logs["T-002"] += "done\n";
    FakeEventSource.last.emit("task.updated", { task_id: "T-002", state: "ci", attempts: 3 });
    await waitFor(() => expect(log).toHaveTextContent("done"));
    await waitFor(() => expect(screen.queryByTestId("log-live")).not.toBeInTheDocument());
    const settled = logCalls().length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(7000);
    });
    expect(logCalls()).toHaveLength(settled);
  });

  it("renders the diff with added and removed lines and the truncation notice", async () => {
    const world = makeWorld({
      tasks,
      diffs: {
        "T-001": {
          diff: "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old = 1\n+new = 2\n keep = 3\n",
          truncated: true,
        },
      },
    });
    stubFetch(world);
    await renderProject("agents");
    await userEvent.click(await screen.findByTestId("agent-card-T-001"));
    await userEvent.click(await screen.findByTestId("drawer-tab-diff"));
    const lines = await screen.findAllByTestId("diff-line");
    const kinds = lines.map((l) => l.getAttribute("data-kind"));
    expect(kinds).toEqual(["meta", "meta", "meta", "hunk", "removed", "added", "context"]);
    expect(lines[4]).toHaveTextContent("-old = 1");
    expect(lines[5]).toHaveClass("bg-diff-added");
    expect(lines[4]).toHaveClass("bg-diff-removed");
    expect(screen.getByTestId("diff-truncated")).toBeVisible();
  });

  it("shows an empty diff message", async () => {
    stubFetch(makeWorld({ tasks }));
    await renderProject("agents");
    await userEvent.click(await screen.findByTestId("agent-card-T-003"));
    await userEvent.click(await screen.findByTestId("drawer-tab-diff"));
    expect(await screen.findByTestId("diff-empty")).toBeVisible();
  });

  it("enables only the valid actions and applies the answer of retry", async () => {
    const world = makeWorld({ tasks });
    const { calls } = stubFetch(world);
    world.extra = (call) => {
      if (call.method === "POST" && call.path === "/projects/p1/tasks/T-004/retry")
        return { json: task("T-004", "todo", { attempts: 0 }) };
      return undefined;
    };
    await renderProject("agents");
    await userEvent.click(await screen.findByTestId("agent-card-T-004"));
    expect(screen.getByTestId("task-retry")).toBeEnabled();
    expect(screen.getByTestId("task-pause")).toBeDisabled();
    expect(screen.getByTestId("task-resume")).toBeDisabled();
    expect(screen.getByTestId("task-stop")).toBeDisabled();
    await userEvent.click(screen.getByTestId("task-retry"));
    await waitFor(() => expect(screen.getByTestId("drawer-state")).toHaveTextContent("To do"));
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/T-004/retry"))).toBe(true);
    expect(screen.getByTestId("task-pause")).toBeEnabled();
    expect(screen.getByTestId("task-retry")).toBeDisabled();
  });

  it("translates a 409 wrong_state answer", async () => {
    const world = makeWorld({ tasks });
    stubFetch(world);
    world.extra = (call) =>
      call.method === "POST" && call.path.endsWith("/T-003/pause")
        ? error(409, "wrong_state")
        : undefined;
    await renderProject("agents");
    await userEvent.click(await screen.findByTestId("agent-card-T-003"));
    await userEvent.click(screen.getByTestId("task-pause"));
    expect(await screen.findByTestId("task-action-error")).toHaveTextContent(
      "This action is not possible in the current state.",
    );
  });

  it("asks for confirmation before stopping a task", async () => {
    const world = makeWorld({ tasks });
    const { calls } = stubFetch(world);
    world.extra = (call) =>
      call.method === "POST" && call.path.endsWith("/T-002/stop")
        ? { json: task("T-002", "stopped") }
        : undefined;
    await renderProject("agents");
    await userEvent.click(await screen.findByTestId("agent-card-T-002"));
    await userEvent.click(screen.getByTestId("task-stop"));
    const dialog = await screen.findByTestId("confirm-dialog");
    expect(calls.some((c) => c.path.endsWith("/stop"))).toBe(false);
    await userEvent.click(within(dialog).getByTestId("confirm-submit"));
    await waitFor(() => expect(screen.getByTestId("drawer-state")).toHaveTextContent("Stopped"));
  });

  it("refetches tasks, milestones and costs after a reconnect", async () => {
    const world = makeWorld({ tasks, milestones: [milestone("M1", "pending")] });
    const { calls } = stubFetch(world);
    await renderProject("agents");
    await screen.findByTestId("agent-card-T-001");
    const es = FakeEventSource.last;
    es.open();
    const before = {
      t: count(calls, "/tasks"),
      m: count(calls, "/milestones"),
      c: count(calls, "/costs"),
    };
    es.drop();
    world.tasks = [...tasks, task("T-005", "todo")];
    es.open();
    expect(await screen.findByTestId("agent-card-T-005")).toBeVisible();
    await waitFor(() => {
      expect(count(calls, "/tasks")).toBe(before.t + 1);
      expect(count(calls, "/milestones")).toBe(before.m + 1);
      expect(count(calls, "/costs")).toBe(before.c + 1);
    });
  });
});

describe("Demo tab", () => {
  it("lists milestones with status, built date and links only when built", async () => {
    stubFetch(
      makeWorld({
        milestones: [milestone("M1", "built"), milestone("M2", "pending")],
      }),
    );
    await renderProject("demo");
    const card = await screen.findByTestId("milestone-card-M1");
    expect(within(card).getByTestId("milestone-status")).toHaveTextContent("Built");
    expect(within(card).getByTestId("milestone-built-at")).toHaveTextContent("Built");
    const link = within(card).getByTestId("demo-open-M1");
    expect(link).toHaveAttribute("href", "/demo/p1/M1/");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    const frame = within(card).getByTestId("demo-frame-M1");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts allow-forms");
    expect(frame).toHaveAttribute("src", "/demo/p1/M1/");

    const pending = screen.getByTestId("milestone-card-M2");
    expect(within(pending).getByTestId("milestone-status")).toHaveTextContent("Pending");
    expect(within(pending).queryByTestId("demo-open-M2")).not.toBeInTheDocument();
    expect(within(pending).queryByTestId("milestone-validate-M2")).not.toBeInTheDocument();
  });

  it("validates a milestone and follows milestone.updated", async () => {
    const world = makeWorld({ milestones: [milestone("M1", "built")] });
    const { calls } = stubFetch(world);
    world.extra = (call) => {
      if (call.method === "POST" && call.path === "/projects/p1/milestones/M1/validate") {
        world.milestones = [milestone("M1", "validated", { validated_at: "2026-03-02T10:00:00Z" })];
        return { json: { milestone: world.milestones[0] } };
      }
      return undefined;
    };
    await renderProject("demo");
    await userEvent.click(await screen.findByTestId("milestone-validate-M1"));
    await waitFor(() =>
      expect(screen.getByTestId("milestone-card-M1")).toHaveAttribute("data-status", "validated"),
    );
    expect(calls.some((c) => c.path.endsWith("/M1/validate"))).toBe(true);
    expect(screen.getByTestId("milestone-validate-M1")).toBeDisabled();

    world.milestones = [milestone("M1", "pending")];
    FakeEventSource.last.emit("milestone.updated", { ref: "M1", status: "pending" });
    await waitFor(() =>
      expect(screen.getByTestId("milestone-card-M1")).toHaveAttribute("data-status", "pending"),
    );
  });

  it("shows a translated error when validation is refused", async () => {
    const world = makeWorld({ milestones: [milestone("M1", "built")] });
    stubFetch(world);
    world.extra = (call) =>
      call.method === "POST" && call.path.endsWith("/validate")
        ? error(409, "wrong_state")
        : undefined;
    await renderProject("demo");
    await userEvent.click(await screen.findByTestId("milestone-validate-M1"));
    expect(await screen.findByTestId("milestone-error")).toHaveTextContent("not possible");
  });

  it("posts a comment (1-2000 chars) and links to the created task in the Agents tab", async () => {
    const world = makeWorld({
      milestones: [milestone("M1", "built")],
      tasks: [task("T-001", "merged")],
    });
    const { calls } = stubFetch(world);
    world.extra = (call) => {
      if (call.method === "POST" && call.path === "/projects/p1/milestones/M1/comments") {
        const created = task("C-001", "todo", { attempts: 0 });
        world.tasks = [...world.tasks, created];
        world.milestones = [milestone("M1", "pending")];
        return { status: 201, json: { task: created } };
      }
      return undefined;
    };
    await renderProject("demo");
    await userEvent.click(await screen.findByTestId("milestone-comment-M1"));
    const dialog = await screen.findByTestId("comment-dialog");
    const submit = within(dialog).getByTestId("comment-submit");
    expect(submit).toBeDisabled();
    await userEvent.type(within(dialog).getByTestId("comment-input"), "   ");
    expect(submit).toBeDisabled();
    await userEvent.type(
      within(dialog).getByTestId("comment-input"),
      "Please add a due date to each task",
    );
    expect(within(dialog).getByTestId("comment-count")).toHaveTextContent("/ 2000");
    expect(submit).toBeEnabled();
    await userEvent.click(submit);

    const notice = await screen.findByTestId("comment-created");
    expect(notice).toHaveTextContent("Task C-001 created");
    expect(calls.find((c) => c.path.endsWith("/comments"))?.body).toEqual({
      content: "Please add a due date to each task",
    });
    expect(screen.queryByTestId("comment-dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("milestone-card-M1")).toHaveAttribute("data-status", "pending");

    await userEvent.click(screen.getByTestId("comment-created-link"));
    expect(await screen.findByTestId("agent-card-C-001")).toBeVisible();
    expect(await screen.findByTestId("task-drawer")).toHaveTextContent("C-001");
  });

  it("keeps the dialog open and shows the error when the comment is refused", async () => {
    const world = makeWorld({ milestones: [milestone("M1", "built")] });
    stubFetch(world);
    world.extra = (call) =>
      call.method === "POST" && call.path.endsWith("/comments")
        ? error(409, "wrong_state")
        : undefined;
    await renderProject("demo");
    await userEvent.click(await screen.findByTestId("milestone-comment-M1"));
    await userEvent.type(screen.getByTestId("comment-input"), "x");
    await userEvent.click(screen.getByTestId("comment-submit"));
    expect(await screen.findByTestId("comment-error")).toHaveTextContent("not possible");
    expect(screen.getByTestId("comment-dialog")).toBeVisible();
  });

  it("reverts only after a destructive confirmation", async () => {
    const world = makeWorld({ milestones: [milestone("M1", "validated")] });
    const { calls } = stubFetch(world);
    world.extra = (call) => {
      if (call.method === "POST" && call.path.endsWith("/M1/revert")) {
        world.milestones = [milestone("M1", "pending")];
        return { status: 202, json: {} };
      }
      return undefined;
    };
    await renderProject("demo");
    await userEvent.click(await screen.findByTestId("milestone-revert-M1"));
    const dialog = await screen.findByTestId("confirm-dialog");
    expect(dialog).toHaveTextContent("Revert milestone M1?");
    expect(calls.some((c) => c.path.endsWith("/revert"))).toBe(false);
    await userEvent.click(within(dialog).getByTestId("confirm-submit"));
    await waitFor(() =>
      expect(screen.getByTestId("milestone-card-M1")).toHaveAttribute("data-status", "pending"),
    );
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/M1/revert"))).toBe(true);
  });
});

describe("Costs tab", () => {
  it("renders totals, estimate vs actual and the tables (English)", async () => {
    stubFetch(makeWorld());
    await renderProject("costs");
    expect(await screen.findByTestId("costs-spent")).toHaveTextContent("$2.50");
    expect(screen.getByTestId("costs-budget")).toHaveTextContent("of $10.00");
    expect(screen.getByTestId("costs-tokens-total")).toHaveTextContent("150,000");
    expect(screen.getByTestId("costs-tokens-split")).toHaveTextContent("120,000 in");
    expect(screen.getByTestId("costs-estimate")).toHaveTextContent("$2.00");
    expect(screen.getByTestId("costs-delta")).toHaveTextContent("25 % above the estimate");
    const bar = screen.getByTestId("budget-bar");
    expect(bar).toHaveAttribute("role", "progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "25");
    expect(bar).toHaveAttribute("data-level", "ok");
    const rows = within(screen.getByTestId("costs-by-task")).getAllByTestId("costs-by-task-row");
    expect(rows[0]).toHaveTextContent("T-001");
    expect(rows[0]).toHaveTextContent("$1.25");
    expect(rows[0]).toHaveTextContent("60,000");
    expect(rows[1]).toHaveTextContent("Planning (no task)");
    expect(rows[1]).toHaveTextContent("$0.0215");
    expect(within(screen.getByTestId("costs-by-model")).getByText("cheap-coder")).toBeVisible();
    expect(screen.getByTestId("costs-by-role")).toHaveTextContent("worker");
    expect(screen.getAllByRole("columnheader", { name: "Tokens in" }).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("costs-paused")).not.toBeInTheDocument();
  });

  it("formats numbers and text in French", async () => {
    stubFetch(makeWorld());
    await renderProject("costs");
    await screen.findByTestId("costs-spent");
    await act(async () => {
      await setLang("fr");
    });
    await waitFor(() => expect(screen.getByTestId("costs-budget")).toHaveTextContent("sur"));
    // Intl uses a comma decimal separator and a (narrow) no-break space between digits
    expect(screen.getByTestId("costs-spent").textContent).toMatch(/2,50/);
    expect(screen.getByTestId("costs-tokens-total").textContent?.replace(/\s/g, " ")).toBe(
      "150 000",
    );
    expect(screen.getByTestId("costs-estimate").textContent).toMatch(/2,00/);
    expect(screen.getByTestId("costs-by-task")).toBeVisible();
    expect(screen.getAllByRole("columnheader", { name: "Jetons en entrée" })).toHaveLength(3);
  });

  it("switches to the warning state at 80 % and the danger state with a paused notice at 100 %", async () => {
    const world = makeWorld({ costs: { ...COSTS, spent_usd: "8.00" } });
    stubFetch(world);
    await renderProject("costs");
    expect(await screen.findByTestId("budget-bar")).toHaveAttribute("data-level", "warning");
    expect(screen.getByTestId("budget-state")).toHaveTextContent("close to the limit");
    expect(screen.queryByTestId("costs-paused")).not.toBeInTheDocument();

    world.costs = { ...COSTS, spent_usd: "10.00" };
    world.project = { ...world.project, status: "paused" };
    FakeEventSource.last.emit("task.updated", { task_id: "T-001", state: "paused", attempts: 1 });
    await waitFor(
      () => expect(screen.getByTestId("budget-bar")).toHaveAttribute("data-level", "danger"),
      {
        timeout: 4000,
      },
    );
    expect(screen.getByTestId("budget-state")).toHaveTextContent("budget is reached");
    await waitFor(() => expect(screen.getByTestId("costs-paused")).toBeVisible());
  });

  it("handles a project without budget or estimate", async () => {
    stubFetch(makeWorld({ costs: { ...COSTS, budget_usd: null, estimate_usd: null } }));
    await renderProject("costs");
    expect(await screen.findByTestId("costs-budget")).toHaveTextContent("No budget set");
    expect(screen.queryByTestId("budget-bar")).not.toBeInTheDocument();
    expect(screen.getByTestId("costs-estimate")).toHaveTextContent("Not available");
  });
});

describe("Global views", () => {
  it("lists projects with their phase and a link into the right tab", async () => {
    stubFetch(makeWorld());
    await renderAt("/agents");
    const row = await screen.findByTestId("view-agents-row");
    expect(row).toHaveTextContent("Todo");
    expect(within(row).getByTestId("view-phase")).toHaveTextContent("Building");
    expect(within(row).getByRole("link")).toHaveAttribute("href", "/projects/p1?tab=agents");
  });

  it("links demos to the demo tab", async () => {
    stubFetch(makeWorld());
    await renderAt("/demos");
    const row = await screen.findByTestId("view-demos-row");
    expect(within(row).getByRole("link")).toHaveAttribute("href", "/projects/p1?tab=demo");
  });

  it("shows the spending of every project from GET /costs", async () => {
    stubFetch(makeWorld());
    await renderAt("/costs");
    const rows = await screen.findAllByTestId("view-costs-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("$2.50");
    expect(rows[0]).toHaveTextContent("$10.00");
    expect(within(rows[0]).getByRole("link")).toHaveAttribute("href", "/projects/p1?tab=costs");
    expect(rows[1]).toHaveTextContent("No budget");
    expect(rows[1]).toHaveTextContent("Paused");
    expect(screen.getByTestId("view-costs-total")).toHaveTextContent("$2.60");
  });
});
