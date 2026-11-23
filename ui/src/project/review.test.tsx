import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Project, Task, TaskDetail, TaskState } from "../api/types";
import { setLang } from "../i18n";
import { mockFetch, renderApp } from "../test/utils";
import * as workspace from "../workspace/WorkspaceProvider";
import * as provider from "./ProjectDataProvider";
import { ReviewToggle } from "./ReviewToggle";
import { canDo, groupOf, stateTone } from "./taskState";
import { TaskDrawer } from "./TaskDrawer";

afterEach(() => vi.restoreAllMocks());

const PROJECT: Project = {
  id: "p1",
  name: "Todo",
  folder_id: null,
  created_at: "2026-01-01T00:00:00Z",
  status: "active",
  phase: "building",
};

const task = (state: TaskState): Task => ({
  ref: "T-001",
  title: "Add login",
  milestone: "M1",
  state,
  attempts: 2,
  escalated: false,
  role: "backend",
  size: "S",
  depends_on: [],
});

function mockProject(project: Partial<Project> = {}) {
  const updateProject = vi.fn(async () => undefined);
  vi.spyOn(provider, "useProjectData").mockReturnValue({
    project: { ...PROJECT, ...project },
    tasks: [],
    questions: [],
    openQuestions: 0,
    buildError: null,
    phase: "building",
    failure: null,
    clearFailure: () => undefined,
    reloadTasks: async () => undefined,
    upsertTask: () => undefined,
  } as unknown as ReturnType<typeof provider.useProjectData>);
  vi.spyOn(workspace, "useWorkspace").mockReturnValue({
    updateProject,
  } as unknown as ReturnType<typeof workspace.useWorkspace>);
  return { updateProject };
}

function detailRoutes(detail: Partial<TaskDetail>, state: TaskState) {
  const full: TaskDetail = { ...task(state), runs: [], ...detail };
  mockFetch({
    "GET /projects/p1/tasks/T-001": () => ({ body: full }),
    "GET /projects/p1/tasks/T-001/diff": () => ({ body: { diff: "", truncated: false } }),
    "GET /projects/p1/tasks/T-001/logs?offset=0": () => ({ body: { text: "", offset: 0 } }),
  });
}

async function openDrawer(state: TaskState, detail: Partial<TaskDetail> = {}) {
  mockProject();
  detailRoutes(detail, state);
  await renderApp(<TaskDrawer task={task(state)} onClose={() => undefined} />);
}

describe("the review switch", () => {
  it("is off by default and says it costs tokens", async () => {
    mockProject();
    await renderApp(<ReviewToggle />);
    const card = await screen.findByTestId("review-mode");
    expect(card).toHaveAttribute("data-state", "off");
    expect(card).toHaveTextContent(/costs tokens/);
    expect(screen.getByTestId<HTMLInputElement>("review-mode-toggle").checked).toBe(false);
  });

  it("switches the project through the workspace", async () => {
    const { updateProject } = mockProject();
    await renderApp(<ReviewToggle />);
    await userEvent.setup().click(await screen.findByTestId("review-mode-toggle"));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("p1", { review_enabled: true }));
  });

  it("turns off a project that has it on", async () => {
    const { updateProject } = mockProject({ review_enabled: true });
    await renderApp(<ReviewToggle />);
    expect(await screen.findByTestId("review-mode")).toHaveAttribute("data-state", "on");
    await userEvent.setup().click(screen.getByTestId("review-mode-toggle"));
    await waitFor(() =>
      expect(updateProject).toHaveBeenCalledWith("p1", { review_enabled: false }),
    );
  });

  it("is translated in French", async () => {
    mockProject();
    await renderApp(<ReviewToggle />);
    await setLang("fr");
    expect(await screen.findByText(/agent relecteur/)).toBeInTheDocument();
  });
});

describe("the review state", () => {
  it("sits in the CI column, is active and can be paused or stopped", () => {
    expect(groupOf("review")).toBe("ci");
    expect(stateTone("review")).toBe("primary");
    expect(canDo("pause", "review")).toBe(true);
    expect(canDo("stop", "review")).toBe(true);
    expect(canDo("retry", "review")).toBe(false);
  });
});

describe("the review in the task drawer", () => {
  it("says the reviewer is reading while the task is in review", async () => {
    await openDrawer("review");
    expect(await screen.findByTestId("review-in-progress")).toHaveTextContent(/reading/);
    expect(screen.getByTestId("drawer-state")).toHaveTextContent("In review");
  });

  it("lists the issues of a request for changes", async () => {
    await openDrawer("implementing", {
      review: {
        verdict: "request_changes",
        issues: ["Handle the empty title", "Add a docstring"],
        attempt: 1,
        warning: null,
      },
    });
    const verdict = await screen.findByTestId("review-verdict");
    expect(verdict).toHaveAttribute("data-verdict", "request_changes");
    const issues = within(await screen.findByTestId("review-issues"));
    expect(issues.getByText("Handle the empty title")).toBeInTheDocument();
    expect(issues.getByText("Add a docstring")).toBeInTheDocument();
  });

  it("explains an approval nobody really gave", async () => {
    await openDrawer("merged", {
      review: { verdict: "approve", issues: [], attempt: 1, warning: "review_unparsable" },
    });
    expect(await screen.findByTestId("review-warning")).toHaveTextContent(/without a review/);
  });

  it("shows nothing when the task was never reviewed", async () => {
    await openDrawer("merged", { review: null });
    await screen.findByTestId("drawer-state");
    expect(screen.queryByTestId("task-review")).not.toBeInTheDocument();
  });
});

describe("the time limit", () => {
  it("explains why a task stopped", async () => {
    await openDrawer("failed", { last_error: "task_timeout" });
    const box = await screen.findByTestId("task-failure");
    expect(box).toHaveAttribute("data-code", "task_timeout");
    expect(box).toHaveTextContent(/time limit/);
  });

  it("does not show raw error text of other failures", async () => {
    await openDrawer("failed", { last_error: "agent failed: secret log" });
    await screen.findByTestId("drawer-state");
    expect(screen.queryByTestId("task-failure")).not.toBeInTheDocument();
  });
});
