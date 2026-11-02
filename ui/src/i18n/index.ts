import i18n from "i18next";
import { initReactI18next } from "react-i18next";

export const LANGS = ["fr", "en"] as const;
export type Lang = (typeof LANGS)[number];
export const LANG_STORAGE_KEY = "cobble.lang";
export const NAMESPACES = [
  "common",
  "auth",
  "shell",
  "settings",
  "errors",
  "chat",
  "spec",
  "plan",
  "agents",
  "demo",
  "costs",
  "store",
  "models",
  "welcome",
] as const;

const modules = import.meta.glob("../locales/*/*.json", {
  eager: true,
  import: "default",
}) as Record<string, Record<string, unknown>>;

const resources: Record<string, Record<string, Record<string, unknown>>> = {};
for (const [path, data] of Object.entries(modules)) {
  const m = /locales\/(\w+)\/(\w+)\.json$/.exec(path);
  if (!m) continue;
  (resources[m[1]] ??= {})[m[2]] = data;
}

export function isLang(value: unknown): value is Lang {
  return value === "fr" || value === "en";
}

/** Saved choice first, then the browser language, then English. */
export function detectLang(): Lang {
  try {
    const stored = localStorage.getItem(LANG_STORAGE_KEY);
    if (isLang(stored)) return stored;
  } catch {
    /* storage unavailable */
  }
  const nav = typeof navigator !== "undefined" ? navigator.language : "";
  return nav.toLowerCase().startsWith("fr") ? "fr" : "en";
}

/** Switch language instantly (no reload) and persist it locally. */
export async function setLang(lang: Lang): Promise<void> {
  try {
    localStorage.setItem(LANG_STORAGE_KEY, lang);
  } catch {
    /* storage unavailable */
  }
  await i18n.changeLanguage(lang);
}

export function currentLang(): Lang {
  return isLang(i18n.language) ? i18n.language : "en";
}

i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng;
});

void i18n.use(initReactI18next).init({
  resources,
  lng: detectLang(),
  fallbackLng: "en",
  supportedLngs: [...LANGS],
  ns: [...NAMESPACES],
  defaultNS: "common",
  interpolation: { escapeValue: false },
  initAsync: false,
});
document.documentElement.lang = i18n.language;

export default i18n;
