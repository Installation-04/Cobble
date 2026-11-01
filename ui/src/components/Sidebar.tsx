import {
  Blocks,
  Bot,
  ChevronDown,
  ChevronRight,
  Coins,
  Folder as FolderIcon,
  FolderPlus,
  MonitorPlay,
  MoreHorizontal,
  Plus,
  Search,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";
import type { Folder, Project } from "../api/types";
import { cn } from "../lib";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { Button } from "./ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { Input } from "./ui/input";

export interface SidebarActions {
  newProject: (folderId?: string | null) => void;
  newFolder: () => void;
  renameFolder: (folder: Folder) => void;
  deleteFolder: (folder: Folder) => void;
  editProject: (project: Project) => void;
  deleteProject: (project: Project) => void;
  /** Called after a navigation click (lets a mobile drawer close). */
  navigated?: () => void;
}

const ROW = "group flex items-center gap-1 rounded-md px-2 py-1.5 text-sm hover:bg-accent";

function RowMenu({
  label,
  testId,
  onRename,
  onDelete,
  extra,
}: {
  label: string;
  testId: string;
  onRename: () => void;
  onDelete: () => void;
  extra?: ReactNode;
}) {
  const { t } = useTranslation("common");
  return (
    <DropdownMenu modal={false}>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 shrink-0 opacity-100 md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100"
          aria-label={label}
          data-testid={testId}
        >
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {extra}
        <DropdownMenuItem data-testid="menu-rename" onSelect={onRename}>
          {t("rename")}
        </DropdownMenuItem>
        <DropdownMenuItem data-testid="menu-delete" destructive onSelect={onDelete}>
          {t("delete")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ProjectRow({ project, actions }: { project: Project; actions: SidebarActions }) {
  const { t } = useTranslation("shell");
  return (
    <li className={ROW} data-testid="project-item">
      <NavLink
        to={`/projects/${project.id}`}
        onClick={actions.navigated}
        className={({ isActive }) =>
          cn("min-w-0 flex-1 truncate", isActive && "font-semibold text-primary")
        }
      >
        {project.name}
      </NavLink>
      <RowMenu
        label={t("project.menu", { name: project.name })}
        testId="project-menu"
        onRename={() => actions.editProject(project)}
        onDelete={() => actions.deleteProject(project)}
      />
    </li>
  );
}

export function Sidebar({
  actions,
  showStore = false,
}: {
  actions: SidebarActions;
  /** Administrators only: the Store installs software on the machine. */
  showStore?: boolean;
}) {
  const { t } = useTranslation(["shell", "common"]);
  const { folders, projects, loading } = useWorkspace();
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const q = query.trim().toLowerCase();
  const matches = (p: Project) => !q || p.name.toLowerCase().includes(q);

  const { groups, unfiled } = useMemo(() => {
    const byFolder = new Map<string, Project[]>();
    const loose: Project[] = [];
    for (const p of projects) {
      if (!matches(p)) continue;
      if (p.folder_id && folders.some((f) => f.id === p.folder_id)) {
        byFolder.set(p.folder_id, [...(byFolder.get(p.folder_id) ?? []), p]);
      } else loose.push(p);
    }
    const visible = folders
      .map((folder) => ({ folder, projects: byFolder.get(folder.id) ?? [] }))
      .filter((g) => !q || g.projects.length > 0 || g.folder.name.toLowerCase().includes(q));
    return { groups: visible, unfiled: loose };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folders, projects, q]);

  const toggle = (id: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const empty = !loading && projects.length === 0 && folders.length === 0;
  const noResults = !empty && !!q && groups.length === 0 && unfiled.length === 0;
  const globalLinks = [
    { to: "/agents", icon: Bot, label: t("shell:sidebar.agents"), id: "agents" },
    { to: "/demos", icon: MonitorPlay, label: t("shell:sidebar.demos"), id: "demos" },
    { to: "/costs", icon: Coins, label: t("shell:sidebar.costs"), id: "costs" },
    ...(showStore
      ? [{ to: "/store", icon: Blocks, label: t("shell:sidebar.store"), id: "store" }]
      : []),
  ];

  return (
    <div
      data-testid="sidebar"
      className="flex h-full flex-col gap-3 bg-sidebar p-3 text-sidebar-foreground"
    >
      <div className="px-2 pt-1 text-lg font-semibold">{t("common:app.name")}</div>
      <Button
        data-testid="new-project-button"
        className="w-full"
        onClick={() => actions.newProject()}
      >
        <Plus className="h-4 w-4" />
        {t("shell:sidebar.newProject")}
      </Button>
      <div className="flex items-center gap-1">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-2.5 left-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            type="search"
            data-testid="sidebar-search"
            className="pl-8"
            value={query}
            aria-label={t("shell:sidebar.search")}
            placeholder={t("shell:sidebar.searchPlaceholder")}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <Button
          variant="outline"
          size="icon"
          data-testid="new-folder-button"
          aria-label={t("shell:sidebar.newFolder")}
          title={t("shell:sidebar.newFolder")}
          onClick={actions.newFolder}
        >
          <FolderPlus className="h-4 w-4" />
        </Button>
      </div>

      <nav aria-label={t("shell:sidebar.label")} className="min-h-0 flex-1 overflow-y-auto">
        {loading && <p className="px-2 text-sm text-muted-foreground">{t("common:loading")}</p>}
        {empty && (
          <p className="px-2 text-sm text-muted-foreground" data-testid="sidebar-empty">
            {t("shell:sidebar.empty")}
          </p>
        )}
        {noResults && (
          <p className="px-2 text-sm text-muted-foreground" data-testid="sidebar-no-results">
            {t("shell:sidebar.noResults")}
          </p>
        )}
        <ul className="grid gap-0.5">
          {groups.map(({ folder, projects: inFolder }) => {
            const open = !!q || !collapsed.has(folder.id);
            return (
              <li key={folder.id} data-testid="folder-item">
                <div className={ROW}>
                  <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
                    aria-expanded={open}
                    aria-label={t("shell:sidebar.expandFolder", { name: folder.name })}
                    data-testid="folder-toggle"
                    onClick={() => toggle(folder.id)}
                  >
                    {open ? (
                      <ChevronDown className="h-4 w-4 shrink-0" />
                    ) : (
                      <ChevronRight className="h-4 w-4 shrink-0" />
                    )}
                    <FolderIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="truncate" data-testid="folder-name">
                      {folder.name}
                    </span>
                  </button>
                  <RowMenu
                    label={t("shell:folder.menu", { name: folder.name })}
                    testId="folder-menu"
                    onRename={() => actions.renameFolder(folder)}
                    onDelete={() => actions.deleteFolder(folder)}
                    extra={
                      <DropdownMenuItem
                        data-testid="menu-new-project"
                        onSelect={() => actions.newProject(folder.id)}
                      >
                        {t("shell:sidebar.newProject")}
                      </DropdownMenuItem>
                    }
                  />
                </div>
                {open && inFolder.length > 0 && (
                  <ul className="ml-4 grid gap-0.5 border-l border-border pl-2">
                    {inFolder.map((p) => (
                      <ProjectRow key={p.id} project={p} actions={actions} />
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
        {unfiled.length > 0 && (
          <div className="mt-3">
            {groups.length > 0 && (
              <h2 className="px-2 pb-1 text-xs font-medium text-muted-foreground uppercase">
                {t("shell:sidebar.unfiled")}
              </h2>
            )}
            <ul className="grid gap-0.5" data-testid="unfiled-projects">
              {unfiled.map((p) => (
                <ProjectRow key={p.id} project={p} actions={actions} />
              ))}
            </ul>
          </div>
        )}
      </nav>

      <nav
        aria-label={t("shell:sidebar.global")}
        className="grid gap-0.5 border-t border-border pt-2"
      >
        {globalLinks.map(({ to, icon: Icon, label, id }) => (
          <NavLink
            key={to}
            to={to}
            data-testid={`nav-${id}`}
            onClick={actions.navigated}
            className={({ isActive }) =>
              cn(ROW, "gap-2", isActive && "bg-accent font-semibold text-accent-foreground")
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
