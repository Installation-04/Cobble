import { useState } from "react";
import { useTranslation } from "react-i18next";
import { errorMessage } from "../api/errors";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  onConfirm: () => Promise<void>;
}

export function ConfirmDialog({ open, onOpenChange, title, description, onConfirm }: Props) {
  const { t } = useTranslation(["common", "errors"]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onOpenChange(false);
    } catch (e) {
      setError(errorMessage(t, e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setError(null);
        onOpenChange(next);
      }}
    >
      <DialogContent data-testid="confirm-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("common:cancel")}
          </Button>
          <Button
            variant="destructive"
            data-testid="confirm-submit"
            disabled={busy}
            onClick={confirm}
          >
            {t("common:delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
