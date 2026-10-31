export type ThemeMode = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "cobble.theme";
export const THEME_MODES: readonly ThemeMode[] = ["system", "light", "dark"];

const DARK_QUERY = "(prefers-color-scheme: dark)";

type Listener = () => void;

let mode: ThemeMode = readStoredMode();
const listeners = new Set<Listener>();
let mediaQuery: MediaQueryList | null = null;

export function isThemeMode(value: unknown): value is ThemeMode {
  return typeof value === "string" && (THEME_MODES as readonly string[]).includes(value);
}

function readStoredMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (isThemeMode(stored)) return stored;
  } catch {
    /* storage unavailable */
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;
}

export function isDark(): boolean {
  return mode === "dark" || (mode === "system" && systemPrefersDark());
}

function apply(): void {
  document.documentElement.classList.toggle("dark", isDark());
  listeners.forEach((l) => l());
}

export function getThemeMode(): ThemeMode {
  return mode;
}

/** Set the theme: instant, no reload, persisted in localStorage. */
export function setThemeMode(next: ThemeMode): void {
  mode = next;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, next);
  } catch {
    /* storage unavailable */
  }
  apply();
}

/** Re-read storage, apply the class and follow the OS preference live. Returns a cleanup. */
export function initTheme(): () => void {
  mode = readStoredMode();
  apply();
  if (typeof window.matchMedia !== "function") return () => undefined;
  mediaQuery = window.matchMedia(DARK_QUERY);
  const onChange = () => {
    if (mode === "system") apply();
  };
  mediaQuery.addEventListener("change", onChange);
  const mq = mediaQuery;
  return () => mq.removeEventListener("change", onChange);
}

export function subscribeTheme(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Snapshot string for useSyncExternalStore: mode plus effective darkness. */
export function themeSnapshot(): string {
  return `${mode}:${isDark() ? "dark" : "light"}`;
}
