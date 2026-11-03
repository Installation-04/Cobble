import { useState } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { Folder, Project } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FolderDialog } from "../components/FolderDialog";
import { ProjectDialog } from "../components/ProjectDialog";
import { SettingsDialog } from "../components/SettingsDialog";
import { Sidebar, type SidebarActions } from "../components/Sidebar";
import { TopBar } from "../components/TopBar";
import { cn } from "../lib";
import { useWorkspace, WorkspaceProvider } from "../workspace/WorkspaceProvider";

type Dialogs =
  | { kind: "none" }
  | { kind: "folder"; folder: Folder | null }
  | { kind: "project"; project: Project | null; folderId: string | null }
  | { kind: "delete-folder"; folder: Folder }
  | { kind: "delete-project"; project: Project };

const isDesktop = () =>
  typeof window.matchMedia !== "function" || window.matchMedia("(min-width: 768px)").matches;

function ShellInner() {
  const { t } = useTranslation("shell");
  const navigate = useNavigate();
  const { deleteFolder, deleteProject } = useWorkspace();
  const { user } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(isDesktop);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [dialog, setDialog] = useState<Dialogs>({ kind: "none" });
  const close = () => setDialog({ kind: "none" });

  const actions: SidebarActions = {
    newProject: (folderId = null) => setDialog({ kind: "project", project: null, folderId }),
    newFolder: () => setDialog({ kind: "folder", folder: null }),
    renameFolder: (folder) => setDialog({ kind: "folder", folder }),
    deleteFolder: (folder) => setDialog({ kind: "delete-folder", folder }),
    editProject: (project) => setDialog({ kind: "project", project, folderId: null }),
    deleteProject: (project) => setDialog({ kind: "delete-project", project }),
    navigated: () => {
      if (!isDesktop()) setSidebarOpen(false);
    },
  };

  return (
    <div className="flex h-full bg-background text-foreground" data-testid="app-shell">
      {sidebarOpen && (
        <button
          type="button"
          tabIndex={-1}
          aria-hidden="true"
          className="fixed inset-0 z-30 bg-overlay md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        data-open={sidebarOpen}
        className={cn(
          "fixed inset-y-0 left-0 z-40 w-72 max-w-[85vw] shrink-0 border-r border-border transition-transform md:static md:max-w-none",
          sidebarOpen ? "translate-x-0" : "-translate-x-full md:hidden",
        )}
      >
        <Sidebar actions={actions} showStore={user?.role === "admin"} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          onToggleSidebar={() => setSidebarOpen((o) => !o)}
          onOpenSettings={() => setSettingsOpen(true)}
        />
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>

      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      <FolderDialog
        open={dialog.kind === "folder"}
        onOpenChange={(o) => !o && close()}
        folder={dialog.kind === "folder" ? dialog.folder : null}
      />
      <ProjectDialog
        open={dialog.kind === "project"}
        onOpenChange={(o) => !o && close()}
        project={dialog.kind === "project" ? dialog.project : null}
        defaultFolderId={dialog.kind === "project" ? dialog.folderId : null}
        onCreated={(p) => {
          navigate(`/projects/${p.id}`);
          actions.navigated?.();
        }}
      />
      <ConfirmDialog
        open={dialog.kind === "delete-folder"}
        onOpenChange={(o) => !o && close()}
        title={t("folder.deleteTitle")}
        description={
          dialog.kind === "delete-folder"
            ? t("folder.deleteDescription", { name: dialog.folder.name })
            : ""
        }
        onConfirm={async () => {
          if (dialog.kind === "delete-folder") await deleteFolder(dialog.folder.id);
        }}
      />
      <ConfirmDialog
        open={dialog.kind === "delete-project"}
        onOpenChange={(o) => !o && close()}
        title={t("project.deleteTitle")}
        description={
          dialog.kind === "delete-project"
            ? t("project.deleteDescription", { name: dialog.project.name })
            : ""
        }
        onConfirm={async () => {
          if (dialog.kind !== "delete-project") return;
          await deleteProject(dialog.project.id);
          navigate("/");
        }}
      />
    </div>
  );
}

export function Shell() {
  return (
    <WorkspaceProvider>
      <ShellInner />
    </WorkspaceProvider>
  );
}
