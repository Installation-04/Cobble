import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../auth/AuthProvider";
import { setLang } from "../i18n";

export type Handler = (init: { method: string; body: unknown; headers: Headers }) => {
  status?: number;
  body?: unknown;
};

export interface FetchCall {
  method: string;
  path: string;
  body: unknown;
  headers: Headers;
}

/** Stub fetch with `"METHOD /path": handler` routes; unknown routes answer 404. */
export function mockFetch(routes: Record<string, Handler>): { calls: FetchCall[] } {
  const calls: FetchCall[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = (init.method ?? "GET").toUpperCase();
      const path = url.replace(/^\/api\/v1/, "");
      const headers = new Headers(init.headers);
      const body = typeof init.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ method, path, body, headers });
      const handler = routes[`${method} ${path}`];
      const out = handler
        ? handler({ method, body, headers })
        : { status: 404, body: { error: { code: "not_found", params: {} } } };
      const status = out.status ?? 200;
      return new Response(status === 204 ? null : JSON.stringify(out.body ?? {}), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return { calls };
}

export const ME = { id: "u1", email: "a@b.co", role: "admin", lang: "en", theme: "system" };

export async function renderApp(ui: ReactElement, route = "/") {
  await setLang("en");
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>,
  );
}
