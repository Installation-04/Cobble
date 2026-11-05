import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CostSettings, ProjectCosts } from "../api/types";
import { setLang } from "../i18n";
import { showCosts } from "../project/costsTestUtils";
import { mockFetch, renderApp } from "../test/utils";
import { CostSettingsForm } from "./CostSettingsForm";

afterEach(() => vi.restoreAllMocks());

const EMPTY: CostSettings = {
  electricity_price_kwh_usd: null,
  electricity_watts: null,
  electricity_counts_in_budget: false,
  task_budget_multiplier: null,
  effective_task_budget_multiplier: "3",
  task_budget_floor_usd: "0.05",
};

describe("cost settings form", () => {
  it("saves the electricity price, the power draw and the task cap", async () => {
    let saved: unknown = null;
    const { calls } = mockFetch({
      "GET /settings/costs": () => ({ body: EMPTY }),
      "PUT /settings/costs": ({ body }) => {
        saved = body;
        return { body: { ...EMPTY, ...(body as object) } };
      },
    });
    await renderApp(<CostSettingsForm />);
    const user = userEvent.setup();
    await user.type(await screen.findByTestId("cost-price"), "0.25");
    await user.type(screen.getByTestId("cost-watts"), "300");
    await user.click(screen.getByTestId("cost-counts"));
    await user.type(screen.getByTestId("cost-multiplier"), "2");
    await user.click(screen.getByTestId("cost-settings-save"));
    expect(await screen.findByTestId("cost-settings-saved")).toBeInTheDocument();
    expect(saved).toEqual({
      electricity_price_kwh_usd: "0.25",
      electricity_watts: 300,
      electricity_counts_in_budget: true,
      task_budget_multiplier: "2",
    });
    expect(calls.some((c) => c.method === "PUT")).toBe(true);
  });

  it("sends nulls when left empty and speaks French", async () => {
    let saved: unknown = null;
    mockFetch({
      "GET /settings/costs": () => ({ body: EMPTY }),
      "PUT /settings/costs": ({ body }) => {
        saved = body;
        return { body: EMPTY };
      },
    });
    await renderApp(<CostSettingsForm />);
    await setLang("fr");
    const user = userEvent.setup();
    await waitFor(() =>
      expect(screen.getByTestId("cost-settings-save")).toHaveTextContent("Enregistrer"),
    );
    await user.click(screen.getByTestId("cost-settings-save"));
    await screen.findByTestId("cost-settings-saved");
    expect(saved).toEqual({
      electricity_price_kwh_usd: null,
      electricity_watts: null,
      electricity_counts_in_budget: false,
      task_budget_multiplier: null,
    });
  });
});

const BASE: ProjectCosts = {
  budget_usd: null,
  spent_usd: "1.25",
  api_usd: "1.00",
  tokens: { prompt: 10, completion: 5 },
  estimate_usd: null,
  by_task: [
    {
      ref: "T-001",
      cost_usd: "0.01",
      prompt_tokens: 1,
      completion_tokens: 1,
      calls: 1,
      cap_usd: "0.30",
    },
  ],
  by_model: [],
  by_role: [],
};

describe("costs tab: electricity and task caps", () => {
  it("shows the electricity apart, as an estimate, with the task cap", async () => {
    await showCosts({
      ...BASE,
      electricity: { usd: "0.25", seconds: 4, calls: 2, counts_in_budget: false, estimated: true },
    });
    const card = await screen.findByTestId("costs-electricity");
    expect(card).toHaveAttribute("data-counted", "no");
    expect(screen.getByTestId("costs-electricity-amount")).toHaveTextContent("0.25");
    expect(screen.getByTestId("costs-api-spend")).toHaveTextContent("1.00");
    expect(card).toHaveTextContent(/estimate/i);
    expect(screen.getByTestId("task-cap")).toHaveTextContent("0.30");
  });

  it("says when the electricity is counted, and hides the card without local calls", async () => {
    await showCosts({
      ...BASE,
      electricity: { usd: "0.25", seconds: 4, calls: 2, counts_in_budget: true, estimated: true },
    });
    expect(await screen.findByTestId("costs-electricity")).toHaveAttribute("data-counted", "yes");
  });

  it("shows no card when no local model was used", async () => {
    await showCosts({
      ...BASE,
      electricity: { usd: "0.00", seconds: 0, calls: 0, counts_in_budget: false, estimated: true },
    });
    await screen.findByTestId("costs-tab");
    expect(screen.queryByTestId("costs-electricity")).toBeNull();
  });
});
