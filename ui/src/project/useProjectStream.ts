import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "../api/client";
import type { ChatMessage, JobKind, Phase } from "../api/types";

export interface JobFailure {
  kind: JobKind;
  code: string;
}

export type JobsInFlight = Record<JobKind, boolean>;

const NO_JOBS: JobsInFlight = { reply: false, spec: false, plan: false };

export interface StreamHandlers {
  onMessage?: (message: ChatMessage) => void;
  onSpecUpdated?: (version: number) => void;
  onPlanUpdated?: (version: number) => void;
  onPhaseChanged?: (phase: Phase) => void;
  /** The connection came back after a drop: refetch everything that may have changed. */
  onResync?: () => void;
}

const JOB_KINDS: readonly JobKind[] = ["reply", "spec", "plan"];

function isKind(value: unknown): value is JobKind {
  return typeof value === "string" && (JOB_KINDS as readonly string[]).includes(value);
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
 * Live events of a project (SSE, ADR 0005). EventSource reconnects by itself and resumes with
 * Last-Event-ID; on every re-open after the first one we also ask the owner to refetch, and we
 * reset the in-flight jobs (the replayed events rebuild them) so no spinner can stay stuck.
 */
export function useProjectStream(projectId: string | undefined, handlers: StreamHandlers) {
  const [jobs, setJobs] = useState<JobsInFlight>(NO_JOBS);
  const [failure, setFailure] = useState<JobFailure | null>(null);
  const [connected, setConnected] = useState(false);
  const handlersRef = useRef(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  });

  const setJob = useCallback((kind: JobKind, running: boolean) => {
    setJobs((prev) => (prev[kind] === running ? prev : { ...prev, [kind]: running }));
  }, []);

  useEffect(() => {
    if (!projectId || typeof EventSource === "undefined") return;
    const source = new EventSource(`${API_BASE}/projects/${projectId}/stream`);
    let opened = false;

    const on = (name: string, listener: (data: Record<string, unknown>) => void) => {
      source.addEventListener(name, (event) => {
        const data = parse(event);
        if (data) listener(data);
      });
    };

    source.addEventListener("open", () => {
      setConnected(true);
      if (opened) {
        setJobs(NO_JOBS);
        handlersRef.current.onResync?.();
      }
      opened = true;
    });
    source.addEventListener("error", () => setConnected(false));

    on("message.created", (data) => {
      const message = data.message as ChatMessage | undefined;
      if (!message) return;
      if (message.role === "assistant") setJob("reply", false);
      handlersRef.current.onMessage?.(message);
    });
    on("spec.updated", (data) => {
      setJob("spec", false);
      handlersRef.current.onSpecUpdated?.(Number(data.version));
    });
    on("plan.updated", (data) => {
      setJob("plan", false);
      handlersRef.current.onPlanUpdated?.(Number(data.version));
    });
    on("phase.changed", (data) => {
      handlersRef.current.onPhaseChanged?.(data.phase as Phase);
    });
    on("job.started", (data) => {
      if (!isKind(data.kind)) return;
      const kind = data.kind;
      setJob(kind, true);
      setFailure((prev) => (prev?.kind === kind ? null : prev));
    });
    on("job.failed", (data) => {
      if (!isKind(data.kind)) return;
      setJob(data.kind, false);
      setFailure({ kind: data.kind, code: String(data.code ?? "unknown") });
    });

    return () => {
      source.close();
      setConnected(false);
    };
  }, [projectId, setJob]);

  const markStarted = useCallback(
    (kind: JobKind) => {
      setJob(kind, true);
      setFailure((prev) => (prev?.kind === kind ? null : prev));
    },
    [setJob],
  );
  const markStopped = useCallback((kind: JobKind) => setJob(kind, false), [setJob]);
  const clearFailure = useCallback(() => setFailure(null), []);

  return { jobs, failure, connected, markStarted, markStopped, clearFailure };
}
