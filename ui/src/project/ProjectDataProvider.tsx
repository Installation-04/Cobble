import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError } from "../api/client";
import { flowApi } from "../api/endpoints";
import type { ChatMessage, Phase, Plan, Project, Spec } from "../api/types";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { useProjectStream, type JobFailure, type JobsInFlight } from "./useProjectStream";

export interface ProjectData {
  project: Project;
  phase: Phase;
  paused: boolean;
  loaded: boolean;
  loadError: unknown;
  messages: ChatMessage[];
  spec: Spec | null;
  plan: Plan | null;
  jobs: JobsInFlight;
  failure: JobFailure | null;
  clearFailure: () => void;
  sendMessage: (content: string) => Promise<void>;
  generateSpec: (feedback?: string) => Promise<void>;
  approveSpec: () => Promise<void>;
  generatePlan: (feedback?: string) => Promise<void>;
  approvePlan: () => Promise<void>;
}

const ProjectDataContext = createContext<ProjectData | null>(null);

/** Add or replace a message; a confirmed user message replaces its optimistic twin. */
export function mergeMessage(list: ChatMessage[], incoming: ChatMessage): ChatMessage[] {
  if (list.some((m) => m.id === incoming.id)) {
    return list.map((m) => (m.id === incoming.id ? incoming : m));
  }
  if (incoming.role === "user") {
    const twin = list.findIndex(
      (m) => m.pending && m.role === "user" && m.content === incoming.content,
    );
    if (twin >= 0) return list.map((m, i) => (i === twin ? incoming : m));
  }
  return [...list, incoming];
}

async function optional<T>(request: Promise<T>): Promise<T | null> {
  try {
    return await request;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

let optimisticCounter = 0;

export function ProjectDataProvider({
  project,
  children,
}: {
  project: Project;
  children: ReactNode;
}) {
  const { patchProject, reload } = useWorkspace();
  const projectId = project.id;
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [spec, setSpec] = useState<Spec | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<unknown>(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const loadMessages = useCallback(async () => {
    const server = await flowApi.messages(projectId);
    if (!alive.current) return;
    // Keep optimistic messages the server does not know yet.
    setMessages((prev) =>
      prev
        .filter(
          (m) => m.pending && !server.some((s) => s.role === "user" && s.content === m.content),
        )
        .reduce(mergeMessage, server),
    );
  }, [projectId]);
  const loadSpec = useCallback(async () => {
    const next = await optional(flowApi.spec(projectId));
    if (alive.current) setSpec(next);
  }, [projectId]);
  const loadPlan = useCallback(async () => {
    const next = await optional(flowApi.plan(projectId));
    if (alive.current) setPlan(next);
  }, [projectId]);

  const loadAll = useCallback(async () => {
    try {
      await Promise.all([loadMessages(), loadSpec(), loadPlan()]);
      if (alive.current) setLoadError(null);
    } catch (e) {
      if (alive.current) setLoadError(e);
    } finally {
      if (alive.current) setLoaded(true);
    }
  }, [loadMessages, loadSpec, loadPlan]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadAll();
  }, [loadAll]);

  const stream = useProjectStream(projectId, {
    onMessage: (message) => setMessages((prev) => mergeMessage(prev, message)),
    onSpecUpdated: () => void loadSpec().catch(() => undefined),
    onPlanUpdated: () => void loadPlan().catch(() => undefined),
    onPhaseChanged: (phase) => patchProject(projectId, { phase }),
    onResync: () => {
      void loadAll();
      void reload();
    },
  });
  const { markStarted, markStopped } = stream;

  const sendMessage = useCallback(
    async (content: string) => {
      const tempId = `pending-${++optimisticCounter}`;
      const optimistic: ChatMessage = {
        id: tempId,
        role: "user",
        content,
        created_at: new Date().toISOString(),
        pending: true,
      };
      setMessages((prev) => [...prev, optimistic]);
      markStarted("reply");
      try {
        const { message } = await flowApi.sendMessage(projectId, content);
        setMessages((prev) =>
          prev.some((m) => m.id === message.id)
            ? prev.filter((m) => m.id !== tempId)
            : mergeMessage(prev, message),
        );
      } catch (e) {
        setMessages((prev) => prev.filter((m) => m.id !== tempId));
        markStopped("reply");
        throw e;
      }
    },
    [projectId, markStarted, markStopped],
  );

  const generateSpec = useCallback(
    async (feedback?: string) => {
      markStarted("spec");
      try {
        await flowApi.generateSpec(projectId, feedback);
      } catch (e) {
        markStopped("spec");
        throw e;
      }
    },
    [projectId, markStarted, markStopped],
  );

  const approveSpec = useCallback(async () => {
    setSpec(await flowApi.approveSpec(projectId));
  }, [projectId]);

  const generatePlan = useCallback(
    async (feedback?: string) => {
      markStarted("plan");
      try {
        await flowApi.generatePlan(projectId, feedback);
      } catch (e) {
        markStopped("plan");
        throw e;
      }
    },
    [projectId, markStarted, markStopped],
  );

  const approvePlan = useCallback(async () => {
    setPlan(await flowApi.approvePlan(projectId));
    patchProject(projectId, { phase: "ready" });
  }, [projectId, patchProject]);

  const value = useMemo<ProjectData>(
    () => ({
      project,
      phase: project.phase,
      paused: project.status === "paused",
      loaded,
      loadError,
      messages,
      spec,
      plan,
      jobs: stream.jobs,
      failure: stream.failure,
      clearFailure: stream.clearFailure,
      sendMessage,
      generateSpec,
      approveSpec,
      generatePlan,
      approvePlan,
    }),
    [
      project,
      loaded,
      loadError,
      messages,
      spec,
      plan,
      stream.jobs,
      stream.failure,
      stream.clearFailure,
      sendMessage,
      generateSpec,
      approveSpec,
      generatePlan,
      approvePlan,
    ],
  );

  return <ProjectDataContext.Provider value={value}>{children}</ProjectDataContext.Provider>;
}

export function useProjectData(): ProjectData {
  const ctx = useContext(ProjectDataContext);
  if (!ctx) throw new Error("useProjectData must be used inside ProjectDataProvider");
  return ctx;
}
