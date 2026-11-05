import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MockupVariant, Project } from "../api/types";
import { setLang } from "../i18n";
import { renderApp } from "../test/utils";
import * as workspace from "../workspace/WorkspaceProvider";
import { MockupsPanel } from "./MockupsPanel";
import * as provider from "./ProjectDataProvider";

afterEach(() => vi.restoreAllMocks());

const PROJECT: Project = {
  id: "p1",
  name: "Todo",
  folder_id: null,
  created_at: "2026-01-01T00:00:00Z",
  status: "active",
  phase: "spec_review",
};

const VARIANTS: MockupVariant[] = [
  {
    id: "v1",
    position: 1,
    title: "Simple list",
    summary: "One column.",
    wireframe: "+------+\n| <script>alert(1)</script> |\n+------+",
    chosen: false,
  },
  { id: "v2", position: 2, title: "Board", summary: "Columns.", wireframe: "+--+", chosen: false },
];

async function show(
  options: { project?: Partial<Project>; mockups?: MockupVariant[]; running?: boolean } = {},
) {
  const updateProject = vi.fn(async () => undefined);
  const generateMockups = vi.fn(async () => undefined);
  const chooseMockup = vi.fn(async () => undefined);
  vi.spyOn(provider, "useProjectData").mockReturnValue({
    project: { ...PROJECT, ...options.project },
    paused: false,
    failure: null,
    clearFailure: vi.fn(),
    jobs: { reply: false, spec: false, plan: false, start: false, mockups: !!options.running },
    mockups: options.mockups ?? [],
    generateMockups,
    chooseMockup,
  } as unknown as ReturnType<typeof provider.useProjectData>);
  vi.spyOn(workspace, "useWorkspace").mockReturnValue({
    updateProject,
  } as unknown as ReturnType<typeof workspace.useWorkspace>);
  await renderApp(<MockupsPanel />);
  return { updateProject, generateMockups, chooseMockup };
}

describe("the mockup variants panel", () => {
  it("is off by default, shows no action, and turns on through the workspace", async () => {
    const { updateProject } = await show();
    expect(await screen.findByTestId("mockups-panel")).toHaveAttribute("data-state", "off");
    expect(screen.queryByTestId("mockups-generate")).toBeNull();
    await userEvent.setup().click(screen.getByTestId("mockups-toggle"));
    await waitFor(() =>
      expect(updateProject).toHaveBeenCalledWith("p1", { mockups_enabled: true }),
    );
  });

  it("asks the planner for mockups when turned on", async () => {
    const { generateMockups } = await show({ project: { mockups_enabled: true } });
    await userEvent.setup().click(await screen.findByTestId("mockups-generate"));
    await waitFor(() => expect(generateMockups).toHaveBeenCalled());
    expect(screen.queryByTestId("mockups-list")).toBeNull();
  });

  it("shows the variants side by side and renders a wireframe as inert text", async () => {
    const { container } = await (async () => {
      await show({ project: { mockups_enabled: true }, mockups: VARIANTS });
      return { container: document.body };
    })();
    expect(await screen.findByTestId("mockup-1")).toHaveTextContent("Simple list");
    expect(screen.getByTestId("mockup-2")).toHaveTextContent("Board");
    expect(screen.getByTestId("mockup-wireframe-1").textContent).toContain(
      "<script>alert(1)</script>",
    );
    expect(container.querySelector("script[src], pre script")).toBeNull();
    expect(screen.getByTestId("mockups-pick-hint")).toBeInTheDocument();
  });

  it("lets the user choose one and marks the chosen one", async () => {
    const { chooseMockup } = await show({ project: { mockups_enabled: true }, mockups: VARIANTS });
    await userEvent.setup().click(await screen.findByTestId("mockup-choose-2"));
    await waitFor(() => expect(chooseMockup).toHaveBeenCalledWith("v2"));
  });

  it("shows the chosen variant as chosen and not choosable again", async () => {
    await show({
      project: { mockups_enabled: true },
      mockups: [VARIANTS[0], { ...VARIANTS[1], chosen: true }],
    });
    expect(await screen.findByTestId("mockup-2")).toHaveAttribute("data-chosen", "true");
    expect(screen.getByTestId("mockup-choose-2")).toBeDisabled();
    expect(screen.queryByTestId("mockups-pick-hint")).toBeNull();
  });

  it("disables the action while the job runs", async () => {
    await show({ project: { mockups_enabled: true }, running: true });
    expect(await screen.findByTestId("mockups-generate")).toBeDisabled();
  });

  it("is translated to French", async () => {
    await show({ project: { mockups_enabled: true } });
    await setLang("fr");
    expect(await screen.findByText("Variantes de maquette")).toBeInTheDocument();
    await setLang("en");
  });
});
