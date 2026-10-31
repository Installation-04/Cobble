import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Markdown } from "../components/Markdown";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { FeedbackForm } from "./FeedbackForm";
import { useProjectData } from "./ProjectDataProvider";
import { useAsyncAction } from "./useAsyncAction";

export function SpecPanel() {
  const { t } = useTranslation("spec");
  const { spec, phase, paused, jobs, approveSpec, generateSpec, generatePlan } = useProjectData();
  const approve = useAsyncAction();
  const feedback = useAsyncAction();
  const plan = useAsyncAction();
  const [asking, setAsking] = useState(false);
  if (!spec) return null;

  const inReview = phase === "spec_review";
  const regenerating = jobs.spec;
  const planning = jobs.plan;
  const draft = spec.status === "draft";
  const error = approve.error ?? feedback.error ?? plan.error;

  return (
    <section
      aria-labelledby="spec-title"
      data-testid="spec-panel"
      className="flex min-h-0 flex-col gap-3 p-4"
    >
      <header className="flex flex-wrap items-center gap-2">
        <h2 id="spec-title" className="text-base font-semibold">
          {t("title")}
        </h2>
        <Badge data-testid="spec-version">{t("version", { version: spec.version })}</Badge>
        <Badge tone={draft ? "warning" : "success"} data-testid="spec-status">
          {t(`status.${spec.status}`)}
        </Badge>
      </header>

      <div
        className="min-h-0 flex-1 overflow-y-auto rounded-md border border-border bg-card p-3 text-card-foreground"
        data-testid="spec-content"
      >
        <Markdown>{spec.content}</Markdown>
      </div>

      {regenerating && (
        <p
          role="status"
          data-testid="spec-regenerating"
          className="flex items-center gap-2 text-sm text-muted-foreground"
        >
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          {t("regenerating")}
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive" data-testid="spec-error">
          {error}
        </p>
      )}

      {inReview && draft && !asking && (
        <div className="flex flex-wrap gap-2">
          <Button
            data-testid="spec-approve"
            disabled={approve.busy || regenerating}
            onClick={() => void approve.run(approveSpec)}
          >
            {approve.busy ? t("approving") : t("approve")}
          </Button>
          <Button
            variant="outline"
            data-testid="spec-request-changes"
            disabled={regenerating || paused}
            onClick={() => setAsking(true)}
          >
            {t("requestChanges")}
          </Button>
        </div>
      )}

      {inReview && draft && asking && (
        <FeedbackForm
          idPrefix="spec"
          label={t("feedbackLabel")}
          placeholder={t("feedbackPlaceholder")}
          submitLabel={t("feedbackSubmit")}
          cancelLabel={t("cancel")}
          busy={feedback.busy || regenerating}
          onCancel={() => setAsking(false)}
          onSubmit={async (text) => {
            const ok = await feedback.run(() => generateSpec(text));
            if (ok) setAsking(false);
            return ok;
          }}
        />
      )}

      {inReview && !draft && (
        <div className="flex flex-col gap-2">
          <p className="text-sm text-muted-foreground" data-testid="spec-approved-note">
            {t("approvedNote")}
          </p>
          <div>
            <Button
              data-testid="plan-generate"
              disabled={planning || paused}
              onClick={() => void plan.run(() => generatePlan())}
            >
              {planning && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
              {planning ? t("generatingPlan") : t("generatePlan")}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
