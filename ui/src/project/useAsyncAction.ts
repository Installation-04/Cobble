import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { errorMessage } from "../api/errors";

/** Run an async action once at a time and keep its translated error message. */
export function useAsyncAction() {
  const { t } = useTranslation("errors");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const run = useCallback(
    async (action: () => Promise<void>): Promise<boolean> => {
      setBusy(true);
      setError(null);
      try {
        await action();
        return true;
      } catch (e) {
        if (alive.current) setError(errorMessage(t, e));
        return false;
      } finally {
        if (alive.current) setBusy(false);
      }
    },
    [t],
  );
  return { busy, error, run, clearError: () => setError(null) };
}
