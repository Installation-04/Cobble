import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModelPrices, ProjectCosts, RoleRoutes as RoutesData } from "../api/types";
import { setLang } from "../i18n";
import { showCosts } from "../project/costsTestUtils";
import { mockFetch, renderApp, type Handler } from "../test/utils";
import { RoleRoutes } from "./RoleRoutes";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const ROLES = ["planner", "test-writer", "worker", "reviewer", "escalation"];
const ROUTES: RoutesData = {
  roles: ROLES,
  max_chain: 3,
  routes: {},
  effective: Object.fromEntries(ROLES.map((r) => [r, ["fake"]])),
};

const LINE = {
  prompt_per_million_usd: "3",
  completion_per_million_usd: "15",
  free: false,
  changed: false,
  previous_prompt_per_million_usd: null,
  previous_completion_per_million_usd: null,
  changed_at: null,
};

const PRICES: ModelPrices = {
  change_window_days: 14,
  prices: [
    {
      ...LINE,
      model: "big",
      prompt_per_million_usd: "4",
      changed: true,
      previous_prompt_per_million_usd: "3",
      previous_completion_per_million_usd: "15",
    },
    {
      ...LINE,
      model: "llama-free",
      prompt_per_million_usd: "0",
      completion_per_million_usd: "0",
      free: true,
    },
  ],
};

function routes(prices: ModelPrices | null): Record<string, Handler> {
  return {
    "GET /models/routes": () => ({ body: ROUTES }),
    "GET /models/benchmarks": () => ({ body: { version: 1, results: [], suggested_worker: null } }),
    "GET /models/presets": () => ({
      body: { slots: {}, suggested: {}, local: [], models: [], presets: [] },
    }),
    "GET /models": () => ({
      body: { models: [], local: [], default: null, configured_default: "fake" },
    }),
    ...(prices ? { "GET /models/prices": () => ({ body: prices }) } : {}),
  };
}

describe("Settings → Models prices", () => {
  it("warns about a changed price, badges free tiers and states the provider terms", async () => {
    mockFetch(routes(PRICES));
    await renderApp(<RoleRoutes />);
    const warning = await screen.findByTestId("price-warning");
    expect(warning).toHaveTextContent("big: input 3 → 4, output 15 → 15");
    expect(screen.getByTestId("price-llama-free")).toHaveTextContent("free");
    expect(screen.getByTestId("price-big")).not.toHaveTextContent("free");
    expect(screen.getByTestId("free-terms")).toHaveTextContent("rate limits");
  });

  it("shows nothing when no price is known (or the server is older)", async () => {
    mockFetch(routes(null));
    await renderApp(<RoleRoutes />);
    await screen.findByTestId("role-routes");
    expect(screen.queryByTestId("prices")).toBeNull();
  });

  it("speaks French", async () => {
    mockFetch(routes(PRICES));
    await renderApp(<RoleRoutes />);
    await screen.findByTestId("price-warning");
    await setLang("fr");
    await waitFor(() =>
      expect(screen.getByTestId("price-warning")).toHaveTextContent("entrée 3 → 4"),
    );
    expect(screen.getByTestId("price-llama-free")).toHaveTextContent("gratuit");
    await setLang("en");
  });
});

describe("Costs tab prices", () => {
  const costs: ProjectCosts = {
    budget_usd: null,
    spent_usd: "0.50",
    tokens: { prompt: 10, completion: 5 },
    estimate_usd: null,
    by_task: [],
    by_model: [
      { model: "big", cost_usd: "0.5", prompt_tokens: 5, completion_tokens: 2, calls: 1 },
      {
        model: "llama-free",
        cost_usd: "0",
        prompt_tokens: 5,
        completion_tokens: 3,
        calls: 2,
        free: true,
      },
    ],
    by_role: [],
    free_calls: 2,
    price_changes: [PRICES.prices[0]!],
  };

  it("counts free calls, badges the free model and warns about the price change", async () => {
    await showCosts(costs);
    expect(await screen.findByTestId("costs-free-calls")).toHaveTextContent("2 calls");
    expect(screen.getByTestId("costs-price-changes")).toHaveTextContent("big: input 3 → 4");
    const rows = screen.getAllByTestId("costs-by-model-row");
    expect(rows[1]).toHaveTextContent("free");
    expect(rows[0]).not.toHaveTextContent("free");
  });

  it("shows no card when there is nothing to say", async () => {
    await showCosts({ ...costs, free_calls: 0, price_changes: [] });
    await screen.findByTestId("costs-tab");
    expect(screen.queryByTestId("costs-prices")).toBeNull();
  });
});
