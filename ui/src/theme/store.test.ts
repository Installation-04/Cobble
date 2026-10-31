import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getThemeMode,
  initTheme,
  isDark,
  setThemeMode,
  subscribeTheme,
  THEME_STORAGE_KEY,
} from "./store";

type Listener = () => void;

function mockMatchMedia(initial: boolean) {
  let matches = initial;
  const listeners = new Set<Listener>();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      get matches() {
        return matches;
      },
      addEventListener: (_: string, l: Listener) => listeners.add(l),
      removeEventListener: (_: string, l: Listener) => listeners.delete(l),
    })),
  );
  return {
    set(next: boolean) {
      matches = next;
      listeners.forEach((l) => l());
    },
    listenerCount: () => listeners.size,
  };
}

const html = () => document.documentElement;

describe("theme store", () => {
  let cleanup: () => void = () => undefined;
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });
  beforeEach(() => {
    cleanup = () => undefined;
  });

  it("defaults to system and follows the OS preference", () => {
    mockMatchMedia(true);
    cleanup = initTheme();
    expect(getThemeMode()).toBe("system");
    expect(html()).toHaveClass("dark");
  });

  it("applies and persists explicit light and dark modes without reload", () => {
    mockMatchMedia(true);
    cleanup = initTheme();
    setThemeMode("light");
    expect(html()).not.toHaveClass("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    setThemeMode("dark");
    expect(html()).toHaveClass("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(isDark()).toBe(true);
  });

  it("reacts live to a matchMedia change in system mode only", () => {
    const media = mockMatchMedia(false);
    cleanup = initTheme();
    expect(html()).not.toHaveClass("dark");
    media.set(true);
    expect(html()).toHaveClass("dark");
    media.set(false);
    expect(html()).not.toHaveClass("dark");

    setThemeMode("light");
    media.set(true);
    expect(html()).not.toHaveClass("dark");
  });

  it("restores the saved mode on init and stops listening on cleanup", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "dark");
    const media = mockMatchMedia(false);
    cleanup = initTheme();
    expect(getThemeMode()).toBe("dark");
    expect(html()).toHaveClass("dark");
    expect(media.listenerCount()).toBe(1);
    cleanup();
    expect(media.listenerCount()).toBe(0);
  });

  it("ignores an invalid stored value", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "purple");
    mockMatchMedia(false);
    cleanup = initTheme();
    expect(getThemeMode()).toBe("system");
  });

  it("notifies subscribers", () => {
    mockMatchMedia(false);
    cleanup = initTheme();
    const spy = vi.fn();
    const off = subscribeTheme(spy);
    setThemeMode("dark");
    expect(spy).toHaveBeenCalledTimes(1);
    off();
    setThemeMode("light");
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
