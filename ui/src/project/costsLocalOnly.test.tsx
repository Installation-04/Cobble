import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ProjectCosts } from "../api/types";
import { ApiError } from "../api/client";
import { ME, mockFetch } from "../test/utils";
import { setLang } from "../i18n";
import { showCosts } from "./costsTestUtils";

afterEach(() => vi.restoreAllMocks());

const COSTS: ProjectCosts = {
  budget_usd: null,
  spent_usd: "0",
  tokens: { prompt: 0, completion: 0 },
  estimate_usd: null,
  by_task: [],
  by_model: [],
  by_role: [],
};

describe("the local-only switch", () => {
  it("is off by default and explains what it needs", async () => {
    await showCosts(COSTS);
    const card = await screen.findByTestId("costs-local-only");
    expect(card).toHaveAttribute("data-state", "off");
    expect(screen.getByTestId<HTMLInputElement>("local-only-toggle").checked).toBe(false);
    expect(card).toHaveTextContent(/Ollama/);
  });

  it("turns the project local-only through the workspace and says what it means", async () => {
    const { updateProject } = await showCosts(COSTS);
    await userEvent.setup().click(await screen.findByTestId("local-only-toggle"));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("p1", { local_only: true }));
  });

  it("shows a project that is already local-only, and turns it off the same way", async () => {
    const { updateProject } = await showCosts(COSTS, { project: { local_only: true } });
    const card = await screen.findByTestId("costs-local-only");
    expect(card).toHaveAttribute("data-state", "on");
    expect(card).toHaveTextContent(/Nothing of this project is sent/);
    await userEvent.setup().click(screen.getByTestId("local-only-toggle"));
    await waitFor(() => expect(updateProject).toHaveBeenCalledWith("p1", { local_only: false }));
  });

  it("explains a refusal in words", async () => {
    await showCosts(COSTS, {
      updateProject: async () => {
        throw new ApiError(500, "internal_error", {});
      },
    });
    await userEvent.setup().click(await screen.findByTestId("local-only-toggle"));
    expect(await screen.findByTestId("local-only-error")).toBeInTheDocument();
  });

  it("speaks French", async () => {
    mockFetch({ "GET /auth/me": () => ({ body: { ...ME, lang: "fr" } }) });
    await showCosts(COSTS);
    await setLang("fr");
    expect(await screen.findByText(/Local seulement/)).toBeInTheDocument();
  });
});
