import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ModelListing, ModelProbe } from "../api/types";
import { setLang } from "../i18n";
import { mockFetch, renderApp } from "../test/utils";
import { connectionName } from "./connection";
import { ModelConnections } from "./ModelConnections";

const SECRET = "sk-super-secret-value-123";

function listing(over: Partial<ModelListing> = {}): ModelListing {
  return { models: [], default: null, configured_default: "demo", ...over } as ModelListing;
}

function fixture(initial: ModelListing = listing(), probe: Partial<ModelProbe> = {}) {
  const state = { listing: initial, putStatus: 200, putCode: "model_gateway_failed" };
  const routes = {
    "GET /models": () => ({ body: state.listing }),
    "PUT /models/openai-gpt-4.1-mini": () =>
      state.putStatus === 200
        ? {
            body: (state.listing = listing({
              models: [
                {
                  name: "openai-gpt-4.1-mini",
                  provider: "openai",
                  model: "gpt-4.1-mini",
                  base_url: null,
                  default: true,
                },
              ],
              default: "openai-gpt-4.1-mini",
            })),
          }
        : { status: state.putStatus, body: { error: { code: state.putCode, params: {} } } },
    "POST /models/openai-gpt-4.1-mini/test": () => ({
      body: { ok: true, code: "ok", ...probe },
    }),
    "DELETE /models/openai-gpt-4.1-mini": () => ({ body: (state.listing = listing()) }),
  };
  return { state, routes };
}

afterEach(() => vi.unstubAllGlobals());

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByTestId("model-model"), "gpt-4.1-mini");
  await user.type(screen.getByTestId("model-key"), SECRET);
  await user.click(screen.getByTestId("model-submit"));
}

describe("connectionName", () => {
  it("gives a name the platform accepts, always the same for the same model", () => {
    expect(connectionName("openai", "gpt-4.1-mini")).toBe("openai-gpt-4.1-mini");
    const odd = connectionName("openrouter", "Meta/Llama 3 (70B) !!");
    expect(odd).toMatch(/^[a-z0-9][a-z0-9._-]{0,39}$/);
    expect(connectionName("custom", "x".repeat(100)).length).toBeLessThanOrEqual(40);
    expect(connectionName("custom", "")).toBe("custom");
  });
});

describe("ModelConnections", () => {
  it("explains the built-in demo model when nothing is connected", async () => {
    const f = fixture();
    mockFetch(f.routes);
    await renderApp(<ModelConnections />);
    expect(await screen.findByTestId("models-empty")).toHaveTextContent("demo");
  });

  it("sends the key once, tests it, and never shows it again", async () => {
    const f = fixture();
    const { calls } = mockFetch(f.routes);
    await renderApp(<ModelConnections />);
    const user = userEvent.setup();
    await fillAndSubmit(user);

    expect(await screen.findByTestId("model-test-result")).toHaveAttribute("data-code", "ok");
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.body).toMatchObject({
      provider: "openai",
      model: "gpt-4.1-mini",
      api_key: SECRET,
      base_url: null,
      make_default: true,
    });
    expect(screen.getByTestId("model-openai-gpt-4.1-mini")).toHaveTextContent("Default");
    expect(document.body.innerHTML).not.toContain(SECRET);
    expect(screen.getByTestId<HTMLInputElement>("model-key").value).toBe("");
    expect(screen.getByTestId("model-key")).toHaveAttribute("type", "password");
    // the key is not in any later response either: only the first call carried it
    expect(calls.filter((c) => JSON.stringify(c.body ?? "").includes(SECRET))).toHaveLength(1);
  });

  it("asks for the address only for a custom service", async () => {
    mockFetch(fixture().routes);
    await renderApp(<ModelConnections />);
    const user = userEvent.setup();
    await screen.findByTestId("model-provider");
    expect(screen.queryByTestId("model-base-url")).toBeNull();
    await user.selectOptions(screen.getByTestId("model-provider"), "custom");
    expect(screen.getByTestId("model-base-url")).toBeInTheDocument();
  });

  it("cannot be submitted without a model and a key", async () => {
    mockFetch(fixture().routes);
    await renderApp(<ModelConnections />);
    const user = userEvent.setup();
    expect(await screen.findByTestId("model-submit")).toBeDisabled();
    await user.type(screen.getByTestId("model-model"), "gpt-4.1-mini");
    expect(screen.getByTestId("model-submit")).toBeDisabled();
    await user.type(screen.getByTestId("model-key"), SECRET);
    expect(screen.getByTestId("model-submit")).toBeEnabled();
  });

  it("shows a translated reason when the gateway refuses the change", async () => {
    const f = fixture();
    f.state.putStatus = 502;
    mockFetch(f.routes);
    await renderApp(<ModelConnections />);
    await fillAndSubmit(userEvent.setup());
    expect(await screen.findByTestId("model-error")).toBeInTheDocument();
    expect(screen.getByTestId("model-error").textContent).not.toMatch(/model_gateway_failed/);
    // it stays in the password field so the user can retry, but is never text on the page
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it("explains a rejected key in plain words", async () => {
    mockFetch(fixture(listing(), { ok: false, code: "auth_failed" }).routes);
    await renderApp(<ModelConnections />);
    await fillAndSubmit(userEvent.setup());
    const result = await screen.findByTestId("model-test-result");
    expect(result).toHaveAttribute("data-code", "auth_failed");
    expect(result).toHaveTextContent(/refused the key/);
    expect(result).toHaveAttribute("role", "alert");
  });

  it("removes a connection after a confirmation", async () => {
    const f = fixture(
      listing({
        models: [
          {
            name: "openai-gpt-4.1-mini",
            provider: "openai",
            model: "gpt-4.1-mini",
            base_url: null,
            default: true,
          },
        ],
        default: "openai-gpt-4.1-mini",
      }),
    );
    const { calls } = mockFetch(f.routes);
    await renderApp(<ModelConnections />);
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("model-remove-openai-gpt-4.1-mini"));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.click(
      await screen
        .findByRole("button", { name: "Remove", hidden: false })
        .then(() => screen.getAllByRole("button", { name: "Remove" }).at(-1)!),
    );
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(await screen.findByTestId("models-empty")).toBeInTheDocument();
  });

  it("speaks French", async () => {
    mockFetch(fixture().routes);
    await renderApp(<ModelConnections />);
    await setLang("fr");
    expect(await screen.findByTestId("model-submit")).toHaveTextContent("Connecter et tester");
  });
});
