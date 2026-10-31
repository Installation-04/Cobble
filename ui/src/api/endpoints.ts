import { api } from "./client";
import type { ChatMessage, Folder, Plan, Project, Spec, User } from "./types";
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
