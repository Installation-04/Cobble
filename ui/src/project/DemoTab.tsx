import { CheckCircle2, ExternalLink, MessageSquarePlus, MonitorPlay, Undo2, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { demoApi, unwrap } from "../api/endpoints";
import { errorMessage } from "../api/errors";
import type { Milestone, MilestoneStatus, Task } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Badge, type BadgeTone } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "../components/ui/dialog";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import { FailureBanner } from "./FailureBanner";
import { useProjectData } from "./ProjectDataProvider";
import { useAsyncAction } from "./useAsyncAction";

export const COMMENT_MAX = 2000;

const STATUS_TONE: Record<MilestoneStatus, BadgeTone> = {
  pending: "neutral",
  built: "warning",
  validated: "success",
};

function CommentDialog({
  milestone,
  onOpenChange,
  onCreated,
}: {
  milestone: Milestone | null;
  onOpenChange: (open: boolean) => void;
  onCreated: (task: Task | null, milestone: Milestone) => void;
}) {
  const { t } = useTranslation("demo");
  const { project, upsertTask, reloadMilestones } = useProjectData();
  const [text, setText] = useState("");
  const send = useAsyncAction();
  const content = text.trim();
  const valid = content.length >= 1 && content.length <= COMMENT_MAX;

  async function submit() {
    if (!milestone || !valid) return;
    const ok = await send.run(async () => {
      const answer = await demoApi.comment(project.id, milestone.ref, content);
      const task = unwrap<Task | null>(answer, "task");
      if (task && typeof task.ref === "string") upsertTask(task);
      await reloadMilestones();
      onCreated(task && typeof task.ref === "string" ? task : null, milestone);
    });
    if (ok) {
      setText("");
      onOpenChange(false);
    }
  }

  return (
    <Dialog
      open={milestone !== null}
      onOpenChange={(open) => {
        if (!open) send.clearError();
        onOpenChange(open);
      }}
    >
      <DialogContent data-testid="comment-dialog">
        <DialogHeader>
          <DialogTitle>{t("comment.title", { ref: milestone?.ref })}</DialogTitle>
          <DialogDescription>{t("comment.description")}</DialogDescription>
        </DialogHeader>
        <form
          className="grid gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="demo-comment">{t("comment.label")}</Label>
            <Textarea
              id="demo-comment"
              data-testid="comment-input"
              rows={5}
              autoFocus
              maxLength={COMMENT_MAX}
              value={text}
              placeholder={t("comment.placeholder")}
              onChange={(e) => setText(e.target.value)}
            />
            <p className="text-right text-xs text-muted-foreground" data-testid="comment-count">
              {t("comment.count", { count: text.length, max: COMMENT_MAX })}
            </p>
          </div>
          {send.error && (
            <p role="alert" data-testid="comment-error" className="text-sm text-destructive">
              {send.error}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("common:cancel")}
            </Button>
            <Button type="submit" data-testid="comment-submit" disabled={!valid || send.busy}>
              {send.busy ? t("comment.sending") : t("comment.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function MilestoneCard({
  milestone,
  showPreview,
  onTogglePreview,
  onComment,
  onRevert,
}: {
  milestone: Milestone;
  showPreview: boolean;
  onTogglePreview: () => void;
  onComment: () => void;
  onRevert: () => void;
}) {
  const { t, i18n } = useTranslation("demo");
  const { project, reloadMilestones } = useProjectData();
  const validate = useAsyncAction();
  const live = milestone.status === "built" || milestone.status === "validated";
  const previewPath = live ? milestone.preview_path : null;
  const built = milestone.built_at
    ? new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeStyle: "short" }).format(
        new Date(milestone.built_at),
      )
    : null;

  return (
    <li
      data-testid={`milestone-card-${milestone.ref}`}
      data-status={milestone.status}
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-muted-foreground">{milestone.ref}</span>
        <h3 className="text-base font-semibold">{milestone.title}</h3>
        <Badge tone={STATUS_TONE[milestone.status]} data-testid="milestone-status">
          {t(`status.${milestone.status}`)}
        </Badge>
        {built && (
          <span className="text-xs text-muted-foreground" data-testid="milestone-built-at">
            {t("builtAt", { date: built })}
          </span>
        )}
      </div>

      {milestone.status === "pending" && (
        <p className="text-sm text-muted-foreground">{t("pendingNote")}</p>
      )}

      {live && (
        <div className="flex flex-wrap gap-2">
          {previewPath && (
            <a
              href={previewPath}
              target="_blank"
              rel="noopener noreferrer"
              data-testid={`demo-open-${milestone.ref}`}
              className="inline-flex h-8 items-center justify-center gap-2 rounded-md border border-input bg-background px-3 text-sm font-medium text-foreground hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              <ExternalLink className="h-4 w-4" aria-hidden="true" />
              {t("open")}
              <span className="sr-only">{t("newTab")}</span>
            </a>
          )}
          {previewPath && (
            <Button
              size="sm"
              variant="ghost"
              aria-expanded={showPreview}
              data-testid={`demo-toggle-${milestone.ref}`}
              onClick={onTogglePreview}
            >
              {showPreview ? t("hidePreview") : t("showPreview")}
            </Button>
          )}
          <Button
            size="sm"
            data-testid={`milestone-validate-${milestone.ref}`}
            disabled={milestone.status !== "built" || validate.busy}
            onClick={() =>
              void validate.run(async () => {
                await demoApi.validate(project.id, milestone.ref);
                await reloadMilestones();
              })
            }
          >
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            {validate.busy ? t("validating") : t("validate")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            data-testid={`milestone-comment-${milestone.ref}`}
            onClick={onComment}
          >
            <MessageSquarePlus className="h-4 w-4" aria-hidden="true" />
            {t("comment.open")}
          </Button>
          <Button
            size="sm"
            variant="destructive"
            data-testid={`milestone-revert-${milestone.ref}`}
            onClick={onRevert}
          >
            <Undo2 className="h-4 w-4" aria-hidden="true" />
            {t("revert.open")}
          </Button>
        </div>
      )}
      {validate.error && (
        <p role="alert" data-testid="milestone-error" className="text-sm text-destructive">
          {validate.error}
        </p>
      )}

      {previewPath && showPreview && (
        // The demo is code written by agents. Scripts are needed for the app to run and forms
        // for its inputs; `allow-same-origin` is deliberately left out so the frame gets an
        // opaque origin and cannot read Cobble's cookies or call its API (the path itself is
        // same-origin `/demo/...`). Popups, top navigation and downloads stay blocked.
        <iframe
          src={previewPath}
          title={t("previewTitle", { ref: milestone.ref })}
          data-testid={`demo-frame-${milestone.ref}`}
          sandbox="allow-scripts allow-forms"
          referrerPolicy="no-referrer"
          loading="lazy"
          className="h-96 w-full rounded-md border border-border bg-background"
        />
      )}
    </li>
  );
}

export function DemoTab() {
  const { t } = useTranslation(["demo", "errors"]);
  const { project, milestones, buildError, phase, reloadTasks, reloadMilestones } =
    useProjectData();
  const [commenting, setCommenting] = useState<Milestone | null>(null);
  const [reverting, setReverting] = useState<Milestone | null>(null);
  const [notice, setNotice] = useState<{ ref: string | null; milestone: string } | null>(null);
  // Previews the user opened or closed by hand; otherwise the newest unvalidated build is open.
  const [manual, setManual] = useState<Record<string, boolean>>({});

  const newestBuilt = [...milestones].reverse().find((m) => m.status === "built")?.ref;
  const isShown = (m: Milestone) => manual[m.ref] ?? m.ref === newestBuilt;

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-4" data-testid="demo-tab">
      <FailureBanner kinds={["start"]} />
      {notice && (
        <div
          role="status"
          data-testid="comment-created"
          className="flex items-start gap-2 rounded-md border border-border bg-card p-3 text-sm text-card-foreground"
        >
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
          <p className="min-w-0 flex-1">
            {notice.ref
              ? t("comment.created", { ref: notice.ref, milestone: notice.milestone })
              : t("comment.createdNoRef", { milestone: notice.milestone })}{" "}
            <Link
              to={notice.ref ? `?tab=agents&task=${encodeURIComponent(notice.ref)}` : "?tab=agents"}
              data-testid="comment-created-link"
              className="font-medium text-primary underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            >
              {t("comment.viewTask")}
            </Link>
          </p>
          <button
            type="button"
            aria-label={t("comment.dismiss")}
            onClick={() => setNotice(null)}
            className="rounded-sm p-1 hover:opacity-80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
      {buildError != null && milestones.length === 0 && (
        <p role="alert" data-testid="demo-error" className="text-sm text-destructive">
          {errorMessage(t, buildError)}
        </p>
      )}
      {phase === "done" && (
        <p
          role="status"
          data-testid="demo-done"
          className="flex items-center gap-2 text-sm font-medium"
        >
          <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
          {t("done")}
        </p>
      )}
      {milestones.length === 0 ? (
        <div
          data-testid="demo-empty"
          className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center"
        >
          <MonitorPlay className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
          <h2 className="text-lg font-semibold">{t("empty.title")}</h2>
          <p className="text-sm text-muted-foreground">
            {t(phase === "building" || phase === "done" ? "empty.building" : "empty.notStarted")}
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-4">
          {milestones.map((milestone) => (
            <MilestoneCard
              key={milestone.ref}
              milestone={milestone}
              showPreview={isShown(milestone)}
              onTogglePreview={() =>
                setManual((prev) => ({ ...prev, [milestone.ref]: !isShown(milestone) }))
              }
              onComment={() => setCommenting(milestone)}
              onRevert={() => setReverting(milestone)}
            />
          ))}
        </ul>
      )}

      <CommentDialog
        milestone={commenting}
        onOpenChange={(open) => !open && setCommenting(null)}
        onCreated={(task, milestone) =>
          setNotice({ ref: task?.ref ?? null, milestone: milestone.ref })
        }
      />
      <ConfirmDialog
        open={reverting !== null}
        onOpenChange={(open) => !open && setReverting(null)}
        title={t("revert.title", { ref: reverting?.ref })}
        description={t("revert.description", { ref: reverting?.ref })}
        confirmLabel={t("revert.confirm")}
        onConfirm={async () => {
          if (!reverting) return;
          await demoApi.revert(project.id, reverting.ref);
          await Promise.all([reloadMilestones(), reloadTasks()]);
        }}
      />
    </div>
  );
}
