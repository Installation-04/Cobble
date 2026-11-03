import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../api/client";
import type { ModuleOperationError, ModuleStepEvent } from "../api/types";

export interface ModuleStreamHandlers {
  /** One step of an install or removal. */
  onStep?: (event: ModuleStepEvent) => void;
  /** `module.operation`: the operation started, or ended (`done` / `failed` with its error). */
  onOperation?: (event: {
    operation_id: string;
    state: "running" | "done" | "failed";
    error: ModuleOperationError | null;
  }) => void;
  /** The connection came back after a drop: events may have been missed, read the state again. */
  onResync?: () => void;
}

function parse(event: Event): Record<string, unknown> | null {
  try {
    const data: unknown = JSON.parse((event as MessageEvent<string>).data);
    return data && typeof data === "object" ? (data as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/**
 * Live progress of module operations (SSE). EventSource reconnects by itself and resumes with
 * Last-Event-ID; a stream opened without an id only delivers new events, so on every re-open
 * after the first one the owner is asked to read the state again (the end of an operation can
 * never be lost).
 */
export function useModuleStream(handlers: ModuleStreamHandlers, enabled = true): boolean {
  const [connected, setConnected] = useState(false);
  const handlersRef = useRef(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  });

  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    const source = new EventSource(`${API_BASE}/modules/stream`);
    let opened = false;

    source.addEventListener("open", () => {
      setConnected(true);
      if (opened) handlersRef.current.onResync?.();
      opened = true;
    });
    source.addEventListener("error", () => setConnected(false));
    source.addEventListener("module.step", (event) => {
      const data = parse(event);
      if (!data || typeof data.module !== "string") return;
      handlersRef.current.onStep?.({
        operation_id: typeof data.operation_id === "string" ? data.operation_id : null,
        module: data.module,
        kind: String(data.kind ?? ""),
        step: typeof data.step === "string" ? data.step : null,
        ok: data.ok !== false,
        code: typeof data.code === "string" ? data.code : null,
      });
    });
    source.addEventListener("module.operation", (event) => {
      const data = parse(event);
      if (!data || typeof data.operation_id !== "string") return;
      const state = data.state;
      if (state !== "running" && state !== "done" && state !== "failed") return;
      handlersRef.current.onOperation?.({
        operation_id: data.operation_id,
        state,
        error: (data.error as ModuleOperationError | null | undefined) ?? null,
      });
    });

    return () => {
      source.close();
      setConnected(false);
    };
  }, [enabled]);

  return connected;
}
