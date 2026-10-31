import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ME, mockFetch, renderApp } from "../test/utils";
import { ActivatePage } from "./ActivatePage";

afterEach(() => vi.unstubAllGlobals());

const ui = (
  <Routes>
    <Route path="/activate" element={<ActivatePage />} />
    <Route path="/" element={<p data-testid="home-reached" />} />
  </Routes>
);
const anonymous = () => ({ status: 401, body: { error: { code: "unauthenticated", params: {} } } });

describe("ActivatePage", () => {
  it("activates with token, email, password and the chosen language", async () => {
    const { calls } = mockFetch({
      "GET /auth/me": anonymous,
      "POST /auth/activate": () => ({ status: 201, body: { ...ME, lang: "fr" } }),
    });
    await renderApp(ui, "/activate?token=abc123");
    await userEvent.type(await screen.findByTestId("activate-email"), "admin@example.com");
    await userEvent.type(screen.getByTestId("activate-password"), "a-long-enough-password");
    await userEvent.selectOptions(screen.getByTestId("activate-lang"), "fr");
    // The UI language switched immediately, without any request.
    expect(screen.getByTestId("activate-submit")).toHaveTextContent("Créer le compte");
    await userEvent.click(screen.getByTestId("activate-submit"));
    await screen.findByTestId("home-reached");

    const call = calls.find((c) => c.path === "/auth/activate")!;
    expect(call.body).toEqual({
      token: "abc123",
      email: "admin@example.com",
      password: "a-long-enough-password",
      lang: "fr",
    });
    expect(call.headers.get("X-Requested-With")).toBe("cobble");
  });

  it("rejects a short password locally without calling the API", async () => {
    const { calls } = mockFetch({ "GET /auth/me": anonymous });
    await renderApp(ui, "/activate?token=abc123");
    await userEvent.type(await screen.findByTestId("activate-email"), "admin@example.com");
    await userEvent.type(screen.getByTestId("activate-password"), "short");
    // bypass native minlength validation by submitting the form directly
    screen.getByTestId("activate-form").dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
    expect(await screen.findByTestId("activate-error")).toHaveTextContent("at least 10");
    expect(calls.some((c) => c.path === "/auth/activate")).toBe(false);
  });

  it("shows the translated server error for an expired link", async () => {
    mockFetch({
      "GET /auth/me": anonymous,
      "POST /auth/activate": () => ({
        status: 410,
        body: { error: { code: "activation_expired", params: {} } },
      }),
    });
    await renderApp(ui, "/activate?token=old");
    await userEvent.type(await screen.findByTestId("activate-email"), "admin@example.com");
    await userEvent.type(screen.getByTestId("activate-password"), "a-long-enough-password");
    await userEvent.click(screen.getByTestId("activate-submit"));
    await waitFor(() =>
      expect(screen.getByTestId("activate-error")).toHaveTextContent("has expired"),
    );
  });

  it("explains a missing token and disables submit", async () => {
    mockFetch({ "GET /auth/me": anonymous });
    await renderApp(ui, "/activate");
    expect(await screen.findByTestId("activate-error")).toHaveTextContent("incomplete");
    expect(screen.getByTestId("activate-submit")).toBeDisabled();
  });
});
