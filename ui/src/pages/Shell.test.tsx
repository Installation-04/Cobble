import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Folder, Project } from "../api/types";
import { ME, mockFetch, renderApp } from "../test/utils";
import { HomePage } from "./HomePage";
import { ProjectPage } from "./ProjectPage";
import { Shell } from "./Shell";

afterEach(() => vi.unstubAllGlobals());

function statefulBackend() {
  const folders: Folder[] = [];
  const projects: Project[] = [];
  const { calls } = mockFetch({
    "GET /auth/me": () => ({ body: ME }),
    "PATCH /auth/me": ({ body }) => ({ body: { ...ME, ...(body as object) } }),
    "GET /folders": () => ({ body: folders }),
    "GET /projects": () => ({ body: projects }),
    "POST /folders": ({ body }) => {
      const f = {
        id: `f${folders.length + 1}`,
        name: (body as { name: string }).name,
        position: 0,
      };
      folders.push(f);
      return { status: 201, body: f };
    },
    "POST /projects": ({ body }) => {
      const b = body as { name: string; folder_id?: string };
      const p: Project = {
        id: `p${projects.length + 1}`,
        name: b.name,
        folder_id: b.folder_id ?? null,
        created_at: "2026-01-01T00:00:00Z",
        status: "active",
        phase: "interview",
      };
      projects.push(p);
      return { status: 201, body: p };
    },
  });
  return calls;
}

const ui = (
  <Routes>
    <Route element={<Shell />}>
      <Route index element={<HomePage />} />
      <Route path="projects/:id" element={<ProjectPage />} />
    </Route>
  </Routes>
);

describe("Shell dialogs", () => {
  it("creates a folder, then a project inside it, both showing in the sidebar", async () => {
    const calls = statefulBackend();
    await renderApp(ui);
    await screen.findByTestId("sidebar-empty");

    await userEvent.click(screen.getByTestId("new-folder-button"));
    await userEvent.type(await screen.findByTestId("folder-name-input"), "Clients");
    await userEvent.click(screen.getByTestId("folder-submit"));
    const folder = await screen.findByTestId("folder-item");
    expect(within(folder).getByTestId("folder-name")).toHaveTextContent("Clients");
    await waitFor(() => expect(screen.queryByTestId("folder-dialog")).toBeNull());

    await userEvent.click(screen.getByTestId("new-project-button"));
    await userEvent.type(await screen.findByTestId("project-name-input"), "Invoicing");
    const select = screen.getByTestId("project-folder-select");
    // "none" is the first option
    expect(
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["No folder", "Clients"]);
    await userEvent.selectOptions(select, "Clients");
    await userEvent.click(screen.getByTestId("project-submit"));

    await waitFor(() =>
      expect(
        within(screen.getByTestId("folder-item")).getByTestId("project-item"),
      ).toHaveTextContent("Invoicing"),
    );
    const created = calls.find((c) => c.method === "POST" && c.path === "/projects")!;
    expect(created.body).toEqual({ name: "Invoicing", folder_id: "f1" });
    expect(created.headers.get("X-Requested-With")).toBe("cobble");
    // navigated to the new project, which shows the tab placeholders
    expect(await screen.findByTestId("project-page")).toBeInTheDocument();
    expect(screen.getByTestId("tab-plan")).toBeInTheDocument();
  });

  it("creates an unfiled project when 'No folder' is kept", async () => {
    const calls = statefulBackend();
    await renderApp(ui);
    await userEvent.click(await screen.findByTestId("new-project-button"));
    await userEvent.type(await screen.findByTestId("project-name-input"), "Solo");
    await userEvent.click(screen.getByTestId("project-submit"));
    await within(await screen.findByTestId("unfiled-projects")).findByText("Solo");
    expect(calls.find((c) => c.path === "/projects" && c.method === "POST")!.body).toEqual({
      name: "Solo",
    });
  });

  it("shows a translated error when the server rejects the folder", async () => {
    mockFetch({
      "GET /auth/me": () => ({ body: ME }),
      "GET /folders": () => ({ body: [] }),
      "GET /projects": () => ({ body: [] }),
      "POST /folders": () => ({
        status: 422,
        body: { error: { code: "validation_error", params: { fields: ["name"] } } },
      }),
    });
    await renderApp(ui);
    await userEvent.click(await screen.findByTestId("new-folder-button"));
    await userEvent.type(await screen.findByTestId("folder-name-input"), "x");
    await userEvent.click(screen.getByTestId("folder-submit"));
    expect(await screen.findByTestId("dialog-error")).toHaveTextContent("name");
  });

  it("toggles language and theme instantly and saves them on the account", async () => {
    const calls = statefulBackend();
    await renderApp(ui);
    await userEvent.click(await screen.findByTestId("lang-toggle"));
    expect(await screen.findByText("Nouveau projet")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("fr");
    await userEvent.click(screen.getByTestId("theme-toggle"));
    expect(document.documentElement).toHaveClass("dark");
    await waitFor(() => {
      const patches = calls.filter((c) => c.method === "PATCH" && c.path === "/auth/me");
      expect(patches.map((c) => c.body)).toEqual([{ lang: "fr" }, { theme: "dark" }]);
    });
  });

  it("changes preferences from the settings dialog tabs", async () => {
    statefulBackend();
    await renderApp(ui);
    await userEvent.click(await screen.findByTestId("settings-button"));
    await userEvent.selectOptions(await screen.findByTestId("settings-lang-select"), "fr");
    expect(await screen.findByText("Réglages")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("settings-tab-appearance"));
    await userEvent.selectOptions(screen.getByTestId("settings-theme-select"), "dark");
    expect(document.documentElement).toHaveClass("dark");
    await userEvent.click(screen.getByTestId("settings-tab-about"));
    expect(screen.getByTestId("about-version")).toHaveTextContent(/^\d+\.\d+\.\d+/);
  });
});
