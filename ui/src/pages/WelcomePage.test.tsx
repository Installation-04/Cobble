import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeEventSource, installFakeEventSource } from "../test/fakeEventSource";
import { ME, mockFetch, renderApp, type Handler } from "../test/utils";
import { WorkspaceProvider } from "../workspace/WorkspaceProvider";
import { HomePage } from "./HomePage";
import { WelcomePage } from "./WelcomePage";

void FakeEventSource;

const PACK = {
  id: "local-cpu",
  name: { en: "Local, CPU", fr: "Local, processeur" },
  description: { en: "Runs on the processor", fr: "Tourne sur le processeur" },
  modules: ["forgejo"],
  hardware: { min_ram_mb: 0, gpu: "none" },
  priority: 1,
  fit: { ok: true, problems: [] },
  recommended: true,
  installed: false,
  installed_modules: [],
};

function world(over: { completed?: boolean; role?: string; lang?: string } = {}) {
  const state = {
    completed: over.completed ?? false,
    me: { ...ME, role: over.role ?? "admin", lang: over.lang ?? "en" },
    catalogDown: false,
  };
  const routes: Record<string, Handler> = {
    "GET /auth/me": () => ({ body: state.me }),
    "GET /setup/progress": () => ({ body: { completed: state.completed } }),
    "POST /setup/complete": () => {
      state.completed = true;
      return { body: { completed: true } };
    },
    "GET /folders": () => ({ body: [] }),
    "GET /projects": () => ({ body: [] }),
    "GET /modules": () =>
      state.catalogDown
        ? { status: 503, body: { error: { code: "module_manager_unavailable", params: {} } } }
        : { body: { modules: [], hardware: { ram_mb: 8192, gpu: "none" } } },
    "GET /modules/packs": () => ({ body: { packs: [PACK], problems: {}, recommended: PACK.id } }),
    "GET /models": () => ({ body: { models: [], default: null, configured_default: "demo" } }),
    "POST /projects": () => ({ body: { id: "p1", name: "To-do list", folder_id: null } }),
    "POST /projects/p1/messages": () => ({ body: { message: { id: "m1" } } }),
  };
  return { state, routes };
}

const app = (
  <WorkspaceProvider>
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/welcome" element={<WelcomePage />} />
      <Route path="/projects/p1" element={<p data-testid="project-page" />} />
    </Routes>
  </WorkspaceProvider>
);

beforeEach(() => installFakeEventSource());
afterEach(() => vi.unstubAllGlobals());

describe("the first-run wizard", () => {
  it("is offered once to the administrator", async () => {
    mockFetch(world().routes);
    await renderApp(app);
    expect(await screen.findByTestId("welcome")).toBeInTheDocument();
  });

  it("is not offered again once it was finished", async () => {
    mockFetch(world({ completed: true }).routes);
    await renderApp(app);
    expect(await screen.findByTestId("home")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId("welcome")).toBeNull());
  });

  it("is never offered to other users", async () => {
    const { calls } = mockFetch(world({ role: "member" }).routes);
    await renderApp(app);
    expect(await screen.findByTestId("home")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/setup/progress")).toBe(false);
  });

  it("shows the machine and the recommended pack, then the model step", async () => {
    mockFetch(world().routes);
    await renderApp(app, "/welcome");
    expect(await screen.findByTestId("welcome-hardware")).toHaveTextContent("8 GB");
    expect(await screen.findByText("Local, CPU")).toBeInTheDocument();
    expect(screen.getByTestId("welcome-progress")).toHaveTextContent("Step 1 of 3");
    const user = userEvent.setup();
    await user.click(screen.getByTestId("welcome-next"));
    expect(await screen.findByTestId("model-connections")).toBeInTheDocument();
    expect(screen.getByTestId("welcome-progress")).toHaveTextContent("Step 2 of 3");
  });

  it("still lets the administrator move on when the module-manager is down", async () => {
    const w = world();
    w.state.catalogDown = true;
    mockFetch(w.routes);
    await renderApp(app, "/welcome");
    expect(await screen.findByTestId("welcome-unavailable")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByTestId("welcome-next"));
    expect(await screen.findByTestId("welcome-model")).toBeInTheDocument();
  });

  it("starts an example project, sends its first message and remembers it was done", async () => {
    const w = world();
    const { calls } = mockFetch(w.routes);
    await renderApp(app, "/welcome");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("welcome-next"));
    await user.click(await screen.findByTestId("welcome-next"));
    await user.click(await screen.findByTestId("welcome-example"));
    expect(await screen.findByTestId("project-page")).toBeInTheDocument();
    const message = calls.find((c) => c.path === "/projects/p1/messages");
    expect(message?.body).toMatchObject({ content: expect.stringContaining("to-do list") });
    expect(w.state.completed).toBe(true);
  });

  it("can be skipped from the first step, and that is remembered", async () => {
    const w = world();
    mockFetch(w.routes);
    await renderApp(app, "/welcome");
    await userEvent.setup().click(await screen.findByTestId("welcome-skip"));
    expect(await screen.findByTestId("home")).toBeInTheDocument();
    expect(w.state.completed).toBe(true);
  });

  it("speaks French", async () => {
    mockFetch(world({ lang: "fr" }).routes);
    await renderApp(app, "/welcome");
    const { setLang } = await import("../i18n");
    await setLang("fr");
    expect(await screen.findByText("Bienvenue dans Cobble")).toBeInTheDocument();
  });
});
