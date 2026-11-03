import { useCallback, useEffect, useRef, useState } from "react";
import { modulesApi } from "../api/endpoints";
import { ApiError } from "../api/client";
import type {
  ModuleAction,
  ModuleOperation,
  ModuleOperationError,
  ModuleOperationRequest,
  ModulePlan,
  ModuleStepEvent,
} from "../api/types";

export type Stage =
  "idle" | "planning" | "choose" | "confirm" | "preview" | "running" | "done" | "failed";

export interface Flow {
  stage: Stage;
  action: ModuleAction | null;
  /** What the user clicked on: a module, or a starter pack (then `pack` is its id too). */
  target: string | null;
  pack: string | null;
  plan: ModulePlan | null;
  /** `module_needs_choice`: the capability to settle and the modules that can provide it. */
  choice: { capability: string; candidates: string[] } | null;
  /** `module_needs_confirmation`: what else would be removed. */
  cascade: string[];
  operationId: string | null;
  steps: ModuleStepEvent[];
  /** A refusal or a transport error (translated by the view). */
  error: unknown;
  /** The failure of a running operation. */
  failure: ModuleOperationError | null;
}

const IDLE: Flow = {
  stage: "idle",
  action: null,
  target: null,
  pack: null,
  plan: null,
  choice: null,
  cascade: [],
  operationId: null,
  steps: [],
  error: null,
  failure: null,
};

/** How often a running operation is read, whatever the stream says. */
export const POLL_MS = 3000;

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/**
 * The install / removal flow: plan first (the user sees what will happen, chooses between several
 * providers, confirms a cascade), then run it and follow it. Progress arrives on the stream; the
 * operation is also read every few seconds, so a dropped stream can never hide its end.
 */
export function useModuleOperation(onFinished: () => void, pollMs: number = POLL_MS) {
  const [flow, setFlow] = useState<Flow>(IDLE);
  const request = useRef<ModuleOperationRequest | null>(null);
  const flowRef = useRef(flow);
  const onFinishedRef = useRef(onFinished);
  useEffect(() => {
    flowRef.current = flow;
    onFinishedRef.current = onFinished;
  });

  const plan = useCallback(async () => {
    const body = request.current;
    if (!body) return;
    setFlow((f) => ({ ...f, stage: "planning", error: null, choice: null, cascade: [] }));
    try {
      const result = await modulesApi.plan(body);
      setFlow((f) => ({ ...f, stage: result.steps.length > 0 ? "preview" : "done", plan: result }));
      if (result.steps.length === 0) onFinishedRef.current();
    } catch (error) {
      if (error instanceof ApiError && error.code === "module_needs_choice") {
        setFlow((f) => ({
          ...f,
          stage: "choose",
          choice: {
            capability: String(error.params.capability ?? ""),
            candidates: strings(error.params.candidates),
          },
        }));
      } else if (error instanceof ApiError && error.code === "module_needs_confirmation") {
        setFlow((f) => ({ ...f, stage: "confirm", cascade: strings(error.params.cascade) }));
      } else {
        setFlow((f) => ({ ...f, stage: "failed", error }));
      }
    }
  }, []);

  const begin = useCallback(
    (action: ModuleAction, modules: string[], pack: string | null = null) => {
      request.current = { action, modules, choices: {}, confirm_cascade: false };
      setFlow({ ...IDLE, action, target: pack ?? modules[0] ?? null, pack });
      void plan();
    },
    [plan],
  );

  const choose = useCallback(
    (capability: string, module: string) => {
      if (!request.current) return;
      request.current = {
        ...request.current,
        choices: { ...request.current.choices, [capability]: module },
      };
      void plan();
    },
    [plan],
  );

  const confirmCascade = useCallback(() => {
    if (!request.current) return;
    request.current = { ...request.current, confirm_cascade: true };
    void plan();
  }, [plan]);

  const start = useCallback(async () => {
    const body = request.current;
    if (!body) return;
    setFlow((f) => ({ ...f, stage: "running", steps: [], error: null, failure: null }));
    try {
      const { operation_id: operationId } = await modulesApi.start(body);
      setFlow((f) => ({ ...f, operationId }));
    } catch (error) {
      setFlow((f) => ({ ...f, stage: "failed", error }));
    }
  }, []);

  const finish = useCallback((state: "done" | "failed", failure: ModuleOperationError | null) => {
    if (flowRef.current.stage !== "running") return;
    setFlow((f) => ({ ...f, stage: state, failure }));
    onFinishedRef.current();
  }, []);

  const reset = useCallback(() => {
    request.current = null;
    setFlow(IDLE);
  }, []);

  // Stream events for the operation being followed.
  const onStep = useCallback((event: ModuleStepEvent) => {
    const current = flowRef.current;
    if (current.stage !== "running" || event.operation_id !== current.operationId) return;
    setFlow((f) => ({ ...f, steps: [...f.steps, event] }));
  }, []);
  const onOperation = useCallback(
    (event: {
      operation_id: string;
      state: ModuleOperation["state"];
      error: ModuleOperationError | null;
    }) => {
      if (event.operation_id !== flowRef.current.operationId || event.state === "running") return;
      finish(event.state, event.error);
    },
    [finish],
  );

  const read = useCallback(async () => {
    const id = flowRef.current.operationId;
    if (!id || flowRef.current.stage !== "running") return;
    try {
      const operation = await modulesApi.operation(id);
      if (operation.state !== "running") finish(operation.state, operation.error);
    } catch {
      // the manager may restart in the middle: keep following, the next read tries again
    }
  }, [finish]);

  const { stage, operationId } = flow;
  useEffect(() => {
    if (stage !== "running" || !operationId) return;
    void read();
    const timer = setInterval(() => void read(), pollMs);
    return () => clearInterval(timer);
  }, [stage, operationId, read, pollMs]);

  return { flow, begin, choose, confirmCascade, start, reset, onStep, onOperation, resync: read };
}
