import { vi } from "vitest";
import type { Project, ProjectCosts } from "../api/types";
import { renderApp } from "../test/utils";
import * as workspace from "../workspace/WorkspaceProvider";
import { CostsTab } from "./CostsTab";
import * as provider from "./ProjectDataProvider";

const BASE_PROJECT: Project = {
  id: "p1",
  name: "Todo",
  folder_id: null,
  created_at: "2026-01-01T00:00:00Z",
  status: "active",
  phase: "building",
};

/** Render the Costs tab with the given report, without a server (the data hooks are stubbed). */
export async function showCosts(
  costs: ProjectCosts,
  options: { project?: Partial<Project>; updateProject?: (...args: never[]) => Promise<void> } = {},
) {
  const updateProject = vi.fn(options.updateProject ?? (async () => undefined));
  vi.spyOn(provider, "useProjectData").mockReturnValue({
    project: { ...BASE_PROJECT, ...options.project },
    costs,
    buildError: null,
    paused: false,
  } as unknown as ReturnType<typeof provider.useProjectData>);
  vi.spyOn(workspace, "useWorkspace").mockReturnValue({
    updateProject,
  } as unknown as ReturnType<typeof workspace.useWorkspace>);
  await renderApp(<CostsTab />);
  return { updateProject };
}
