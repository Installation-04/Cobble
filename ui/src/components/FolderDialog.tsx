import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { errorMessage } from "../api/errors";
import type { Folder } from "../api/types";
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

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When set, the dialog renames this folder instead of creating one. */
  folder?: Folder | null;
}

function FolderForm({ folder, onDone }: { folder?: Folder | null; onDone: () => void }) {
  const { t } = useTranslation(["shell", "common"]);
  const { createFolder, renameFolder } = useWorkspace();
  const [name, setName] = useState(folder?.name ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      if (folder) await renameFolder(folder.id, trimmed);
      else await createFolder(trimmed);
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
        <Label htmlFor="folder-name">{t("shell:folder.name")}</Label>
        <Input
          id="folder-name"
          data-testid="folder-name-input"
          value={name}
          maxLength={100}
          autoFocus
          placeholder={t("shell:folder.namePlaceholder")}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      {error && (
        <p role="alert" data-testid="dialog-error" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button type="submit" data-testid="folder-submit" disabled={busy || !name.trim()}>
          {folder ? t("common:save") : t("common:create")}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function FolderDialog({ open, onOpenChange, folder }: Props) {
  const { t } = useTranslation("shell");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="folder-dialog">
        <DialogHeader>
          <DialogTitle>{folder ? t("folder.renameTitle") : t("folder.createTitle")}</DialogTitle>
          <DialogDescription className="sr-only">{t("folder.name")}</DialogDescription>
        </DialogHeader>
        <FolderForm folder={folder} onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}
