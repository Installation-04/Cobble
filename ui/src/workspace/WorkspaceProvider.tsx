import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { foldersApi, projectsApi } from "../api/endpoints";
import type { Folder, Project } from "../api/types";

export interface WorkspaceValue {
  folders: Folder[];
  projects: Project[];
  loading: boolean;
  error: unknown;
  reload: () => Promise<void>;
  createFolder: (name: string) => Promise<Folder>;
  renameFolder: (id: string, name: string) => Promise<void>;
  deleteFolder: (id: string) => Promise<void>;
  createProject: (name: string, folderId: string | null) => Promise<Project>;
  updateProject: (id: string, body: { name?: string; folder_id?: string | null }) => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
  /** Merge server-pushed fields (e.g. the phase) into a project already in memory. */
  patchProject: (id: string, patch: Partial<Project>) => void;
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [folders, setFolders] = useState<Folder[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const reload = useCallback(async () => {
    try {
      const [f, p] = await Promise.all([foldersApi.list(), projectsApi.list()]);
      setFolders([...f].sort((a, b) => a.position - b.position));
      setProjects(p);
      setError(null);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload();
  }, [reload]);

  const value = useMemo<WorkspaceValue>(
    () => ({
      folders,
      projects,
      loading,
      error,
      reload,
      createFolder: async (name) => {
        const folder = await foldersApi.create(name);
        setFolders((prev) => [...prev, folder]);
        return folder;
      },
      renameFolder: async (id, name) => {
        const updated = await foldersApi.rename(id, name);
        setFolders((prev) => prev.map((f) => (f.id === id ? updated : f)));
      },
      deleteFolder: async (id) => {
        await foldersApi.remove(id);
        setFolders((prev) => prev.filter((f) => f.id !== id));
        setProjects((prev) =>
          prev.map((p) => (p.folder_id === id ? { ...p, folder_id: null } : p)),
        );
      },
      createProject: async (name, folderId) => {
        const project = await projectsApi.create(name, folderId);
        setProjects((prev) => [...prev, project]);
        return project;
      },
      updateProject: async (id, body) => {
        const updated = await projectsApi.update(id, body);
        setProjects((prev) => prev.map((p) => (p.id === id ? updated : p)));
      },
      deleteProject: async (id) => {
        await projectsApi.remove(id);
        setProjects((prev) => prev.filter((p) => p.id !== id));
      },
      patchProject: (id, patch) =>
        setProjects((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p))),
    }),
    [folders, projects, loading, error, reload],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return ctx;
}
