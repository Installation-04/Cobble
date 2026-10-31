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
import { buildApi, costsApi, demoApi, flowApi } from "../api/endpoints";
import type {
  ChatMessage,
  Milestone,
  Phase,
  Plan,
  Project,
  ProjectCosts,
  Spec,
  Task,
} from "../api/types";
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
  /** Build phase (ADR 0006/0007): tasks, demo milestones and costs, kept live by the stream. */
  tasks: Task[];
  milestones: Milestone[];
  costs: ProjectCosts | null;
  /** Last error that prevented loading tasks, milestones or costs (null when fine). */
  buildError: unknown;
  startBuilding: () => Promise<void>;
  reloadTasks: () => Promise<void>;
  reloadMilestones: () => Promise<void>;
  reloadCosts: () => Promise<void>;
  /** Merge a task returned by an action (e.g. the one created by a demo comment). */
  upsertTask: (task: Task) => void;
}

const COSTS_REFRESH_MS = 1500;

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

type BuildResult<T> = { ok: true; value: T | null } | { ok: false; error: unknown };

async function settle<T>(request: Promise<T>): Promise<BuildResult<T>> {
  try {
    return { ok: true, value: await optional(request) };
  } catch (error) {
    return { ok: false, error };
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
  const [tasks, setTasks] = useState<Task[]>([]);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [costs, setCosts] = useState<ProjectCosts | null>(null);
  const [buildError, setBuildError] = useState<unknown>(null);
  const alive = useRef(true);
  const statusRef = useRef(project.status);
  useEffect(() => {
    statusRef.current = project.status;
  });
  const tasksRef = useRef<Task[]>([]);
  useEffect(() => {
    tasksRef.current = tasks;
  });
  const costsTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (costsTimer.current) clearTimeout(costsTimer.current);
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

  /** A build resource: a 404 means "nothing yet", any other error is kept for the tabs. */
  const applyBuild = useCallback((result: BuildResult<unknown>, apply: (v: never) => void) => {
    if (!alive.current) return;
    if (result.ok) {
      apply(result.value as never);
      setBuildError(null);
    } else setBuildError(result.error);
  }, []);
  const reloadTasks = useCallback(
    () =>
      settle(buildApi.tasks(projectId)).then((r) =>
        applyBuild(r, (v: Task[] | null) => setTasks(v ?? [])),
      ),
    [applyBuild, projectId],
  );
  const reloadMilestones = useCallback(
    () =>
      settle(demoApi.milestones(projectId)).then((r) =>
        applyBuild(r, (v: Milestone[] | null) => setMilestones(v ?? [])),
      ),
    [applyBuild, projectId],
  );
  const reloadCosts = useCallback(
    () =>
      settle(costsApi.project(projectId)).then((r) =>
        applyBuild(r, (v: ProjectCosts | null) => {
          setCosts(v);
          // The router pauses a project that reaches its budget: pick the new status up.
          const reached = v?.budget_usd != null && Number(v.spent_usd) >= Number(v.budget_usd);
          if (reached && statusRef.current === "active") void reload();
        }),
      ),
    [applyBuild, projectId, reload],
  );
  const loadBuildAll = useCallback(
    () => Promise.all([reloadTasks(), reloadMilestones(), reloadCosts()]).then(() => undefined),
    [reloadTasks, reloadMilestones, reloadCosts],
  );

  const scheduleCostsRefresh = useCallback(() => {
    if (costsTimer.current) return;
    costsTimer.current = setTimeout(() => {
      costsTimer.current = null;
      void reloadCosts();
    }, COSTS_REFRESH_MS);
  }, [reloadCosts]);

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

  useEffect(() => {
    void loadBuildAll();
  }, [loadBuildAll]);

  const stream = useProjectStream(projectId, {
    onMessage: (message) => setMessages((prev) => mergeMessage(prev, message)),
    onSpecUpdated: () => void loadSpec().catch(() => undefined),
    onPlanUpdated: () => void loadPlan().catch(() => undefined),
    onPhaseChanged: (phase) => {
      patchProject(projectId, { phase });
      if (phase === "building" || phase === "done") {
        void reloadTasks();
        void reloadMilestones();
      }
    },
    onTaskUpdated: ({ ref, state, attempts }) => {
      setTasks((prev) =>
        prev.map((task) =>
          task.ref === ref ? { ...task, state, attempts: attempts ?? task.attempts } : task,
        ),
      );
      // A task we have never seen (a new comment task, a fresh plan): fetch the list.
      if (!tasksRef.current.some((task) => task.ref === ref)) void reloadTasks();
      scheduleCostsRefresh();
    },
    onMilestoneUpdated: ({ ref, status }) => {
      setMilestones((prev) => prev.map((m) => (m.ref === ref ? { ...m, status } : m)));
      // preview_path and built_at come with the full record.
      void reloadMilestones();
    },
    onBuildEvent: () => {
      void reloadTasks();
      void reloadMilestones();
    },
    onResync: () => {
      void loadAll();
      void loadBuildAll();
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

  const startBuilding = useCallback(async () => {
    markStarted("start");
    try {
      await buildApi.start(projectId);
    } catch (e) {
      markStopped("start");
      throw e;
    }
  }, [projectId, markStarted, markStopped]);

  const upsertTask = useCallback((task: Task) => {
    setTasks((prev) =>
      prev.some((t) => t.ref === task.ref)
        ? prev.map((t) => (t.ref === task.ref ? task : t))
        : [...prev, task],
    );
  }, []);

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
      tasks,
      milestones,
      costs,
      buildError,
      startBuilding,
      reloadTasks,
      reloadMilestones,
      reloadCosts,
      upsertTask,
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
      tasks,
      milestones,
      costs,
      buildError,
      startBuilding,
      reloadTasks,
      reloadMilestones,
      reloadCosts,
      upsertTask,
    ],
  );

  return <ProjectDataContext.Provider value={value}>{children}</ProjectDataContext.Provider>;
}

export function useProjectData(): ProjectData {
  const ctx = useContext(ProjectDataContext);
  if (!ctx) throw new Error("useProjectData must be used inside ProjectDataProvider");
  return ctx;
}
