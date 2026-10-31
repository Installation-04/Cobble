import { api } from "./client";
import type { Folder, Project, User } from "./types";
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
