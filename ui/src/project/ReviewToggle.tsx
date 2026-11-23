import { Eye } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { useProjectData } from "./ProjectDataProvider";
import { useAsyncAction } from "./useAsyncAction";

/** Reviewer agent: reads each task between CI green and merge. Opt-in because it costs tokens. */
export function ReviewToggle() {
  const { t } = useTranslation(["agents", "errors"]);
  const { project } = useProjectData();
  const { updateProject } = useWorkspace();
  const action = useAsyncAction();
  const on = project.review_enabled === true;
  return (
    <section
      aria-labelledby="review-mode-title"
      data-testid="review-mode"
      data-state={on ? "on" : "off"}
      className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      <h3 id="review-mode-title" className="flex items-center gap-2 text-sm font-semibold">
        <Eye className="h-4 w-4" aria-hidden="true" />
        {t("agents:review.toggle.title")}
      </h3>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={on}
          disabled={action.busy}
          data-testid="review-mode-toggle"
          onChange={(e) =>
            void action.run(() => updateProject(project.id, { review_enabled: e.target.checked }))
          }
        />
        <span>{t("agents:review.toggle.label")}</span>
      </label>
      <p className="text-xs text-muted-foreground">
        {on ? t("agents:review.toggle.onHelp") : t("agents:review.toggle.offHelp")}
      </p>
      {action.error && (
        <p role="alert" className="text-sm text-destructive" data-testid="review-mode-error">
          {action.error}
        </p>
      )}
    </section>
  );
}
