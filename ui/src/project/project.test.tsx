import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage, Phase, Plan, Project, Spec } from "../api/types";
import { setLang } from "../i18n";
import { ProjectPage } from "../pages/ProjectPage";
import { FakeEventSource, installFakeEventSource } from "../test/fakeEventSource";
import { mockFetch, renderApp, type Handler } from "../test/utils";
import { WorkspaceProvider } from "../workspace/WorkspaceProvider";

const PROJECT_ID = "p1";

const PLAN: Plan = {
  version: 1,
  status: "draft",
  created_at: "2026-01-01T00:00:00Z",
  plan: {
    milestones: [
      { id: "M1", title: "Backend API" },
      { id: "M2", title: "Web UI" },
    ],
    tasks: [
      {
        id: "T-001",
        title: "Create the todo endpoints",
        milestone: "M1",
        depends_on: [],
        files: ["app/api/todos.py", "tests/test_todos.py"],
        acceptance: ["POST /api/todos returns 201"],
        tests: "tests/test_todos.py",
        size: "S",
        role: "backend",
      },
      {
        id: "T-002",
        title: "Build the list page",
        milestone: "M2",
        depends_on: ["T-001"],
        files: ["src/pages/List.tsx"],
        acceptance: ["Tasks are listed", "A task can be completed"],
        tests: "src/pages/List.test.tsx",
        size: "M",
        role: "frontend",
      },
    ],
  },
  estimate: {
    tokens: 150000,
    cost_usd: "1234.5",
    milestones: [
      { id: "M1", tokens: 30000, cost_usd: "0.06" },
      { id: "M2", tokens: 75000, cost_usd: "0.15" },
    ],
  },
};

interface World {
  project: Project;
  messages: ChatMessage[];
  spec: Spec | null;
  plan: Plan | null;
}

function setup(initial: Partial<World> = {}, extra: Record<string, Handler> = {}) {
  const world: World = {
    project: {
      id: PROJECT_ID,
      name: "Todo",
      folder_id: null,
      created_at: "2026-01-01T00:00:00Z",
      status: "active",
      phase: "interview",
    },
    messages: [],
    spec: null,
    plan: null,
    ...initial,
  };
  const notFound = { status: 404, body: { error: { code: "not_found", params: {} } } };
  const { calls } = mockFetch({
    "GET /folders": () => ({ body: [] }),
    "GET /projects": () => ({ body: [world.project] }),
    "GET /auth/me": () => ({
      body: { id: "u", email: "a@b.co", role: "admin", lang: "en", theme: "system" },
    }),
    [`GET /projects/${PROJECT_ID}/messages`]: () => ({ body: world.messages }),
    [`GET /projects/${PROJECT_ID}/spec`]: () => (world.spec ? { body: world.spec } : notFound),
    [`GET /projects/${PROJECT_ID}/plan`]: () => (world.plan ? { body: world.plan } : notFound),
    ...extra,
  });
  return { world, calls };
}

async function renderProject() {
  const view = await renderApp(
    <WorkspaceProvider>
      <Routes>
        <Route path="projects/:id" element={<ProjectPage />} />
      </Routes>
    </WorkspaceProvider>,
    `/projects/${PROJECT_ID}`,
  );
  await screen.findByTestId("project-page");
  await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
  await screen.findByTestId("chat-input");
  return view;
}

const msg = (id: string, role: "user" | "assistant", content: string): ChatMessage => ({
  id,
  role,
  content,
  created_at: "2026-01-01T00:00:00Z",
});

const SPEC: Spec = {
  version: 1,
  content: "# Todo spec\n\nA **simple** list. [docs](https://example.com)",
  status: "draft",
  created_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => installFakeEventSource());
afterEach(() => vi.unstubAllGlobals());

describe("Chat tab", () => {
  it("sends with Enter, shows the message optimistically and reconciles with message.created", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    const { world, calls } = setup(
      {},
      {
        [`POST /projects/${PROJECT_ID}/messages`]: ({ body }) => {
          const stored = msg("m1", "user", (body as { content: string }).content);
          world.messages.push(stored);
          return { status: 202, body: { message: stored } };
        },
      },
    );
    // Hold the POST answer back to observe the optimistic state.
    const original = fetch;
    vi.stubGlobal("fetch", (url: string, init?: RequestInit) =>
      init?.method === "POST" ? gate.then(() => original(url, init)) : original(url, init),
    );
    await renderProject();
    expect(await screen.findByTestId("chat-empty")).toBeVisible();

    await userEvent.type(screen.getByTestId("chat-input"), "A to-do app{Enter}");
    // Optimistic bubble first (pending), input cleared, server not answered yet
    const bubble = await screen.findByTestId("chat-message-user");
    expect(bubble).toHaveAttribute("data-pending", "true");
    expect(bubble).toHaveTextContent("A to-do app");
    expect(screen.getByTestId("chat-input")).toHaveValue("");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    release();
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/messages"))?.body).toEqual({
        content: "A to-do app",
      }),
    );

    // The typing indicator shows while the reply job runs
    expect(await screen.findByTestId("chat-typing")).toBeVisible();

    // SSE echo of the stored message must not duplicate the bubble
    FakeEventSource.last.emit("message.created", { message: world.messages[0] });
    expect(screen.getAllByText("A to-do app")).toHaveLength(1);
    await waitFor(() =>
      expect(screen.getAllByTestId("chat-message-user")[0]).not.toHaveAttribute("data-pending"),
    );

    // Assistant reply: rendered as Markdown, typing indicator gone
    FakeEventSource.last.emit("message.created", {
      message: msg("m2", "assistant", "What **platform** do you want?"),
    });
    const reply = await screen.findByTestId("chat-message-assistant");
    expect(within(reply).getByText("platform").tagName).toBe("STRONG");
    expect(screen.queryByTestId("chat-typing")).not.toBeInTheDocument();
  });

  it("Shift+Enter inserts a newline instead of sending", async () => {
    const { calls } = setup();
    await renderProject();
    await userEvent.type(screen.getByTestId("chat-input"), "line1{Shift>}{Enter}{/Shift}line2");
    expect(screen.getByTestId("chat-input")).toHaveValue("line1\nline2");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("restores the draft and shows the error when sending fails", async () => {
    setup(
      {},
      {
        [`POST /projects/${PROJECT_ID}/messages`]: () => ({
          status: 409,
          body: { error: { code: "wrong_phase", params: {} } },
        }),
      },
    );
    await renderProject();
    await userEvent.type(screen.getByTestId("chat-input"), "Hello{Enter}");
    expect(await screen.findByTestId("chat-error")).toHaveTextContent(
      "This action is not available at the current stage of the project.",
    );
    expect(screen.getByTestId("chat-input")).toHaveValue("Hello");
    expect(screen.queryByTestId("chat-message-user")).not.toBeInTheDocument();
  });

  it.each<Phase>(["spec_review", "plan_review", "ready"])(
    "disables the input in phase %s",
    async (phase) => {
      setup({
        project: { ...baseProject(), phase },
        messages: [msg("m1", "user", "hi")],
      });
      await renderProject();
      expect(screen.getByTestId("chat-input")).toBeDisabled();
      expect(screen.getByTestId("chat-send")).toBeDisabled();
      expect(screen.getByTestId("chat-closed")).toBeVisible();
    },
  );

  it("disables the input when the project is paused", async () => {
    setup({ project: { ...baseProject(), status: "paused" } });
    await renderProject();
    expect(screen.getByTestId("chat-input")).toBeDisabled();
    expect(screen.getByTestId("chat-paused")).toHaveTextContent("paused");
  });

  it("highlights the current phase in the stepper and follows phase.changed", async () => {
    setup({ messages: [msg("m1", "user", "hi")] });
    await renderProject();
    const state = (p: string) => screen.getByTestId(`phase-step-${p}`).getAttribute("data-state");
    expect(state("interview")).toBe("current");
    expect(state("ready")).toBe("upcoming");
    FakeEventSource.last.emit("phase.changed", { phase: "plan_review" });
    await waitFor(() => expect(state("plan_review")).toBe("current"));
    expect(state("interview")).toBe("done");
    expect(state("spec_review")).toBe("done");
    expect(screen.getByTestId("chat-input")).toBeDisabled();
  });

  it("shows a translated banner on job.failed and clears it when the job restarts", async () => {
    setup({ messages: [msg("m1", "user", "hi")] });
    await renderProject();
    FakeEventSource.last.emit("job.started", { kind: "reply" });
    expect(await screen.findByTestId("chat-typing")).toBeVisible();
    FakeEventSource.last.emit("job.failed", { kind: "reply", code: "llm_error" });
    const banner = await screen.findByTestId("job-failed");
    expect(banner).toHaveAttribute("data-code", "llm_error");
    expect(banner).toHaveTextContent("The language model failed to answer.");
    expect(screen.queryByTestId("chat-typing")).not.toBeInTheDocument();

    FakeEventSource.last.emit("job.started", { kind: "reply" });
    await waitFor(() => expect(screen.queryByTestId("job-failed")).not.toBeInTheDocument());
  });

  it("explains a reached budget in French", async () => {
    setup({ messages: [msg("m1", "user", "hi")] });
    await renderProject();
    await setLang("fr");
    FakeEventSource.last.emit("job.failed", { kind: "spec", code: "budget_reached" });
    expect(await screen.findByTestId("job-failed")).toHaveTextContent(
      "Le budget du projet est atteint",
    );
  });
});

function baseProject(): Project {
  return {
    id: PROJECT_ID,
    name: "Todo",
    folder_id: null,
    created_at: "2026-01-01T00:00:00Z",
    status: "active",
    phase: "interview",
  };
}

describe("SSE connection", () => {
  it("opens one stream per project and closes it on unmount", async () => {
    setup();
    const { unmount } = await renderProject();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.last.url).toBe(`/api/v1/projects/${PROJECT_ID}/stream`);
    unmount();
    expect(FakeEventSource.last.closed).toBe(true);
  });

  it("refetches messages, spec, plan and project after a reconnect, not on the first open", async () => {
    const { world, calls } = setup({ messages: [msg("m1", "user", "hi")] });
    await renderProject();
    const es = FakeEventSource.last;
    es.open();
    const count = (suffix: string) =>
      calls.filter((c) => c.method === "GET" && c.path.endsWith(suffix)).length;
    const before = {
      m: count("/messages"),
      s: count("/spec"),
      p: count("/plan"),
      pr: count("/projects"),
    };
    expect(before.m).toBe(1);

    // Connection drops; while away the assistant answered and the phase moved on.
    es.drop();
    world.messages.push(msg("m2", "assistant", "Missed while offline"));
    world.spec = SPEC;
    world.project = { ...world.project, phase: "spec_review" };
    es.open();

    expect(await screen.findByText("Missed while offline")).toBeVisible();
    expect(await screen.findByTestId("spec-panel")).toBeVisible();
    await waitFor(() =>
      expect(screen.getByTestId("phase-step-spec_review")).toHaveAttribute("data-state", "current"),
    );
    expect(count("/messages")).toBe(before.m + 1);
    expect(count("/spec")).toBe(before.s + 1);
    expect(count("/plan")).toBe(before.p + 1);
    expect(count("/projects")).toBe(before.pr + 1);
  });

  it("drops in-flight jobs on reconnect so no spinner stays stuck", async () => {
    setup({ messages: [msg("m1", "user", "hi")] });
    await renderProject();
    const es = FakeEventSource.last;
    es.open();
    es.emit("job.started", { kind: "reply" });
    expect(await screen.findByTestId("chat-typing")).toBeVisible();
    es.drop();
    es.open();
    await waitFor(() => expect(screen.queryByTestId("chat-typing")).not.toBeInTheDocument());
  });
});

describe("Spec flow", () => {
  it("generates the spec, renders it, then supports feedback, approval and plan generation", async () => {
    const { world, calls } = setup(
      { messages: [msg("m1", "user", "A to-do app"), msg("m2", "assistant", "Anything else?")] },
      {
        [`POST /projects/${PROJECT_ID}/spec/generate`]: () => ({ status: 202, body: {} }),
        [`POST /projects/${PROJECT_ID}/spec/approve`]: () => {
          world.spec = { ...world.spec!, status: "approved" };
          return { body: world.spec };
        },
        [`POST /projects/${PROJECT_ID}/plan/generate`]: () => ({ status: 202, body: {} }),
      },
    );
    await renderProject();

    // Button visible once a user message exists; loading state while the job runs
    await userEvent.click(await screen.findByTestId("spec-generate"));
    expect(calls.find((c) => c.path.endsWith("/spec/generate"))?.body).toEqual({});
    expect(screen.getByTestId("spec-generate")).toBeDisabled();
    expect(screen.getByTestId("spec-generate")).toHaveTextContent("Generating the spec");

    // Worker publishes the result
    world.spec = SPEC;
    world.project = { ...world.project, phase: "spec_review" };
    FakeEventSource.last.emit("spec.updated", { version: 1 });
    FakeEventSource.last.emit("phase.changed", { phase: "spec_review" });
    const panel = await screen.findByTestId("spec-panel");
    expect(within(panel).getByRole("heading", { name: "Todo spec" })).toBeVisible();
    expect(within(panel).getByText("simple").tagName).toBe("STRONG");
    expect(screen.getByTestId("spec-version")).toHaveTextContent("Version 1");
    expect(screen.queryByTestId("spec-generate")).not.toBeInTheDocument();
    // links are safe
    const link = within(panel).getByRole("link", { name: "docs" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");

    // Request changes -> feedback textarea -> POST {feedback}
    await userEvent.click(screen.getByTestId("spec-request-changes"));
    expect(screen.getByTestId("spec-feedback-submit")).toBeDisabled();
    await userEvent.type(screen.getByTestId("spec-feedback"), "Add due dates");
    await userEvent.click(screen.getByTestId("spec-feedback-submit"));
    await waitFor(() =>
      expect(calls.filter((c) => c.path.endsWith("/spec/generate"))).toHaveLength(2),
    );
    expect(calls.filter((c) => c.path.endsWith("/spec/generate"))[1].body).toEqual({
      feedback: "Add due dates",
    });
    expect(await screen.findByTestId("spec-regenerating")).toBeVisible();
    world.spec = { ...SPEC, version: 2, content: "# Todo spec v2" };
    FakeEventSource.last.emit("spec.updated", { version: 2 });
    await waitFor(() => expect(screen.getByTestId("spec-version")).toHaveTextContent("Version 2"));
    expect(screen.queryByTestId("spec-regenerating")).not.toBeInTheDocument();

    // Approve -> "Generate plan"
    await userEvent.click(screen.getByTestId("spec-approve"));
    expect(await screen.findByTestId("spec-approved-note")).toBeVisible();
    expect(screen.getByTestId("spec-status")).toHaveTextContent("Approved");
    expect(screen.queryByTestId("spec-approve")).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId("plan-generate"));
    expect(screen.getByTestId("plan-generate")).toBeDisabled();
    expect(screen.getByTestId("plan-generate")).toHaveTextContent("Generating the plan");
    expect(calls.some((c) => c.path.endsWith("/plan/generate"))).toBe(true);
  });

  it("hides the spec button before the first user message", async () => {
    setup();
    await renderProject();
    expect(screen.queryByTestId("spec-generate")).not.toBeInTheDocument();
  });
});

describe("Plan tab", () => {
  async function openPlanTab() {
    await userEvent.click(screen.getByTestId("tab-plan"));
    return screen.findByTestId("plan-tab");
  }

  it("shows an empty state that depends on the phase", async () => {
    setup();
    await renderProject();
    await openPlanTab();
    expect(screen.getByTestId("plan-empty")).toHaveTextContent("No plan yet");
    expect(screen.queryByTestId("plan-generate")).not.toBeInTheDocument();
  });

  it("offers to generate the plan once the spec is approved", async () => {
    setup(
      {
        project: { ...baseProject(), phase: "spec_review" },
        spec: { ...SPEC, status: "approved" },
      },
      {
        [`POST /projects/${PROJECT_ID}/plan/generate`]: () => ({ status: 202, body: {} }),
      },
    );
    await renderProject();
    await openPlanTab();
    await userEvent.click(screen.getByTestId("plan-generate"));
    expect(await screen.findByTestId("plan-generating")).toBeVisible();
    FakeEventSource.last.emit("job.failed", { kind: "plan", code: "plan_invalid" });
    expect(await screen.findByTestId("job-failed")).toHaveTextContent("valid plan");
    expect(screen.getByTestId("plan-generate")).toBeEnabled();
  });

  it("renders milestones, task cards and the estimate formatted per language", async () => {
    setup({ project: { ...baseProject(), phase: "plan_review" }, plan: PLAN });
    await renderProject();
    await openPlanTab();

    expect(screen.getByTestId("plan-version")).toHaveTextContent("Version 1");
    const total = screen.getByTestId("estimate-total-cost");
    expect(total).toHaveTextContent("$1,234.50");
    expect(screen.getByTestId("estimate-total-tokens")).toHaveTextContent("150,000 tokens");

    const m1 = screen.getByTestId("milestone-M1");
    expect(within(m1).getByRole("heading", { name: /Backend API/ })).toBeVisible();
    expect(within(m1).getByTestId("milestone-estimate")).toHaveTextContent(
      "1 task · 30,000 tokens · $0.06",
    );
    const t1 = within(m1).getByTestId("task-card-T-001");
    expect(within(t1).getByText("Create the todo endpoints")).toBeVisible();
    expect(within(t1).getByTestId("task-size")).toHaveTextContent("S");
    expect(within(t1).getByTestId("task-role")).toHaveTextContent("Backend");
    expect(within(t1).getByTestId("task-files")).toHaveTextContent("app/api/todos.py");
    expect(within(t1).getByTestId("task-tests")).toHaveTextContent("tests/test_todos.py");
    expect(within(t1).getByText("POST /api/todos returns 201")).toBeVisible();

    const t2 = within(screen.getByTestId("milestone-M2")).getByTestId("task-card-T-002");
    expect(within(t2).getByTestId("task-size")).toHaveTextContent("M");
    expect(within(t2).getByTestId("task-depends")).toHaveTextContent("T-001");
    expect(within(t2).getAllByRole("listitem").length).toBeGreaterThan(3);

    await setLang("fr");
    await waitFor(() =>
      expect(screen.getByTestId("estimate-total-tokens")).toHaveTextContent(/150\s000 jetons/),
    );
    // fr-FR currency: 1 234,50 $US (space separators are non-breaking)
    expect(screen.getByTestId("estimate-total-cost").textContent?.replace(/\s/g, " ")).toMatch(
      /^1 234,50 \$/,
    );
    expect(within(m1).getByTestId("milestone-estimate").textContent ?? "").toContain("tâche");
  });

  it("asks for confirmation with the estimated cost before approving, then shows the ready state", async () => {
    const { world, calls } = setup(
      {
        project: { ...baseProject(), phase: "plan_review" },
        plan: PLAN,
        spec: { ...SPEC, status: "approved" },
      },
      {
        [`POST /projects/${PROJECT_ID}/plan/approve`]: () => {
          world.plan = { ...PLAN, status: "approved" };
          return { body: world.plan };
        },
      },
    );
    await renderProject();
    await openPlanTab();

    await userEvent.click(screen.getByTestId("plan-approve"));
    const dialog = await screen.findByTestId("confirm-dialog");
    expect(dialog).toHaveTextContent("$1,234.50");
    expect(dialog).toHaveTextContent("150,000 tokens");
    expect(calls.some((c) => c.path.endsWith("/plan/approve"))).toBe(false);

    await userEvent.click(within(dialog).getByTestId("confirm-submit"));
    expect(await screen.findByTestId("plan-approved")).toHaveTextContent(
      "Review the plan one last time, then start building.",
    );
    expect(screen.queryByTestId("plan-approve")).not.toBeInTheDocument();
    expect(screen.getByTestId("plan-status")).toHaveTextContent("Approved");
    // phase moved to ready in the stepper (Chat tab)
    await userEvent.click(screen.getByTestId("tab-chat"));
    expect(await screen.findByTestId("phase-step-ready")).toHaveAttribute("data-state", "current");
  });

  it("cancelling the confirmation does not approve", async () => {
    const { calls } = setup({ project: { ...baseProject(), phase: "plan_review" }, plan: PLAN });
    await renderProject();
    await openPlanTab();
    await userEvent.click(screen.getByTestId("plan-approve"));
    const dialog = await screen.findByTestId("confirm-dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByTestId("confirm-dialog")).not.toBeInTheDocument());
    expect(calls.some((c) => c.path.endsWith("/plan/approve"))).toBe(false);
  });

  it("sends feedback to plan/generate and refreshes on plan.updated", async () => {
    const { world, calls } = setup(
      { project: { ...baseProject(), phase: "plan_review" }, plan: PLAN },
      { [`POST /projects/${PROJECT_ID}/plan/generate`]: () => ({ status: 202, body: {} }) },
    );
    await renderProject();
    await openPlanTab();
    await userEvent.click(screen.getByTestId("plan-request-changes"));
    await userEvent.type(screen.getByTestId("plan-feedback"), "Split the UI task");
    await userEvent.click(screen.getByTestId("plan-feedback-submit"));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/plan/generate"))?.body).toEqual({
        feedback: "Split the UI task",
      }),
    );
    expect(await screen.findByTestId("plan-generating")).toBeVisible();
    expect(screen.getByTestId("plan-approve")).toBeDisabled();
    world.plan = { ...PLAN, version: 2 };
    FakeEventSource.last.emit("plan.updated", { version: 2 });
    await waitFor(() => expect(screen.getByTestId("plan-version")).toHaveTextContent("Version 2"));
    expect(screen.queryByTestId("plan-generating")).not.toBeInTheDocument();
  });
});
