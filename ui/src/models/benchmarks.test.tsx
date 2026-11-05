import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type {
  BenchmarkStatus as StatusData,
  Benchmarks as BenchData,
  RoleRoutes as RoutesData,
} from "../api/types";
import { setLang } from "../i18n";
import { mockFetch, renderApp, type Handler } from "../test/utils";
import { workerChainWith } from "./Benchmarks";
import { RoleRoutes } from "./RoleRoutes";

afterEach(() => vi.unstubAllGlobals());

const ROLES = ["planner", "test-writer", "worker", "reviewer", "escalation"];

function routesData(routes: Record<string, string[]> = {}): RoutesData {
  return {
    roles: ROLES,
    max_chain: 3,
    routes,
    effective: Object.fromEntries(ROLES.map((r) => [r, routes[r] ?? ["fake"]])),
  };
}

const BENCH: BenchData = {
  version: 1,
  suggested_worker: "coder",
  results: [
    {
      model: "coder",
      quality: 0.875,
      seconds: 12,
      tokens_per_second: 41.6,
      created_at: "",
      failed_tasks: 1,
      tasks: 8,
    },
    {
      model: "tiny",
      quality: 0.5,
      seconds: 5,
      tokens_per_second: null,
      created_at: "",
      failed_tasks: 4,
      tasks: 8,
    },
  ],
};

const IDLE: StatusData = {
  state: "idle",
  models: [],
  model: null,
  model_index: 0,
  task: 0,
  tasks: 8,
  started_at: null,
  finished_at: null,
  error: null,
};

function fixture(bench: BenchData | null = BENCH) {
  const state = {
    saved: null as Record<string, string[]> | null,
    started: null as { models: string[]; allow_paid: boolean } | null,
    status: IDLE,
    startError: null as string | null,
    results: bench,
  };
  const routes: Record<string, Handler> = {
    "GET /models/routes": () => ({ body: routesData({ worker: ["fake"], planner: ["fake"] }) }),
    "GET /models/benchmarks": () => ({
      body: state.results ?? { version: 1, results: [], suggested_worker: null },
    }),
    "GET /models/benchmarks/status": () => ({ body: state.status }),
    "POST /models/benchmarks/run": ({ body }) => {
      state.started = body as { models: string[]; allow_paid: boolean };
      if (state.startError) {
        return { status: 409, body: { error: { code: state.startError, params: {} } } };
      }
      state.status = { ...IDLE, state: "running", models: state.started.models, model: "coder" };
      return { status: 202, body: state.status };
    },
    "GET /models/presets": () => ({
      body: { slots: {}, suggested: {}, local: [], models: [], presets: [] },
    }),
    "GET /models": () => ({
      body: {
        models: [{ name: "cheap", provider: "openai", model: "gpt", default: false }],
        local: [
          { name: "coder", model: "x", module: "ollama" },
          { name: "tiny", model: "y", module: "ollama" },
        ],
        default: null,
        configured_default: "fake",
      },
    }),
    "PUT /models/routes": ({ body }) => {
      state.saved = (body as { routes: Record<string, string[]> }).routes;
      return { body: routesData(state.saved) };
    },
  };
  return { state, routes };
}

describe("Benchmarks", () => {
  it("lists the results, marks the proposed worker and saves it first, keeping the rest", async () => {
    const f = fixture();
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    const row = await screen.findByTestId("bench-coder");
    expect(row).toHaveTextContent("88 %");
    expect(row).toHaveTextContent("42 tokens/s");
    expect(row).toHaveTextContent("proposed for the worker");
    expect(screen.getByTestId("bench-tiny")).toHaveTextContent("—");
    expect(screen.queryByTestId("bench-use-tiny")).toBeNull();
    await userEvent.setup().click(screen.getByTestId("bench-use-coder"));
    await waitFor(() => expect(f.state.saved).not.toBeNull());
    expect(f.state.saved).toEqual({ worker: ["coder", "fake"], planner: ["fake"] });
    await waitFor(() =>
      expect(screen.getByTestId<HTMLSelectElement>("route-worker-0").value).toBe("coder"),
    );
  });

  it("offers to run one when no benchmark was run yet", async () => {
    mockFetch(fixture(null).routes);
    await renderApp(<RoleRoutes />);
    await screen.findByTestId("role-routes");
    expect(await screen.findByText("No benchmark has been run yet.")).toBeInTheDocument();
    expect(screen.getByTestId("bench-run-open")).toBeEnabled();
  });

  it("runs the checked local models, never a paid one unless chosen", async () => {
    const f = fixture();
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("bench-run-open"));
    expect(await screen.findByTestId("bench-choose-coder")).toBeChecked();
    expect(screen.getByTestId("bench-choose-tiny")).toBeChecked();
    expect(screen.getByTestId("bench-choose-cheap")).not.toBeChecked();
    await user.click(screen.getByTestId("bench-choose-tiny"));
    await user.click(screen.getByTestId("bench-run-start"));
    await waitFor(() => expect(f.state.started).not.toBeNull());
    expect(f.state.started).toEqual({ models: ["coder"], allow_paid: false });
    expect(await screen.findByTestId("bench-progress")).toHaveTextContent(
      "Measuring coder: task 0 of 8 (model 1 of 1)",
    );
    expect(screen.getByTestId("bench-run-open")).toBeDisabled();
  });

  it("confirms a paid model by ticking it", async () => {
    const f = fixture();
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("bench-run-open"));
    await user.click(await screen.findByTestId("bench-choose-cheap"));
    await user.click(screen.getByTestId("bench-run-start"));
    await waitFor(() => expect(f.state.started).not.toBeNull());
    expect(f.state.started).toEqual({ models: ["coder", "tiny", "cheap"], allow_paid: true });
  });

  it("says so when a run is already going", async () => {
    const f = fixture();
    f.state.startError = "benchmark_running";
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("bench-run-open"));
    await user.click(await screen.findByTestId("bench-run-start"));
    expect(await screen.findByTestId("bench-run-error")).toHaveTextContent(
      "A benchmark is already running",
    );
  });

  it("follows a run in progress, then refreshes the results", async () => {
    const f = fixture(null);
    f.state.status = { ...IDLE, state: "running", models: ["coder"], model: "coder", task: 3 };
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    expect(await screen.findByTestId("bench-progress")).toHaveTextContent("task 3 of 8");
    f.state.results = BENCH;
    f.state.status = { ...IDLE, models: ["coder"], model: "coder", task: 8 };
    await waitFor(() => expect(screen.getByTestId("bench-coder")).toBeInTheDocument(), {
      timeout: 6000,
    });
    expect(screen.getByTestId("bench-finished")).toBeInTheDocument();
    expect(screen.queryByTestId("bench-progress")).toBeNull();
  }, 10000);

  it("explains why a run stopped, in both languages", async () => {
    const f = fixture();
    f.state.status = { ...IDLE, error: "sandbox_unavailable" };
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    expect(await screen.findByTestId("bench-failed")).toHaveTextContent(
      "The code sandbox is not available",
    );
    await setLang("fr");
    await waitFor(() =>
      expect(screen.getByTestId("bench-failed")).toHaveTextContent("Le bac à sable de code"),
    );
    await setLang("en");
  });

  it("does not invent a message for an unknown error code", async () => {
    const f = fixture();
    f.state.status = { ...IDLE, error: "whatever" };
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    expect(await screen.findByTestId("bench-failed")).toHaveTextContent("unknown reason");
  });

  it("speaks French", async () => {
    mockFetch(fixture().routes);
    await renderApp(<RoleRoutes />);
    await screen.findByTestId("bench-use-coder");
    await setLang("fr");
    await waitFor(() =>
      expect(screen.getByTestId("bench-use-coder")).toHaveTextContent("Utiliser comme développeur"),
    );
    await setLang("en");
  });

  it("puts the model first, drops a duplicate and respects the chain limit", () => {
    expect(workerChainWith("a", ["b", "a", "c", "d"], 3)).toEqual(["a", "b", "c"]);
  });
});
