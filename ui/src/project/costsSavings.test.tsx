import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CostSavings, ProjectCosts } from "../api/types";
import { setLang } from "../i18n";
import { ME, mockFetch, renderApp } from "../test/utils";
import { CostsTab } from "./CostsTab";
import * as provider from "./ProjectDataProvider";

afterEach(() => vi.restoreAllMocks());

async function show(savings: CostSavings | null | undefined) {
  const costs: ProjectCosts = {
    budget_usd: null,
    spent_usd: "0.002",
    tokens: { prompt: 1000, completion: 500 },
    estimate_usd: null,
    by_task: [],
    by_model: [],
    by_role: [],
    ...(savings === undefined ? {} : { savings }),
  };
  vi.spyOn(provider, "useProjectData").mockReturnValue({
    costs,
    buildError: null,
    paused: false,
  } as unknown as ReturnType<typeof provider.useProjectData>);
  await renderApp(<CostsTab />);
}

const SAVED: CostSavings = {
  reference_model: "big",
  reference_cost_usd: "0.025",
  actual_cost_usd: "0.002",
  saved_usd: "0.023",
  saved_percent: 92,
};

describe("the savings counter", () => {
  it("says how much was saved compared with the strongest model", async () => {
    await show(SAVED);
    const card = await screen.findByTestId("costs-savings");
    expect(card).toHaveAttribute("data-state", "saved");
    expect(screen.getByTestId("costs-saved")).toHaveTextContent("92 %");
    expect(card).toHaveTextContent("big");
  });

  it("says so plainly when nothing was saved, never hides a loss", async () => {
    await show({ ...SAVED, saved_usd: "-0.5", saved_percent: -20 });
    const card = await screen.findByTestId("costs-savings");
    expect(card).toHaveAttribute("data-state", "none");
    expect(screen.getByTestId("costs-saved")).toHaveTextContent("No saving compared with big");
  });

  it("says it is not available when the strongest model cannot be priced, or by an older server", async () => {
    await show(null);
    expect(await screen.findByTestId("costs-savings")).toHaveAttribute("data-state", "unavailable");
  });

  it("does not break when the server does not report savings at all", async () => {
    await show(undefined);
    expect(await screen.findByTestId("costs-savings")).toHaveAttribute("data-state", "unavailable");
  });

  it("speaks French", async () => {
    mockFetch({ "GET /auth/me": () => ({ body: { ...ME, lang: "fr" } }) });
    await show(SAVED);
    await setLang("fr");
    expect(await screen.findByText(/Vous avez économisé/)).toBeInTheDocument();
  });
});
