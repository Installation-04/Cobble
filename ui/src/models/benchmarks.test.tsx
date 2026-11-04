import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Benchmarks as BenchData, RoleRoutes as RoutesData } from "../api/types";
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

function fixture(bench: BenchData | null = BENCH) {
  const state = { saved: null as Record<string, string[]> | null };
  const routes: Record<string, Handler> = {
    "GET /models/routes": () => ({ body: routesData({ worker: ["fake"], planner: ["fake"] }) }),
    "GET /models/benchmarks": () => ({
      body: bench ?? { version: 1, results: [], suggested_worker: null },
    }),
    "GET /models/presets": () => ({
      body: { slots: {}, suggested: {}, local: [], models: [], presets: [] },
    }),
    "GET /models": () => ({
      body: {
        models: [],
        local: [{ name: "coder", model: "x", module: "ollama" }],
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

  it("shows nothing when no benchmark was run", async () => {
    mockFetch(fixture(null).routes);
    await renderApp(<RoleRoutes />);
    await screen.findByTestId("role-routes");
    expect(screen.queryByTestId("benchmarks")).toBeNull();
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
