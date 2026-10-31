import { useEffect, useRef, useState } from "react";
import { buildApi } from "../api/endpoints";

export const LOG_POLL_MS = 2000;

/**
 * Live log of a task. Reads the latest run's log in chunks (`?offset=`), appends them, and
 * while `running` asks again every 2 s. When the task leaves the running state the effect runs
 * one last time (to catch the tail) and does not schedule another poll.
 * `resetKey` changes with every new run: the log then starts over from offset 0.
 */
export function useTaskLog(projectId: string, ref: string, running: boolean, resetKey: string) {
  const [text, setText] = useState("");
  const [error, setError] = useState<unknown>(null);
  const offset = useRef(0);
  const lastKey = useRef(resetKey);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    if (lastKey.current !== resetKey) {
      // "" = the run list is not loaded yet: that is not a new run.
      const firstLoad = lastKey.current === "";
      lastKey.current = resetKey;
      if (!firstLoad) {
        offset.current = 0;
        setText("");
      }
    }

    const tick = async () => {
      try {
        const chunk = await buildApi.logs(projectId, ref, offset.current);
        if (cancelled) return;
        if (chunk.nextOffset !== null && chunk.nextOffset < offset.current) {
          // The log shrank (a new run replaced it): start over with what we received.
          setText(chunk.text);
        } else if (chunk.text) {
          setText((prev) => prev + chunk.text);
        }
        offset.current = chunk.nextOffset ?? offset.current + chunk.text.length;
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e);
      }
      if (!cancelled && running) timer = setTimeout(() => void tick(), LOG_POLL_MS);
    };
    void tick();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [projectId, ref, running, resetKey]);

  return { text, error };
}
