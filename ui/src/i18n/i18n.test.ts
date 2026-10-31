import { describe, expect, it, vi } from "vitest";
import i18n, { detectLang, LANG_STORAGE_KEY, setLang } from "./index";

describe("i18n", () => {
  it("switches language instantly, persists it and updates <html lang>", async () => {
    await setLang("fr");
    expect(i18n.t("shell:sidebar.newProject")).toBe("Nouveau projet");
    expect(document.documentElement.lang).toBe("fr");
    expect(localStorage.getItem(LANG_STORAGE_KEY)).toBe("fr");

    await setLang("en");
    expect(i18n.t("shell:sidebar.newProject")).toBe("New project");
    expect(document.documentElement.lang).toBe("en");
  });

  it("detects the saved language first, then the browser language", () => {
    localStorage.setItem(LANG_STORAGE_KEY, "fr");
    expect(detectLang()).toBe("fr");
    localStorage.clear();
    const nav = vi.spyOn(navigator, "language", "get");
    nav.mockReturnValue("fr-CA");
    expect(detectLang()).toBe("fr");
    nav.mockReturnValue("de-DE");
    expect(detectLang()).toBe("en");
    nav.mockRestore();
  });

  it("translates every known API error code in both languages", async () => {
    const codes = [
      "invalid_credentials",
      "unauthenticated",
      "activation_invalid",
      "activation_expired",
      "already_initialized",
      "too_many_attempts",
      "csrf_failed",
      "not_found",
      "validation_error",
      "unknown",
      "network",
    ];
    for (const lang of ["fr", "en"] as const) {
      await setLang(lang);
      for (const code of codes) {
        expect(i18n.exists(`errors:${code}`), `${lang} ${code}`).toBe(true);
      }
    }
  });
});
