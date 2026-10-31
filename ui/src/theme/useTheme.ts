import { useSyncExternalStore } from "react";
import { useAuth } from "../auth/AuthProvider";
import { subscribeTheme, themeSnapshot, type ThemeMode } from "./store";

export function useTheme(): {
  mode: ThemeMode;
  dark: boolean;
  setMode: (mode: ThemeMode) => void;
  toggle: () => void;
} {
  const snap = useSyncExternalStore(subscribeTheme, themeSnapshot);
  const { savePrefs } = useAuth();
  const [mode, effective] = snap.split(":") as [ThemeMode, "light" | "dark"];
  const dark = effective === "dark";
  return {
    mode,
    dark,
    setMode: (next) => void savePrefs({ theme: next }),
    toggle: () => void savePrefs({ theme: dark ? "light" : "dark" }),
  };
}
