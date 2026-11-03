import { act, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ModuleEntry, ModuleOperation, ModulePack, ModulePlan } from "../api/types";
import { StorePage } from "../pages/StorePage";
import { FakeEventSource, installFakeEventSource } from "../test/fakeEventSource";
import { ME, mockFetch, renderApp, type Handler } from "../test/utils";
import { useModuleOperation } from "./useModuleOperation";

function entry(id: string, over: Partial<ModuleEntry> = {}): ModuleEntry {
  return {
    id,
    name: id.charAt(0).toUpperCase() + id.slice(1),
    version: "1.0.0",
    category: "git",
    description: { en: `${id} in English`, fr: `${id} en français` },
    license: "MIT",
    provides: [],
    requires: [],
    exclusive: [],
    variants: [],
    web_ui: null,
    secrets: [],
    host_access: [],
    offline: false,
    hardware: { ok: true, variant: null, problems: [] },
    installed: null,
    ...over,
  };
}

const INSTALLED = {
  state: "running",
  explicit: true,
  variant: null,
  version: "1.0.0",
  error: null,
};

function plan(...steps: [string, string][]): ModulePlan {
  return {
    steps: steps.map(([action, module]) => ({ action: action as "install", module })),
    explicit: [],
    installed: [],
    auto_added: [],
    cascade: [],
    replaced: [],
    auto_removed: [],
    links_added: [],
    links_removed: [],
  };
}

/** A fake module-manager behind the modules API; tests change `world` as the story goes. */
function world() {
  const state = {
    modules: [
      entry("forgejo", {
        provides: ["git"],
        web_ui: { service: "f", port: 3000, path: "/git", strip_prefix: true },
      }),
      entry("woodpecker", { category: "ci", provides: ["ci"], requires: ["git"] }),
      entry("ollama", {
        category: "llm",
        hardware: {
          ok: false,
          variant: null,
          problems: [{ code: "ram", needed: "8192", have: "4096" }],
        },
      }),
    ] as ModuleEntry[],
    plans: [] as (ModulePlan | { status: number; code: string; params?: object })[],
    start: { status: 202, body: { operation_id: "op1" } } as { status: number; body: unknown },
    operation: {
      id: "op1",
      action: "install",
      modules: [],
      state: "running",
      plan: null,
      error: null,
    } as ModuleOperation,
    secrets: {} as Record<string, boolean>,
    packs: [] as ModulePack[],
    packsStatus: 200,
    catalogStatus: 200,
    me: ME as object,
  };
  const reply = (item: ModulePlan | { status: number; code: string; params?: object }) =>
    "status" in item
      ? { status: item.status, body: { error: { code: item.code, params: item.params ?? {} } } }
      : { body: item };
  const routes: Record<string, Handler> = {
    "GET /auth/me": () => ({ body: state.me }),
    "GET /modules": () =>
      state.catalogStatus === 200
        ? { body: { modules: state.modules, hardware: { ram_mb: 4096, gpu: "none" } } }
        : {
            status: state.catalogStatus,
            body: { error: { code: "module_manager_unavailable", params: {} } },
          },
    "GET /modules/packs": () =>
      state.packsStatus === 200
        ? {
            body: {
              packs: state.packs,
              problems: {},
              recommended: state.packs.find((p) => p.recommended)?.id ?? null,
            },
          }
        : {
            status: state.packsStatus,
            body: { error: { code: "module_manager_unavailable", params: {} } },
          },
    "POST /modules/plan": () =>
      reply(state.plans.length > 1 ? state.plans.shift()! : state.plans[0]),
    "POST /modules/operations": () => state.start,
    "GET /modules/operations/op1": () => ({ body: state.operation }),
    "GET /modules/forgejo/secrets": () => ({ body: state.secrets }),
  };
  return { state, routes };
}

const page = (
  <Routes>
    <Route path="/store" element={<StorePage />} />
  </Routes>
);

async function open(id: string) {
  const user = userEvent.setup();
  await user.click(await screen.findByTestId(`module-card-${id}`));
  return user;
}

beforeEach(() => installFakeEventSource());
afterEach(() => vi.unstubAllGlobals());

describe("the catalogue", () => {
  it("shows every module with its state and its fit for this machine", async () => {
    const w = world();
    w.state.modules[0].installed = INSTALLED as ModuleEntry["installed"];
    const { calls } = mockFetch(w.routes);
    await renderApp(page, "/store");
    expect(await screen.findByTestId("module-card-forgejo")).toBeInTheDocument();
    expect(screen.getByTestId("module-state-forgejo")).toHaveTextContent("Installed");
    expect(screen.getByTestId("module-state-woodpecker")).toHaveTextContent("Not installed");
    expect(screen.getByText("forgejo in English")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "GET" && c.path === "/modules")).toBe(true);
  });

  it("filters by search words and by category", async () => {
    const w = world();
    mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = userEvent.setup();
    await screen.findByTestId("module-card-forgejo");
    await user.type(screen.getByTestId("store-search"), "git");
    expect(screen.queryByTestId("module-card-woodpecker")).not.toBeInTheDocument();
    expect(screen.getByTestId("module-card-forgejo")).toBeInTheDocument();
    await user.clear(screen.getByTestId("store-search"));
    await user.selectOptions(screen.getByTestId("store-category"), "ci");
    expect(screen.queryByTestId("module-card-forgejo")).not.toBeInTheDocument();
    expect(screen.getByTestId("module-card-woodpecker")).toBeInTheDocument();
    await user.type(screen.getByTestId("store-search"), "zzzz");
    expect(screen.getByTestId("store-no-match")).toBeInTheDocument();
  });

  it("greys a module that does not fit, says why, and cannot install it", async () => {
    const w = world();
    mockFetch(w.routes);
    await renderApp(page, "/store");
    const card = await screen.findByTestId("module-card-ollama");
    expect(card).toHaveAttribute("data-fits", "false"); // greyed, but still opens to say why
    expect(screen.getByTestId("module-reason-ollama")).toHaveTextContent(
      "needs 8192 MB of memory, this machine has 4096 MB",
    );
    const user = userEvent.setup();
    await user.click(card);
    expect(screen.getByTestId("module-problems")).toHaveTextContent("needs 8192 MB");
    expect(screen.getByTestId("module-install")).toBeDisabled();
  });

  it("explains an unreachable module-manager", async () => {
    const w = world();
    w.state.catalogStatus = 503;
    mockFetch(w.routes);
    await renderApp(page, "/store");
    expect(await screen.findByRole("alert")).toHaveTextContent("module manager is not available");
  });

  it("is for administrators: others get a message and no request", async () => {
    const w = world();
    w.state.me = { ...ME, role: "user" };
    const { calls } = mockFetch(w.routes);
    await renderApp(page, "/store");
    expect(await screen.findByTestId("view-store-forbidden")).toHaveTextContent("administrator");
    expect(calls.some((c) => c.path.startsWith("/modules"))).toBe(false);
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("shows which secrets are set and never a value", async () => {
    const w = world();
    w.state.modules[0].installed = INSTALLED as ModuleEntry["installed"];
    w.state.secrets = { api_token: true, admin_password: false };
    mockFetch(w.routes);
    await renderApp(page, "/store");
    await open("forgejo");
    const secrets = await screen.findByTestId("module-secrets");
    expect(within(secrets).getByText("api_token").parentElement).toHaveTextContent("set");
    expect(within(secrets).getByText("admin_password").parentElement).toHaveTextContent("not set");
    expect(screen.getByTestId("module-open")).toHaveAttribute("href", "/git/");
  });
});

describe("installing", () => {
  it("previews the plan, runs it, follows the steps and refreshes the catalogue", async () => {
    const w = world();
    const p = plan(["install", "forgejo"], ["install", "woodpecker"]);
    p.auto_added = ["forgejo"];
    w.state.plans = [p];
    const { calls } = mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = await open("woodpecker");
    await user.click(screen.getByTestId("module-install"));
    expect(await screen.findByTestId("flow-steps")).toHaveTextContent("Install forgejo");
    expect(screen.getByTestId("flow-auto-added")).toHaveTextContent("forgejo");
    expect(calls.filter((c) => c.path === "/modules/operations")).toHaveLength(0); // nothing yet

    await user.click(screen.getByTestId("flow-start"));
    await screen.findByTestId("flow-progress");
    expect(calls.find((c) => c.path === "/modules/operations")?.body).toMatchObject({
      action: "install",
      modules: ["woodpecker"],
    });
    const stream = FakeEventSource.last;
    expect(stream.url).toBe("/api/v1/modules/stream");
    stream.open();
    stream.emit("module.step", {
      operation_id: "other",
      module: "x",
      kind: "install",
      step: "up",
      ok: true,
    });
    stream.emit("module.step", {
      operation_id: "op1",
      module: "forgejo",
      kind: "install",
      step: "up",
      ok: true,
    });
    stream.emit("module.step", {
      operation_id: "op1",
      module: "forgejo",
      kind: "install",
      step: "health",
      ok: true,
    });
    const progress = await screen.findByTestId("flow-progress");
    await waitFor(() => expect(progress.children).toHaveLength(2)); // the other operation is ignored
    expect(progress).toHaveTextContent("Starting the containers");

    w.state.modules[1].installed = INSTALLED as ModuleEntry["installed"];
    stream.emit("module.operation", { operation_id: "op1", state: "done", error: null });
    expect(await screen.findByTestId("flow-done")).toHaveTextContent("Done.");
    await waitFor(() =>
      expect(
        calls.filter((c) => c.method === "GET" && c.path === "/modules").length,
      ).toBeGreaterThan(1),
    );
    await waitFor(() =>
      expect(screen.getByTestId("module-state-woodpecker")).toHaveTextContent("Installed"),
    );
  });

  it("asks which provider when several can, then plans again with the choice", async () => {
    const w = world();
    w.state.plans = [
      {
        status: 409,
        code: "module_needs_choice",
        params: { capability: "git", candidates: ["forgejo", "gitea"] },
      },
      plan(["install", "gitea"], ["install", "woodpecker"]),
    ];
    const { calls } = mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = await open("woodpecker");
    await user.click(screen.getByTestId("module-install"));
    expect(await screen.findByText(/Several modules can provide “git”/)).toBeInTheDocument();
    expect(screen.getByTestId("flow-choose")).toBeDisabled();
    await user.click(screen.getByLabelText("gitea"));
    await user.click(screen.getByTestId("flow-choose"));
    expect(await screen.findByTestId("flow-steps")).toHaveTextContent("Install gitea");
    const plans = calls.filter((c) => c.path === "/modules/plan");
    expect(plans[1].body).toMatchObject({ choices: { git: "gitea" } });
  });

  it("says nothing is left to do when the modules are already as asked", async () => {
    const w = world();
    w.state.plans = [plan()];
    mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = await open("forgejo");
    await user.click(screen.getByTestId("module-install"));
    expect(await screen.findByTestId("flow-done")).toHaveTextContent("Nothing to do");
  });

  it("explains a busy module-manager when starting", async () => {
    const w = world();
    w.state.plans = [plan(["install", "forgejo"])];
    w.state.start = { status: 409, body: { error: { code: "module_busy", params: {} } } };
    mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = await open("forgejo");
    await user.click(screen.getByTestId("module-install"));
    await user.click(await screen.findByTestId("flow-start"));
    expect(await screen.findByTestId("flow-failed")).toHaveTextContent("already in progress");
  });

  it("can be cancelled at the preview: nothing is started", async () => {
    const w = world();
    w.state.plans = [plan(["install", "forgejo"])];
    const { calls } = mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = await open("forgejo");
    await user.click(screen.getByTestId("module-install"));
    await screen.findByTestId("flow-steps");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("module-flow")).not.toBeInTheDocument();
    expect(calls.some((c) => c.path === "/modules/operations")).toBe(false);
  });
});

describe("removing", () => {
  it("asks before removing what depends on the module, then confirms the cascade", async () => {
    const w = world();
    w.state.modules[0].installed = INSTALLED as ModuleEntry["installed"];
    w.state.plans = [
      { status: 409, code: "module_needs_confirmation", params: { cascade: ["woodpecker"] } },
      plan(["uninstall", "woodpecker"], ["uninstall", "forgejo"]),
    ];
    const { calls } = mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = await open("forgejo");
    await user.click(screen.getByTestId("module-uninstall"));
    expect(await screen.findByTestId("flow-cascade")).toHaveTextContent("woodpecker");
    expect(calls.some((c) => c.path === "/modules/operations")).toBe(false);
    await user.click(screen.getByTestId("flow-cascade-ok"));
    expect(await screen.findByTestId("flow-steps")).toHaveTextContent("Remove woodpecker");
    await user.click(screen.getByTestId("flow-start"));
    await waitFor(() =>
      expect(calls.find((c) => c.path === "/modules/operations")?.body).toMatchObject({
        action: "uninstall",
        confirm_cascade: true,
      }),
    );
  });
});

describe("a failure", () => {
  async function fail(lang: "en" | "fr") {
    const w = world();
    w.state.plans = [plan(["install", "woodpecker"])];
    w.state.me = { ...ME, lang }; // the profile's language wins once it is loaded
    mockFetch(w.routes);
    await renderApp(page, "/store");
    await waitFor(() => expect(document.documentElement.lang).toBe(lang));
    const user = await open("woodpecker");
    await user.click(screen.getByTestId("module-install"));
    await user.click(await screen.findByTestId("flow-start"));
    await screen.findByTestId("flow-progress");
    FakeEventSource.last.emit("module.operation", {
      operation_id: "op1",
      state: "failed",
      error: {
        module: "woodpecker",
        step: "up",
        code: "up_failed",
        rolled_back: ["woodpecker"],
        partial: true,
      },
    });
    return screen.findByTestId("flow-failed");
  }

  it("says where, why and what was undone", async () => {
    const failed = await fail("en");
    expect(failed).toHaveTextContent("Failed at “woodpecker”, step “Starting the containers”");
    expect(failed).toHaveTextContent("The module could not be started.");
    expect(screen.getByTestId("flow-rolled-back")).toHaveTextContent("Rolled back: woodpecker");
    expect(failed).toHaveTextContent("Some removals had already been done");
  });

  it("speaks French when the interface does", async () => {
    const failed = await fail("fr");
    expect(failed).toHaveTextContent("Échec sur « woodpecker »");
    expect(failed).toHaveTextContent("Le module n'a pas pu démarrer.");
    expect(screen.getByTestId("flow-rolled-back")).toHaveTextContent("Annulé : woodpecker");
  });

  it("an unknown failure code is still shown as a failure, not hidden", async () => {
    const w = world();
    w.state.plans = [plan(["install", "woodpecker"])];
    mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = await open("woodpecker");
    await user.click(screen.getByTestId("module-install"));
    await user.click(await screen.findByTestId("flow-start"));
    await screen.findByTestId("flow-progress");
    FakeEventSource.last.emit("module.operation", {
      operation_id: "op1",
      state: "failed",
      error: { module: "woodpecker", step: "brand_new", code: "brand_new_code" },
    });
    expect(await screen.findByTestId("flow-failed")).toHaveTextContent("The operation failed.");
  });
});

describe("events of other operations", () => {
  it("never end the operation being followed", async () => {
    const w = world();
    w.state.plans = [plan(["install", "forgejo"])];
    mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = await open("forgejo");
    await user.click(screen.getByTestId("module-install"));
    await user.click(await screen.findByTestId("flow-start"));
    await screen.findByTestId("flow-progress");
    FakeEventSource.last.emit("module.operation", {
      operation_id: "someone-else",
      state: "done",
      error: null,
    });
    FakeEventSource.last.emit("module.operation", {
      operation_id: "someone-else",
      state: "failed",
      error: { module: "x", step: "up", code: "up_failed" },
    });
    expect(screen.getByTestId("module-flow")).toHaveAttribute("data-stage", "running");
    FakeEventSource.last.emit("module.operation", {
      operation_id: "op1",
      state: "done",
      error: null,
    });
    expect(await screen.findByTestId("flow-done")).toBeInTheDocument();
  });
});

describe("a running operation", () => {
  it("goes on when the drawer is closed, and can be reopened from the banner", async () => {
    const w = world();
    w.state.plans = [plan(["install", "forgejo"])];
    mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = await open("forgejo");
    await user.click(screen.getByTestId("module-install"));
    await user.click(await screen.findByTestId("flow-start"));
    await screen.findByTestId("flow-progress");
    await user.click(screen.getByTestId("sheet-close"));
    const banner = await screen.findByTestId("store-operation-banner");
    expect(banner).toHaveTextContent("Working on forgejo");
    await user.click(banner);
    expect(await screen.findByTestId("module-flow")).toHaveAttribute("data-stage", "running");
  });

  it("is reconciled after the stream comes back, so a missed end is never lost", async () => {
    const w = world();
    w.state.plans = [plan(["install", "forgejo"])];
    mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = await open("forgejo");
    await user.click(screen.getByTestId("module-install"));
    await user.click(await screen.findByTestId("flow-start"));
    await screen.findByTestId("flow-progress");
    const stream = FakeEventSource.last;
    stream.open();
    stream.drop(); // the end of the operation is emitted while the browser is offline...
    w.state.operation = { ...w.state.operation, state: "done" };
    stream.open(); // ...and the reconnection reads the state again
    expect(await screen.findByTestId("flow-done")).toBeInTheDocument();
  });
});

describe("polling", () => {
  it("reaches the end of an operation even if the stream never says anything", async () => {
    const w = world();
    w.state.plans = [plan(["install", "forgejo"])];
    let reads = 0;
    mockFetch({
      ...w.routes,
      "GET /modules/operations/op1": () => {
        reads += 1;
        return { body: { ...w.state.operation, state: reads >= 3 ? "done" : "running" } };
      },
    });
    const finished = vi.fn();
    const { result } = renderHook(() => useModuleOperation(finished, 20));
    act(() => result.current.begin("install", ["forgejo"]));
    await waitFor(() => expect(result.current.flow.stage).toBe("preview"));
    await act(async () => result.current.start());
    await waitFor(() => expect(result.current.flow.stage).toBe("done"));
    expect(reads).toBeGreaterThanOrEqual(3);
    expect(finished).toHaveBeenCalledTimes(1);
  });
});

function pack(id: string, modules: string[], over: Partial<ModulePack> = {}): ModulePack {
  return {
    id,
    name: { en: `${id} pack`, fr: `pack ${id}` },
    description: { en: `${id} in English`, fr: `${id} en français` },
    modules,
    hardware: { min_ram_mb: 0, gpu: "none" },
    priority: 0,
    fit: { ok: true, problems: [] },
    recommended: false,
    installed: false,
    installed_modules: [],
    ...over,
  };
}

describe("starter packs", () => {
  it("are offered first, the one for this machine is marked, the others say why not", async () => {
    const w = world();
    w.state.packs = [
      pack("local-cpu", ["forgejo", "woodpecker", "ollama"], { recommended: true }),
      pack("local-gpu", ["forgejo", "woodpecker", "ollama"], {
        fit: {
          ok: false,
          problems: [
            { module: null, code: "gpu", needed: "any", have: "none" },
            { module: "ollama", code: "ram", needed: "8192", have: "4096" },
          ],
        },
      }),
    ];
    mockFetch(w.routes);
    await renderApp(page, "/store");
    const cpu = await screen.findByTestId("pack-card-local-cpu");
    expect(cpu).toHaveAttribute("data-recommended", "true");
    expect(cpu).toHaveTextContent("Recommended for this machine");
    const gpu = screen.getByTestId("pack-card-local-gpu");
    expect(gpu).toHaveAttribute("data-fits", "false");
    expect(screen.getByTestId("pack-reason-local-gpu")).toHaveTextContent(
      "needs a GPU, this machine has no GPU · ollama: needs 8192 MB of memory, this machine has 4096 MB",
    );
  });

  it("install every module of the pack in one operation", async () => {
    const w = world();
    w.state.packs = [pack("api-only", ["forgejo", "woodpecker"], { recommended: true })];
    w.state.plans = [plan(["install", "forgejo"], ["install", "woodpecker"])];
    const { calls } = mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("pack-card-api-only"));
    expect(screen.getByTestId("pack-modules")).toHaveTextContent("forgejo, woodpecker");
    await user.click(screen.getByTestId("pack-install"));
    expect(await screen.findByTestId("flow-steps")).toHaveTextContent("Install woodpecker");
    expect(calls.find((c) => c.path === "/modules/plan")?.body).toMatchObject({
      action: "install",
      modules: ["forgejo", "woodpecker"],
    });
    await user.click(screen.getByTestId("flow-start"));
    await screen.findByTestId("flow-progress");
    expect(calls.find((c) => c.path === "/modules/operations")?.body).toMatchObject({
      modules: ["forgejo", "woodpecker"],
    });
    w.state.packs = [
      pack("api-only", ["forgejo", "woodpecker"], {
        installed: true,
        installed_modules: ["forgejo", "woodpecker"],
      }),
    ];
    FakeEventSource.last.emit("module.operation", {
      operation_id: "op1",
      state: "done",
      error: null,
    });
    expect(await screen.findByTestId("flow-done")).toBeInTheDocument();
    // the packs and the catalogue are read again when it ends
    await waitFor(() =>
      expect(
        calls.filter((c) => c.method === "GET" && c.path === "/modules/packs").length,
      ).toBeGreaterThan(1),
    );
    await user.click(screen.getByTestId("flow-dismiss"));
    expect(screen.queryByTestId("pack-install")).not.toBeInTheDocument(); // already installed
    expect(screen.getByTestId("pack-sheet")).toHaveTextContent("Installed");
  });

  it("cannot be installed when they do not fit, and the reasons are in the drawer", async () => {
    const w = world();
    w.state.packs = [
      pack("local-gpu", ["ollama"], {
        fit: {
          ok: false,
          problems: [{ module: null, code: "gpu", needed: "nvidia", have: "none" }],
        },
      }),
    ];
    const { calls } = mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("pack-card-local-gpu"));
    expect(screen.getByTestId("pack-install")).toBeDisabled();
    expect(screen.getByTestId("pack-problems")).toHaveTextContent("needs an NVIDIA GPU");
    expect(calls.some((c) => c.path === "/modules/plan")).toBe(false);
  });

  it("show how far a half installed pack is", async () => {
    const w = world();
    w.state.packs = [
      pack("p", ["forgejo", "woodpecker", "ollama"], { installed_modules: ["forgejo"] }),
    ];
    mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("pack-card-p"));
    expect(screen.getByTestId("pack-sheet")).toHaveTextContent("1 of 3 modules installed");
  });

  it("are shown in the language of the interface", async () => {
    const w = world();
    w.state.me = { ...ME, lang: "fr" };
    w.state.packs = [pack("p", ["forgejo"], { recommended: true })];
    mockFetch(w.routes);
    await renderApp(page, "/store");
    expect(await screen.findByTestId("pack-card-p")).toHaveTextContent("pack p");
    expect(screen.getByTestId("pack-card-p")).toHaveTextContent("p en français");
    expect(screen.getByTestId("pack-card-p")).toHaveTextContent("Recommandé pour cette machine");
  });

  it("do not stop the catalogue from working when they cannot be read", async () => {
    const w = world();
    w.state.packsStatus = 503;
    mockFetch(w.routes);
    await renderApp(page, "/store");
    expect(await screen.findByTestId("module-card-forgejo")).toBeInTheDocument();
    expect(screen.queryByTestId("store-packs")).not.toBeInTheDocument();
  });

  it("keep running when their drawer is closed, and the banner brings it back", async () => {
    const w = world();
    w.state.packs = [pack("api-only", ["forgejo", "woodpecker"])];
    w.state.plans = [plan(["install", "forgejo"], ["install", "woodpecker"])];
    mockFetch(w.routes);
    await renderApp(page, "/store");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("pack-card-api-only"));
    await user.click(screen.getByTestId("pack-install"));
    await user.click(await screen.findByTestId("flow-start"));
    await screen.findByTestId("flow-progress");
    await user.click(screen.getByTestId("sheet-close"));
    const banner = await screen.findByTestId("store-operation-banner");
    expect(banner).toHaveTextContent("api-only");
    await user.click(banner);
    expect(await screen.findByTestId("pack-sheet")).toBeInTheDocument();
    expect(screen.getByTestId("module-flow")).toHaveAttribute("data-stage", "running");
  });
});
