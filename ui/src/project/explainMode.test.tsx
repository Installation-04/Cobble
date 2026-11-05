import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Milestone, Project } from "../api/types";
import { setLang } from "../i18n";
import { ME, mockFetch, renderApp } from "../test/utils";
import * as workspace from "../workspace/WorkspaceProvider";
import { DemoTab } from "./DemoTab";
import * as provider from "./ProjectDataProvider";

afterEach(() => vi.restoreAllMocks());

const PROJECT: Project = {
  id: "p1",
  name: "Todo",
  folder_id: null,
  created_at: "2026-01-01T00:00:00Z",
  status: "active",
  phase: "building",
};

const built = (ref: string, over: Partial<Milestone> = {}): Milestone => ({
  ref,
  title: `Milestone ${ref}`,
  status: "built",
  tag: `milestone-${ref}`,
  preview_path: null,
  built_at: "2026-01-02T10:00:00Z",
  validated_at: null,
  explanation: null,
  ...over,
});

async function showDemo(milestones: Milestone[], project: Partial<Project> = {}) {
  const updateProject = vi.fn(async () => undefined);
  vi.spyOn(provider, "useProjectData").mockReturnValue({
    project: { ...PROJECT, ...project },
    milestones,
    buildError: null,
    phase: "building",
    failure: null,
    clearFailure: () => undefined,
    reloadTasks: async () => undefined,
    reloadMilestones: async () => undefined,
    upsertTask: () => undefined,
  } as unknown as ReturnType<typeof provider.useProjectData>);
  vi.spyOn(workspace, "useWorkspace").mockReturnValue({
    updateProject,
  } as unknown as ReturnType<typeof workspace.useWorkspace>);
  await renderApp(<DemoTab />);
  return { updateProject };
}

describe("the Explique-moi switch", () => {
  it("is off by default and says why", async () => {
    await showDemo([built("M1")]);
    const card = await screen.findByTestId("explain-mode");
    expect(card).toHaveAttribute("data-state", "off");
    expect(screen.getByTestId<HTMLInputElement>("explain-mode-toggle").checked).toBe(false);
    expect(card).toHaveTextContent(/costs a few tokens/);
    expect(screen.queryByTestId("milestone-explanation-M1")).not.toBeInTheDocument();
  });

  it("switches the project through the workspace, on and off", async () => {
    const { updateProject } = await showDemo([built("M1")]);
    await userEvent.setup().click(await screen.findByTestId("explain-mode-toggle"));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("p1", { explain_mode: true }));
  });

  it("turns off a project that has it on", async () => {
    const { updateProject } = await showDemo([built("M1")], { explain_mode: true });
    expect(await screen.findByTestId("explain-mode")).toHaveAttribute("data-state", "on");
    await userEvent.setup().click(screen.getByTestId("explain-mode-toggle"));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("p1", { explain_mode: false }));
  });
});

describe("the explanation of a milestone", () => {
  it("shows the summary on the built milestone", async () => {
    await showDemo([built("M1", { explanation: "You can now add tasks.\nWhy: lists first." })], {
      explain_mode: true,
    });
    const box = await screen.findByTestId("milestone-explanation-M1");
    expect(box).toHaveTextContent("You can now add tasks.");
    expect(within(box).getByText("Write it again")).toBeInTheDocument();
  });

  it("keeps a summary visible after the mode is switched off, without the button", async () => {
    await showDemo([built("M1", { explanation: "Kept." })]);
    const box = await screen.findByTestId("milestone-explanation-M1");
    expect(box).toHaveTextContent("Kept.");
    expect(screen.queryByTestId("milestone-explain-M1")).not.toBeInTheDocument();
  });

  it("says it is being written and can ask for it", async () => {
    const { calls } = mockFetch({
      "POST /projects/p1/milestones/M1/explain": () => ({ status: 202, body: {} }),
    });
    await showDemo([built("M1")], { explain_mode: true });
    expect(await screen.findByText(/being written/)).toBeInTheDocument();
    await userEvent.setup().click(screen.getByTestId("milestone-explain-M1"));
    expect(await screen.findByText(/Explanation requested/)).toBeInTheDocument();
    expect(calls.map((c) => `${c.method} ${c.path}`)).toContain(
      "POST /projects/p1/milestones/M1/explain",
    );
  });

  it("explains a refusal in words", async () => {
    mockFetch({
      "POST /projects/p1/milestones/M1/explain": () => ({
        status: 409,
        body: { error: { code: "explain_mode_off", params: {} } },
      }),
    });
    await showDemo([built("M1")], { explain_mode: true });
    await userEvent.setup().click(await screen.findByTestId("milestone-explain-M1"));
    expect(await screen.findByTestId("explain-error")).toHaveTextContent(/Explain mode is off/);
  });

  it("does not show a box on a milestone that is still pending", async () => {
    await showDemo([built("M1", { status: "pending", built_at: null })], { explain_mode: true });
    await screen.findByTestId("explain-mode");
    expect(screen.queryByTestId("milestone-explanation-M1")).not.toBeInTheDocument();
  });

  it("speaks French", async () => {
    mockFetch({ "GET /auth/me": () => ({ body: { ...ME, lang: "fr" } }) });
    await showDemo([built("M1", { explanation: "Vous pouvez ajouter des tâches." })], {
      explain_mode: true,
    });
    await setLang("fr");
    expect(
      await screen.findByText(/Expliqué en mots simples/, { selector: "p" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/La réécrire/)).toBeInTheDocument();
  });
});
