import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ProjectCosts } from "../api/types";
import { setLang } from "../i18n";
import { ME, mockFetch, renderApp } from "../test/utils";
import { CostsTab } from "./CostsTab";
import * as provider from "./ProjectDataProvider";

afterEach(() => vi.restoreAllMocks());

function costs(fallbacks?: ProjectCosts["fallbacks"]): ProjectCosts {
  return {
    budget_usd: null,
    spent_usd: "0.33",
    tokens: { prompt: 10, completion: 5 },
    estimate_usd: null,
    by_task: [],
    by_model: [],
    by_role: [],
    ...(fallbacks ? { fallbacks } : {}),
  };
}

async function show(value: ProjectCosts) {
  vi.spyOn(provider, "useProjectData").mockReturnValue({
    costs: value,
    buildError: null,
    paused: false,
  } as unknown as ReturnType<typeof provider.useProjectData>);
  await renderApp(<CostsTab />);
}

const LINE = { prompt_tokens: 1, completion_tokens: 1 };

describe("fallbacks in the costs tab", () => {
  it("says how many calls a fallback answered, by whom and instead of whom", async () => {
    await show(
      costs({
        calls: 3,
        total_calls: 5,
        by_model: [
          { model: "cheap-api", fallback_from: "local", calls: 2, cost_usd: "0.03", ...LINE },
          { model: "strong-api", fallback_from: "local", calls: 1, cost_usd: "0.30", ...LINE },
        ],
      }),
    );
    expect(await screen.findByTestId("costs-fallbacks-summary")).toHaveTextContent(
      "3 of 5 calls (60 %)",
    );
    const rows = screen.getAllByTestId("costs-fallbacks-row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText("cheap-api")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("local")).toBeInTheDocument();
    expect(screen.getByTestId("costs-fallbacks-hint")).toBeInTheDocument(); // 60 % is a lot
  });

  it("stays quiet about routes when only a few calls fell back", async () => {
    await show(
      costs({
        calls: 1,
        total_calls: 20,
        by_model: [
          { model: "cheap-api", fallback_from: "local", calls: 1, cost_usd: "0.01", ...LINE },
        ],
      }),
    );
    expect(await screen.findByTestId("costs-fallbacks")).toBeInTheDocument();
    expect(screen.queryByTestId("costs-fallbacks-hint")).toBeNull();
  });

  it("is not shown when nothing fell back, or when the server does not report it", async () => {
    await show(costs({ calls: 0, total_calls: 4, by_model: [] }));
    expect(await screen.findByTestId("costs-tab")).toBeInTheDocument();
    expect(screen.queryByTestId("costs-fallbacks")).toBeNull();
  });

  it("speaks French", async () => {
    mockFetch({ "GET /auth/me": () => ({ body: { ...ME, lang: "fr" } }) });
    await show(
      costs({
        calls: 1,
        total_calls: 2,
        by_model: [{ model: "m", fallback_from: "l", calls: 1, cost_usd: "0.01", ...LINE }],
      }),
    );
    await setLang("fr");
    expect(
      await screen.findByRole("heading", { name: "Appels traités par un modèle de repli" }),
    ).toBeInTheDocument();
  });
});
