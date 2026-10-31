import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { errorMessage } from "../api/errors";
import type { Project } from "../api/types";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Select } from "./ui/select";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When set, the dialog edits this project instead of creating one. */
  project?: Project | null;
  /** Preselected folder when creating. */
  defaultFolderId?: string | null;
  onCreated?: (project: Project) => void;
}

function ProjectForm({
  project,
  defaultFolderId,
  onDone,
  onCreated,
}: {
  project?: Project | null;
  defaultFolderId?: string | null;
  onDone: () => void;
  onCreated?: (project: Project) => void;
}) {
  const { t } = useTranslation(["shell", "common"]);
  const { folders, createProject, updateProject } = useWorkspace();
  const [name, setName] = useState(project?.name ?? "");
  const [folderId, setFolderId] = useState(project?.folder_id ?? defaultFolderId ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      if (project) {
        await updateProject(project.id, { name: trimmed, folder_id: folderId || null });
      } else {
        const created = await createProject(trimmed, folderId || null);
        onCreated?.(created);
      }
      onDone();
    } catch (e) {
      setError(errorMessage(t, e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <div className="grid gap-2">
        <Label htmlFor="project-name">{t("shell:project.name")}</Label>
        <Input
          id="project-name"
          data-testid="project-name-input"
          value={name}
          maxLength={100}
          autoFocus
          placeholder={t("shell:project.namePlaceholder")}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="grid gap-2">
        <Label htmlFor="project-folder">{t("shell:project.folder")}</Label>
        <Select
          id="project-folder"
          data-testid="project-folder-select"
          value={folderId}
          onChange={(e) => setFolderId(e.target.value)}
        >
          <option value="">{t("shell:project.noFolder")}</option>
          {folders.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </Select>
      </div>
      {error && (
        <p role="alert" data-testid="dialog-error" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button type="submit" data-testid="project-submit" disabled={busy || !name.trim()}>
          {project ? t("common:save") : t("common:create")}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function ProjectDialog({ open, onOpenChange, project, defaultFolderId, onCreated }: Props) {
  const { t } = useTranslation("shell");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="project-dialog">
        <DialogHeader>
          <DialogTitle>{project ? t("project.renameTitle") : t("project.createTitle")}</DialogTitle>
          <DialogDescription className="sr-only">{t("project.name")}</DialogDescription>
        </DialogHeader>
        <ProjectForm
          project={project}
          defaultFolderId={defaultFolderId}
          onDone={() => onOpenChange(false)}
          onCreated={onCreated}
        />
      </DialogContent>
    </Dialog>
  );
}
