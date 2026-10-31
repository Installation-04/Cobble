import { api, requestText, type TextChunk } from "./client";
import type {
  ChatMessage,
  Folder,
  GlobalCostRow,
  Milestone,
  Plan,
  Project,
  ProjectCosts,
  Spec,
  Task,
  TaskDetail,
  TaskDiff,
  User,
} from "./types";
import type { Lang } from "../i18n";
import type { ThemeMode } from "../theme/store";

export const authApi = {
  me: () => api.get<User>("/auth/me", { skipUnauthorizedHandler: true }),
  login: (email: string, password: string) => api.post<User>("/auth/login", { email, password }),
  activate: (body: { token: string; email: string; password: string; lang?: Lang }) =>
    api.post<User>("/auth/activate", body),
  logout: () => api.post<void>("/auth/logout"),
  updateMe: (prefs: { lang?: Lang; theme?: ThemeMode }) => api.patch<User>("/auth/me", prefs),
};

export const foldersApi = {
  list: () => api.get<Folder[]>("/folders"),
  create: (name: string) => api.post<Folder>("/folders", { name }),
  rename: (id: string, name: string) => api.patch<Folder>(`/folders/${id}`, { name }),
  remove: (id: string) => api.delete(`/folders/${id}`),
};

export const projectsApi = {
  list: () => api.get<Project[]>("/projects"),
  create: (name: string, folderId: string | null) =>
    api.post<Project>("/projects", folderId ? { name, folder_id: folderId } : { name }),
  update: (id: string, body: { name?: string; folder_id?: string | null }) =>
    api.patch<Project>(`/projects/${id}`, body),
  remove: (id: string) => api.delete(`/projects/${id}`),
};

/** Interview, spec and plan (ADR 0005). Generation endpoints answer 202 and run in the worker. */
export const flowApi = {
  messages: (id: string) => api.get<ChatMessage[]>(`/projects/${id}/messages`),
  sendMessage: (id: string, content: string) =>
    api.post<{ message: ChatMessage }>(`/projects/${id}/messages`, { content }),
  spec: (id: string) => api.get<Spec>(`/projects/${id}/spec`),
  generateSpec: (id: string, feedback?: string) =>
    api.post<void>(`/projects/${id}/spec/generate`, feedback ? { feedback } : {}),
  approveSpec: (id: string) => api.post<Spec>(`/projects/${id}/spec/approve`),
  plan: (id: string) => api.get<Plan>(`/projects/${id}/plan`),
  generatePlan: (id: string, feedback?: string) =>
    api.post<void>(`/projects/${id}/plan/generate`, feedback ? { feedback } : {}),
  approvePlan: (id: string) => api.post<Plan>(`/projects/${id}/plan/approve`),
};

/** The answer of an action is either the object itself or wrapped under `key` (ADR 0007). */
export function unwrap<T>(value: unknown, key: string): T {
  if (value && typeof value === "object" && key in value) return (value as Record<string, T>)[key];
  return value as T;
}

/** Start building and the agents (ADR 0006 and 0007). */
export const buildApi = {
  start: (id: string) => api.post<void>(`/projects/${id}/start`),
  tasks: (id: string) => api.get<Task[]>(`/projects/${id}/tasks`),
  task: (id: string, ref: string) => api.get<TaskDetail>(`/projects/${id}/tasks/${ref}`),
  logs: (id: string, ref: string, offset: number): Promise<TextChunk> =>
    requestText(`/projects/${id}/tasks/${ref}/logs?offset=${offset}`),
  diff: (id: string, ref: string) => api.get<TaskDiff>(`/projects/${id}/tasks/${ref}/diff`),
  pause: (id: string, ref: string) => api.post<Task>(`/projects/${id}/tasks/${ref}/pause`),
  resume: (id: string, ref: string) => api.post<Task>(`/projects/${id}/tasks/${ref}/resume`),
  stop: (id: string, ref: string) => api.post<Task>(`/projects/${id}/tasks/${ref}/stop`),
  retry: (id: string, ref: string) => api.post<Task>(`/projects/${id}/tasks/${ref}/retry`),
};

/** Demo milestones: validate, comment, revert (ADR 0007). */
export const demoApi = {
  milestones: (id: string) => api.get<Milestone[]>(`/projects/${id}/milestones`),
  validate: (id: string, ref: string) =>
    api.post<unknown>(`/projects/${id}/milestones/${ref}/validate`),
  comment: (id: string, ref: string, content: string) =>
    api.post<unknown>(`/projects/${id}/milestones/${ref}/comments`, { content }),
  revert: (id: string, ref: string) =>
    api.post<unknown>(`/projects/${id}/milestones/${ref}/revert`),
};

export const costsApi = {
  project: (id: string) => api.get<ProjectCosts>(`/projects/${id}/costs`),
  all: () => api.get<GlobalCostRow[]>("/costs"),
};
