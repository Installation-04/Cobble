import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PresetsData, RoleRoutes as RoutesData } from "../api/types";
import { setLang } from "../i18n";
import { mockFetch, renderApp, type Handler } from "../test/utils";
import { RoleRoutes } from "./RoleRoutes";

afterEach(() => vi.unstubAllGlobals());

const ROLES = ["planner", "test-writer", "worker", "reviewer", "escalation"];

function routesData(routes: Record<string, string[]> = {}): RoutesData {
  return {
    roles: ROLES,
    max_chain: 4,
    routes,
    effective: Object.fromEntries(ROLES.map((r) => [r, routes[r] ?? ["fake"]])),
  };
}

/** What the server would answer for these slots (the same rules, kept tiny). */
function presetsFor(slots: { local?: string; cheap?: string; strong?: string }): PresetsData {
  const strong = slots.strong || "fake";
  const cheap = slots.cheap || strong;
  const local = slots.local || null;
  return {
    slots: { local, cheap: slots.cheap ?? null, strong },
    suggested: { local: "coder", cheap: null, strong: "fake" },
    local: ["coder"],
    models: ["cheap-api", "coder", "fake", "strong-api"],
    presets: [
      {
        id: "economical-local",
        required: ["local", "strong"],
        available: local !== null,
        missing: local === null ? ["local"] : [],
        routes:
          local === null
            ? {}
            : {
                planner: [strong, cheap],
                "test-writer": [local, cheap],
                worker: [local, cheap],
                reviewer: [local, cheap],
                escalation: [strong],
              },
      },
      {
        id: "balanced",
        required: ["strong"],
        available: true,
        missing: [],
        routes: {
          planner: [strong],
          "test-writer": [cheap, strong],
          worker: [cheap, strong],
          reviewer: [strong],
          escalation: [strong],
        },
      },
    ],
  };
}

function fixture() {
  const state = { applied: null as string | null, fail: false, last: {} as Record<string, string> };
  const routes: Record<string, Handler> = {
    "GET /models/routes": () => ({ body: routesData() }),
    "GET /models": () => ({
      body: {
        models: [
          { name: "cheap-api", provider: "openai", model: "x", base_url: null, default: false },
          { name: "strong-api", provider: "anthropic", model: "y", base_url: null, default: true },
        ],
        local: [{ name: "coder", model: "ollama_chat/q", module: "ollama" }],
        default: "strong-api",
        configured_default: "fake",
      },
    }),
    "GET /models/presets": () => ({ body: presetsFor({ local: "coder", strong: "strong-api" }) }),
    "POST /models/presets/economical-local/apply": ({ body }) => {
      state.last = body as Record<string, string>;
      if (state.fail) {
        return { status: 422, body: { error: { code: "preset_unavailable", params: {} } } };
      }
      state.applied = "economical-local";
      const out = presetsFor(body as Record<string, string>).presets[0]!.routes;
      return { body: routesData(out) };
    },
  };
  return { state, routes };
}

describe("Presets", () => {
  it("shows both presets with the routes they would give", async () => {
    mockFetch(fixture().routes);
    await renderApp(<RoleRoutes />);
    const eco = await screen.findByTestId("preset-economical-local");
    expect(eco).toHaveAttribute("data-available", "true");
    expect(within(eco).getByTestId("preset-economical-local-routes")).toHaveTextContent("coder");
    expect(screen.getByTestId("preset-balanced")).toBeInTheDocument();
  });

  it("starts from the suggested models and offers local ones only in the local slot", async () => {
    mockFetch(fixture().routes);
    await renderApp(<RoleRoutes />);
    const local = await screen.findByTestId<HTMLSelectElement>("preset-slot-local");
    expect(local.value).toBe("coder");
    expect([...local.options].map((o) => o.value)).toEqual(["", "coder"]);
    const strong = screen.getByTestId<HTMLSelectElement>("preset-slot-strong");
    expect(strong.value).toBe("fake");
    expect([...strong.options].map((o) => o.value)).toContain("strong-api");
  });

  it("asks before replacing the routes, then sends the chosen models and refreshes the rows", async () => {
    const f = fixture();
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByTestId("preset-slot-strong"), "strong-api");
    await user.click(await screen.findByTestId("preset-economical-local-apply"));
    expect(f.state.applied).toBeNull(); // nothing is sent before the confirmation
    expect(
      within(screen.getByTestId("preset-economical-local")).getByRole("alert"),
    ).toHaveTextContent(/replaces the routes/);
    await user.click(screen.getByTestId("preset-economical-local-confirm"));
    await waitFor(() => expect(f.state.applied).toBe("economical-local"));
    expect(f.state.last).toMatchObject({ local: "coder", strong: "strong-api" });
    // the per-job rows now show what the preset stored
    await waitFor(() =>
      expect(screen.getByTestId<HTMLSelectElement>("route-worker-0").value).toBe("coder"),
    );
    expect(screen.getByTestId("route-planner-effective")).toHaveTextContent("strong-api");
  });

  it("disables a preset that cannot work and says what it lacks", async () => {
    const f = fixture();
    f.routes["GET /models/presets"] = () => ({ body: presetsFor({ strong: "fake" }) });
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    expect(await screen.findByTestId("preset-economical-local-apply")).toBeDisabled();
    expect(screen.getByTestId("preset-economical-local-missing")).toHaveTextContent("Local model");
    expect(screen.getByTestId("preset-balanced-apply")).toBeEnabled();
  });

  it("explains a refusal in words and keeps the old routes", async () => {
    const f = fixture();
    f.state.fail = true;
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("preset-economical-local-apply"));
    await user.click(screen.getByTestId("preset-economical-local-confirm"));
    expect(await screen.findByTestId("presets-error")).toBeInTheDocument();
    expect(screen.getByTestId<HTMLSelectElement>("route-worker-0").value).toBe("");
  });

  it("speaks French", async () => {
    mockFetch(fixture().routes);
    await renderApp(<RoleRoutes />);
    await setLang("fr");
    expect(await screen.findByText("Économique local")).toBeInTheDocument();
    expect(screen.getByText("Équilibré")).toBeInTheDocument();
  });
});
