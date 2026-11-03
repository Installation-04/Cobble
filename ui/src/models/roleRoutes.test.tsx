import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RoleRoutes as RoutesData } from "../api/types";
import { setLang } from "../i18n";
import { mockFetch, renderApp, type Handler } from "../test/utils";
import { RoleRoutes } from "./RoleRoutes";

afterEach(() => vi.unstubAllGlobals());

const ROLES = ["planner", "test-writer", "worker", "reviewer", "escalation"];

function data(routes: Record<string, string[]> = {}): RoutesData {
  return {
    roles: ROLES,
    max_chain: 4,
    routes,
    effective: Object.fromEntries(ROLES.map((r) => [r, routes[r] ?? ["fake"]])),
  };
}

function fixture() {
  const state = { routes: {} as Record<string, string[]>, fail: false };
  const routes: Record<string, Handler> = {
    "GET /models/routes": () => ({ body: data(state.routes) }),
    "GET /models": () => ({
      body: {
        models: [
          { name: "cheap", provider: "openai", model: "x", base_url: null, default: true },
          { name: "strong", provider: "anthropic", model: "y", base_url: null, default: false },
        ],
        default: "cheap",
        configured_default: "fake",
      },
    }),
    "PUT /models/routes": ({ body }) => {
      if (state.fail)
        return { status: 422, body: { error: { code: "validation_error", params: {} } } };
      state.routes = (body as { routes: Record<string, string[]> }).routes;
      return { body: data(state.routes) };
    },
  };
  return { state, routes };
}

describe("RoleRoutes", () => {
  it("shows every role with what it uses now", async () => {
    const f = fixture();
    f.state.routes = { worker: ["cheap", "strong"] };
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    expect(await screen.findByTestId("route-worker")).toBeInTheDocument();
    for (const role of ROLES) expect(screen.getByTestId(`route-${role}`)).toBeInTheDocument();
    expect(screen.getByTestId("route-worker-effective")).toHaveTextContent("cheap → strong");
    expect(screen.getByTestId("route-planner-effective")).toHaveTextContent("fake");
    expect(screen.getByTestId<HTMLSelectElement>("route-worker-1").value).toBe("strong");
  });

  it("saves the chosen models in order, without empty slots or duplicates", async () => {
    const f = fixture();
    const { calls } = mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    const user = userEvent.setup();
    await user.selectOptions(await screen.findByTestId("route-worker-0"), "cheap");
    await user.selectOptions(screen.getByTestId("route-worker-2"), "strong"); // slot 1 left empty
    await user.selectOptions(screen.getByTestId("route-reviewer-0"), "strong");
    await user.click(screen.getByTestId("routes-save"));
    expect(await screen.findByTestId("routes-saved")).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body).toEqual({ routes: { worker: ["cheap", "strong"], reviewer: ["strong"] } });
  });

  it("offers the connected models and the built-in one", async () => {
    mockFetch(fixture().routes);
    await renderApp(<RoleRoutes />);
    const select = await screen.findByTestId<HTMLSelectElement>("route-worker-0");
    expect([...select.options].map((o) => o.value)).toEqual(["", "cheap", "strong", "fake"]);
  });

  it("explains a refused save in words", async () => {
    const f = fixture();
    f.state.fail = true;
    mockFetch(f.routes);
    await renderApp(<RoleRoutes />);
    await userEvent.setup().click(await screen.findByTestId("routes-save"));
    expect(await screen.findByTestId("routes-error")).toBeInTheDocument();
    expect(screen.queryByTestId("routes-saved")).toBeNull();
  });

  it("speaks French", async () => {
    mockFetch(fixture().routes);
    await renderApp(<RoleRoutes />);
    await setLang("fr");
    await waitFor(() =>
      expect(screen.getByTestId("routes-save")).toHaveTextContent("Enregistrer les routes"),
    );
    expect(screen.getByTestId("route-escalation")).toHaveTextContent("Escalade");
  });
});
