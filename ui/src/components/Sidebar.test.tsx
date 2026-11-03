import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLang } from "../i18n";
import { mockFetch } from "../test/utils";
import { WorkspaceProvider } from "../workspace/WorkspaceProvider";
import { Sidebar, type SidebarActions } from "./Sidebar";

const FOLDERS = [
  { id: "f2", name: "Perso", position: 1 },
  { id: "f1", name: "Clients", position: 0 },
];
const PROJECTS = [
  {
    id: "p1",
    name: "Invoicing",
    folder_id: "f1",
    created_at: "2026-01-01T00:00:00Z",
    status: "active",
    phase: "interview",
  },
  {
    id: "p2",
    name: "Inventory",
    folder_id: "f1",
    created_at: "2026-01-02T00:00:00Z",
    status: "active",
    phase: "interview",
  },
  {
    id: "p3",
    name: "Recipes",
    folder_id: "f2",
    created_at: "2026-01-03T00:00:00Z",
    status: "active",
    phase: "interview",
  },
  {
    id: "p4",
    name: "Scratchpad",
    folder_id: null,
    created_at: "2026-01-04T00:00:00Z",
    status: "active",
    phase: "interview",
  },
];

function actions(): SidebarActions {
  return {
    newProject: vi.fn(),
    newFolder: vi.fn(),
    renameFolder: vi.fn(),
    deleteFolder: vi.fn(),
    editProject: vi.fn(),
    deleteProject: vi.fn(),
  };
}

async function renderSidebar(
  a = actions(),
  data = { folders: FOLDERS, projects: PROJECTS },
  showStore = false,
) {
  mockFetch({
    "GET /folders": () => ({ body: data.folders }),
    "GET /projects": () => ({ body: data.projects }),
  });
  render(
    <MemoryRouter>
      <WorkspaceProvider>
        <Sidebar actions={a} showStore={showStore} />
      </WorkspaceProvider>
    </MemoryRouter>,
  );
  await screen.findAllByTestId("project-item");
  return a;
}

beforeEach(() => setLang("en"));
afterEach(() => vi.unstubAllGlobals());

describe("Sidebar", () => {
  it("links to the Store for administrators only", async () => {
    await renderSidebar();
    expect(screen.queryByTestId("nav-store")).not.toBeInTheDocument();
    cleanup();
    await renderSidebar(actions(), { folders: FOLDERS, projects: PROJECTS }, true);
    expect(screen.getByTestId("nav-store")).toHaveAttribute("href", "/store");
  });

  it("lists folders by position with their projects nested, and unfiled projects apart", async () => {
    await renderSidebar();
    const folders = screen.getAllByTestId("folder-item");
    expect(folders.map((f) => within(f).getByTestId("folder-name").textContent)).toEqual([
      "Clients",
      "Perso",
    ]);
    expect(
      within(folders[0])
        .getAllByTestId("project-item")
        .map((p) => p.textContent),
    ).toEqual(["Invoicing", "Inventory"]);
    expect(within(folders[1]).getByText("Recipes")).toBeInTheDocument();
    const unfiled = screen.getByTestId("unfiled-projects");
    expect(within(unfiled).getByText("Scratchpad")).toBeInTheDocument();
  });

  it("filters projects client-side and hides folders without a match", async () => {
    await renderSidebar();
    await userEvent.type(screen.getByTestId("sidebar-search"), "inv");
    expect(screen.getAllByTestId("project-item").map((p) => p.textContent)).toEqual([
      "Invoicing",
      "Inventory",
    ]);
    expect(screen.getAllByTestId("folder-item")).toHaveLength(1);
    expect(screen.queryByText("Recipes")).toBeNull();

    await userEvent.clear(screen.getByTestId("sidebar-search"));
    await userEvent.type(screen.getByTestId("sidebar-search"), "zzz");
    expect(screen.getByTestId("sidebar-no-results")).toBeInTheDocument();
  });

  it("collapses and expands a folder", async () => {
    await renderSidebar();
    const clients = screen.getAllByTestId("folder-item")[0];
    await userEvent.click(within(clients).getByTestId("folder-toggle"));
    expect(within(clients).queryByText("Invoicing")).toBeNull();
    await userEvent.click(within(clients).getByTestId("folder-toggle"));
    expect(within(clients).getByText("Invoicing")).toBeInTheDocument();
  });

  it("wires the buttons, row menus and global views", async () => {
    const a = await renderSidebar();
    await userEvent.click(screen.getByTestId("new-project-button"));
    expect(a.newProject).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByTestId("new-folder-button"));
    expect(a.newFolder).toHaveBeenCalledOnce();

    const first = screen.getAllByTestId("project-item")[0];
    await userEvent.click(within(first).getByTestId("project-menu"));
    await userEvent.click(await screen.findByTestId("menu-delete"));
    expect(a.deleteProject).toHaveBeenCalledWith(expect.objectContaining({ id: "p1" }));

    expect(screen.getByTestId("nav-agents")).toHaveAttribute("href", "/agents");
    expect(screen.getByTestId("nav-demos")).toHaveAttribute("href", "/demos");
    expect(screen.getByTestId("nav-costs")).toHaveAttribute("href", "/costs");
  });

  it("shows an empty state when there is nothing yet", async () => {
    mockFetch({ "GET /folders": () => ({ body: [] }), "GET /projects": () => ({ body: [] }) });
    render(
      <MemoryRouter>
        <WorkspaceProvider>
          <Sidebar actions={actions()} />
        </WorkspaceProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByTestId("sidebar-empty")).toBeInTheDocument();
  });
});
