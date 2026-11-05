import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ProjectReport } from "../api/types";
import { setLang } from "../i18n";
import { ME, mockFetch, renderApp } from "../test/utils";
import * as provider from "./ProjectDataProvider";
import { ReportTab } from "./ReportTab";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const REPORT: ProjectReport = {
  project: { id: "p1", name: "Todo", phase: "done", status: "active", finished: true },
  span: {
    started_at: "2026-01-01T10:00:00+00:00",
    ended_at: "2026-01-01T13:05:00+00:00",
    duration_seconds: 11100,
  },
  build: {
    milestones: [
      {
        ref: "M1",
        title: "Backend",
        status: "validated",
        validated_at: null,
        tasks_total: 4,
        tasks_done: 3,
        tasks_failed: 1,
      },
    ],
    milestones_validated: 1,
    tasks: { total: 4, done: 3, failed: 1, escalated: 2, attempts: 6 },
  },
  costs: {
    spent_usd: "0.002",
    budget_usd: "1.00",
    estimate_usd: null,
    budget_used_percent: 0,
    estimate_delta_percent: null,
    tokens: { prompt: 1000, completion: 500 },
    savings: {
      reference_model: "big",
      reference_cost_usd: "0.025",
      actual_cost_usd: "0.002",
      saved_usd: "0.023",
      saved_percent: 92,
    },
    by_model: [
      { model: "cheap", cost_usd: "0.002", prompt_tokens: 1000, completion_tokens: 500, calls: 3 },
    ],
    by_role: [
      { role: "worker", cost_usd: "0.002", prompt_tokens: 1000, completion_tokens: 500, calls: 3 },
    ],
    fallbacks: { calls: 1, total_calls: 3, by_model: [] },
  },
};

async function show(
  report: ProjectReport | null,
  lang: "en" | "fr" = "en",
): Promise<{ calls: { path: string }[] }> {
  vi.spyOn(provider, "useProjectData").mockReturnValue({
    project: { id: "p1", name: "Todo" },
  } as unknown as ReturnType<typeof provider.useProjectData>);
  const fetched = mockFetch({
    "GET /auth/me": () => ({ body: { ...ME, lang } }),
    "GET /projects/p1/report": () =>
      report
        ? { body: report }
        : { status: 404, body: { error: { code: "not_found", params: {} } } },
  });
  await renderApp(<ReportTab />);
  await setLang(lang);
  return fetched;
}

describe("the end-of-project report", () => {
  it("shows what was built, the time, the cost and the savings", async () => {
    await show(REPORT);
    expect(await screen.findByTestId("report-built-summary")).toHaveTextContent(
      "1 of 1 milestones validated. Tasks: 3 done out of 4, 1 failed, 2 escalated",
    );
    expect(screen.getByTestId("report-duration")).toHaveTextContent("3 h 5 min");
    expect(screen.getByTestId("report-spent")).toHaveTextContent("$0.002");
    expect(screen.getByTestId("report-budget")).toHaveTextContent("$1.00");
    expect(screen.getByTestId("report-estimate")).toHaveTextContent("n/a");
    expect(screen.getByTestId("costs-savings")).toHaveAttribute("data-state", "saved");
    expect(screen.getByTestId("costs-saved")).toHaveTextContent("92 %");
    expect(screen.getByTestId("report-fallbacks")).toHaveTextContent("1 of 3 calls");
    expect(screen.getByTestId("report-byModel")).toHaveTextContent("cheap");
    expect(screen.getByTestId("report-byRole")).toHaveTextContent("worker");
    expect(screen.getByTestId("report-milestones")).toHaveTextContent("M1 Backend");
  });

  it("offers the Markdown download, which the server localises", async () => {
    await show(REPORT);
    const link = await screen.findByTestId("report-download");
    expect(link).toHaveAttribute("href", "/api/v1/projects/p1/report?format=md");
    expect(link).toHaveAttribute("download");
  });

  it("says when the project is not finished and shows no savings when unavailable", async () => {
    await show({
      ...REPORT,
      project: { ...REPORT.project, finished: false },
      costs: { ...REPORT.costs, savings: null },
    });
    expect(await screen.findByTestId("report-state")).toHaveTextContent("not finished yet");
    expect(screen.getByTestId("costs-savings")).toHaveAttribute("data-state", "unavailable");
  });

  it("speaks French", async () => {
    await show(REPORT, "fr");
    expect(await screen.findByText(/1 jalons validés sur 1/)).toBeInTheDocument();
    expect(screen.getByTestId("report-download")).toHaveTextContent("Télécharger en Markdown");
  });

  it("shows an error when the report cannot be read", async () => {
    await show(null);
    expect(await screen.findByTestId("report-error")).toBeInTheDocument();
  });
});
