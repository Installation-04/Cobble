import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ME, mockFetch, renderApp } from "../test/utils";
import { LoginPage } from "./LoginPage";

afterEach(() => vi.unstubAllGlobals());

function ui() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<p data-testid="home-reached" />} />
    </Routes>
  );
}

const anonymous = () => ({ status: 401, body: { error: { code: "unauthenticated", params: {} } } });

describe("LoginPage", () => {
  it("shows a translated error on bad credentials and stays on the page", async () => {
    mockFetch({
      "GET /auth/me": anonymous,
      "POST /auth/login": () => ({
        status: 401,
        body: { error: { code: "invalid_credentials", params: {} } },
      }),
    });
    await renderApp(ui(), "/login");
    await userEvent.type(await screen.findByTestId("login-email"), "a@b.co");
    await userEvent.type(screen.getByTestId("login-password"), "wrong-password");
    await userEvent.click(screen.getByTestId("login-submit"));
    expect(await screen.findByTestId("login-error")).toHaveTextContent(
      "Incorrect email or password.",
    );
    expect(screen.queryByTestId("home-reached")).toBeNull();
  });

  it("logs in, sends the credentials with the CSRF header and adopts the saved prefs", async () => {
    const { calls } = mockFetch({
      "GET /auth/me": anonymous,
      "POST /auth/login": () => ({ body: { ...ME, lang: "fr", theme: "dark" } }),
    });
    await renderApp(ui(), "/login");
    await userEvent.type(await screen.findByTestId("login-email"), "a@b.co");
    await userEvent.type(screen.getByTestId("login-password"), "correct-horse-battery");
    await userEvent.click(screen.getByTestId("login-submit"));
    await screen.findByTestId("home-reached");

    const login = calls.find((c) => c.path === "/auth/login")!;
    expect(login.body).toEqual({ email: "a@b.co", password: "correct-horse-battery" });
    expect(login.headers.get("X-Requested-With")).toBe("cobble");
    await waitFor(() => expect(document.documentElement.lang).toBe("fr"));
    expect(document.documentElement).toHaveClass("dark");
  });
});
