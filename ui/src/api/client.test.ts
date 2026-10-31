import { afterEach, describe, expect, it, vi } from "vitest";
import { setLang } from "../i18n";
import i18n from "../i18n";
import { mockFetch } from "../test/utils";
import { api, ApiError, NetworkError, setUnauthorizedHandler } from "./client";
import { errorMessage } from "./errors";

afterEach(() => {
  setUnauthorizedHandler(null);
  vi.unstubAllGlobals();
});

describe("api client", () => {
  it("sends X-Requested-With on unsafe methods only, same-origin", async () => {
    const { calls } = mockFetch({
      "GET /folders": () => ({ body: [] }),
      "POST /folders": () => ({ status: 201, body: { id: "f" } }),
      "PATCH /folders/f": () => ({ body: {} }),
      "DELETE /folders/f": () => ({ status: 204 }),
    });
    await api.get("/folders");
    await api.post("/folders", { name: "x" });
    await api.patch("/folders/f", { name: "y" });
    await expect(api.delete("/folders/f")).resolves.toBeUndefined();

    const byMethod = Object.fromEntries(calls.map((c) => [c.method, c]));
    expect(byMethod.GET.headers.get("X-Requested-With")).toBeNull();
    for (const m of ["POST", "PATCH", "DELETE"]) {
      expect(byMethod[m].headers.get("X-Requested-With")).toBe("cobble");
    }
    expect(byMethod.POST.body).toEqual({ name: "x" });
    expect(vi.mocked(fetch).mock.calls[0][1]).toMatchObject({ credentials: "same-origin" });
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/v1/folders");
  });

  it("parses the error format into a typed ApiError", async () => {
    mockFetch({
      "POST /auth/login": () => ({
        status: 429,
        body: { error: { code: "too_many_attempts", params: { retry: 5 } } },
      }),
    });
    const err = await api.post("/auth/login", {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 429, code: "too_many_attempts", params: { retry: 5 } });
  });

  it("falls back to an unknown code on a non-JSON error and maps network failures", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>", { status: 502 })));
    await expect(api.get("/x")).rejects.toMatchObject({ status: 502, code: "unknown" });
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("offline"))));
    await expect(api.get("/x")).rejects.toBeInstanceOf(NetworkError);
  });

  it("calls the unauthorized handler on 401 except for bad credentials", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch({
      "GET /folders": () => ({ status: 401, body: { error: { code: "unauthenticated" } } }),
      "POST /auth/login": () => ({ status: 401, body: { error: { code: "invalid_credentials" } } }),
    });
    await expect(api.get("/folders")).rejects.toMatchObject({ code: "unauthenticated" });
    expect(handler).toHaveBeenCalledTimes(1);
    await expect(api.post("/auth/login", {})).rejects.toMatchObject({ code: "invalid_credentials" });
    expect(handler).toHaveBeenCalledTimes(1);
    await expect(api.get("/folders", { skipUnauthorizedHandler: true })).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(handler).toHaveBeenCalledTimes(1);
  });
});

describe("errorMessage", () => {
  it("maps codes to translated messages in the active language", async () => {
    await setLang("fr");
    const t = i18n.t.bind(i18n);
    expect(errorMessage(t, new ApiError(401, "invalid_credentials"))).toBe(
      "Courriel ou mot de passe incorrect.",
    );
    expect(
      errorMessage(t, new ApiError(422, "validation_error", { fields: ["email", "name"] })),
    ).toContain("email, name");
    expect(errorMessage(t, new NetworkError())).toBe(i18n.t("errors:network"));
    expect(errorMessage(t, new ApiError(500, "something_else"))).toBe(i18n.t("errors:unknown"));
    expect(errorMessage(t, new Error("boom"))).toBe(i18n.t("errors:unknown"));
    await setLang("en");
    expect(errorMessage(t, new ApiError(404, "not_found"))).toBe("This item no longer exists.");
  });
});
