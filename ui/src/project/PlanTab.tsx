import { CheckCircle2, ClipboardList, Hammer, Loader2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import type { Plan, PlanTask } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { FailureBanner } from "./FailureBanner";
import { FeedbackForm } from "./FeedbackForm";
import { formatCost, formatTokens } from "./format";
import { useProjectData } from "./ProjectDataProvider";
import { useAsyncAction } from "./useAsyncAction";

const SEP = " · ";

function Chips({ items, testId }: { items: string[]; testId: string }) {
  return (
    <ul className="flex flex-wrap gap-1" data-testid={testId}>
      {items.map((item) => (
        <li
          key={item}
          className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground"
        >
          {item}
        </li>
      ))}
    </ul>
  );
}

function TaskCard({ task }: { task: PlanTask }) {
  const { t } = useTranslation("plan");
  return (
    <li
      data-testid={`task-card-${task.id}`}
      className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3 text-sm text-card-foreground"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-muted-foreground">{task.id}</span>
        <Badge
          tone="primary"
          aria-label={t("task.size", { size: task.size })}
          data-testid="task-size"
        >
          {task.size}
        </Badge>
        <Badge data-testid="task-role">{t(`task.role.${task.role}`)}</Badge>
      </div>
      <h4 className="font-medium">{task.title}</h4>
      <dl className="flex flex-col gap-2">
        <div className="flex flex-col gap-1">
          <dt className="text-xs font-medium text-muted-foreground">{t("task.dependsOn")}</dt>
          <dd>
            {task.depends_on.length > 0 ? (
              <Chips items={task.depends_on} testId="task-depends" />
            ) : (
              <span className="text-muted-foreground">{t("task.none")}</span>
            )}
          </dd>
        </div>
        <div className="flex flex-col gap-1">
          <dt className="text-xs font-medium text-muted-foreground">{t("task.files")}</dt>
          <dd>
            <Chips items={task.files} testId="task-files" />
          </dd>
        </div>
        <div className="flex flex-col gap-1">
          <dt className="text-xs font-medium text-muted-foreground">{t("task.acceptance")}</dt>
          <dd>
            <ul className="list-disc pl-5" data-testid="task-acceptance">
              {task.acceptance.map((criterion) => (
                <li key={criterion}>{criterion}</li>
              ))}
            </ul>
          </dd>
        </div>
        <div className="flex flex-col gap-1">
          <dt className="text-xs font-medium text-muted-foreground">{t("task.tests")}</dt>
          <dd>
            <code className="font-mono text-xs" data-testid="task-tests">
              {task.tests}
            </code>
          </dd>
        </div>
      </dl>
    </li>
  );
}

function PlanView({ plan, lang }: { plan: Plan; lang: string }) {
  const { t } = useTranslation("plan");
  const { milestones, tasks } = plan.plan;
  const estimateOf = (id: string) => plan.estimate.milestones.find((m) => m.id === id);
  return (
    <div className="flex flex-col gap-4">
      <section
        aria-labelledby="estimate-title"
        data-testid="plan-estimate"
        className="rounded-lg border border-border bg-card p-4 text-card-foreground"
      >
        <h3 id="estimate-title" className="text-sm font-semibold">
          {t("estimate.title")}
        </h3>
        <p className="mt-1 flex flex-wrap items-baseline gap-x-3">
          <span className="text-xs text-muted-foreground">{t("estimate.total")}</span>
          <span className="text-2xl font-semibold" data-testid="estimate-total-cost">
            {formatCost(plan.estimate.cost_usd, lang)}
          </span>
          <span className="text-sm text-muted-foreground" data-testid="estimate-total-tokens">
            {t("estimate.tokens", { tokens: formatTokens(plan.estimate.tokens, lang) })}
          </span>
        </p>
        <p className="mt-1 text-xs text-muted-foreground">{t("estimate.note")}</p>
      </section>

      {milestones.map((milestone) => {
        const own = tasks.filter((task) => task.milestone === milestone.id);
        const estimate = estimateOf(milestone.id);
        return (
          <section
            key={milestone.id}
            aria-labelledby={`milestone-${milestone.id}`}
            data-testid={`milestone-${milestone.id}`}
            className="flex flex-col gap-2"
          >
            <header className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 id={`milestone-${milestone.id}`} className="text-base font-semibold">
                <span className="text-muted-foreground">{milestone.id}</span>
                {SEP}
                {milestone.title}
              </h3>
              <p className="text-xs text-muted-foreground" data-testid="milestone-estimate">
                {t("tasks", { count: own.length })}
                {estimate && (
                  <>
                    {SEP}
                    {t("estimate.tokens", { tokens: formatTokens(estimate.tokens, lang) })}
                    {SEP}
                    {formatCost(estimate.cost_usd, lang)}
                  </>
                )}
              </p>
            </header>
            <ul className="grid gap-3 md:grid-cols-2">
              {own.map((task) => (
                <TaskCard key={task.id} task={task} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

export function PlanTab() {
  const { t, i18n } = useTranslation("plan");
  const { phase, paused, plan, spec, jobs, generatePlan, approvePlan, startBuilding } =
    useProjectData();
  const [asking, setAsking] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const feedback = useAsyncAction();
  const generate = useAsyncAction();
  const start = useAsyncAction();
  const lang = i18n.language;

  if (!plan) {
    const specApproved = phase === "spec_review" && spec?.status === "approved";
    const key = specApproved ? "specApproved" : phase === "interview" ? "interview" : "specReview";
    return (
      <div className="flex h-full flex-col gap-3 overflow-y-auto p-4" data-testid="plan-tab">
        <FailureBanner kinds={["plan"]} />
        <div
          data-testid="plan-empty"
          className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center"
        >
          {jobs.plan ? (
            <p role="status" data-testid="plan-generating" className="flex items-center gap-2">
              <Loader2
                className="h-5 w-5 animate-spin motion-reduce:animate-none"
                aria-hidden="true"
              />
              {t("generating")}
            </p>
          ) : (
            <>
              <ClipboardList className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
              <h2 className="text-lg font-semibold">{t(`empty.${key}.title`)}</h2>
              <p className="text-sm text-muted-foreground">{t(`empty.${key}.description`)}</p>
              {specApproved && (
                <Button
                  data-testid="plan-generate"
                  disabled={paused}
                  onClick={() => void generate.run(() => generatePlan())}
                >
                  {t("generatePlan")}
                </Button>
              )}
              {generate.error && (
                <p role="alert" className="text-sm text-destructive">
                  {generate.error}
                </p>
              )}
            </>
          )}
        </div>
      </div>
    );
  }

  const inReview = phase === "plan_review";
  const regenerating = jobs.plan;
  const error = feedback.error;

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="plan-tab">
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        <header className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold">{t("title")}</h2>
          <Badge data-testid="plan-version">{t("version", { version: plan.version })}</Badge>
          <Badge
            tone={plan.status === "approved" ? "success" : "warning"}
            data-testid="plan-status"
          >
            {t(`status.${plan.status}`)}
          </Badge>
        </header>
        <FailureBanner kinds={["plan", "start"]} />
        {regenerating && (
          <p
            role="status"
            data-testid="plan-generating"
            className="flex items-center gap-2 text-sm text-muted-foreground"
          >
            <Loader2
              className="h-4 w-4 animate-spin motion-reduce:animate-none"
              aria-hidden="true"
            />
            {t("regenerating")}
          </p>
        )}
        <PlanView plan={plan} lang={lang} />
      </div>

      <div className="flex flex-col gap-2 border-t border-border p-3">
        {(error || start.error) && (
          <p role="alert" data-testid="plan-error" className="text-sm text-destructive">
            {error ?? start.error}
          </p>
        )}
        {phase === "ready" && (
          <div
            data-testid="plan-approved"
            className="flex flex-wrap items-center justify-between gap-3 text-sm"
          >
            <div className="flex items-start gap-2" role="status">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
              <div>
                <p className="font-medium">{t("approved")}</p>
                <p className="text-muted-foreground">{t("approvedNote")}</p>
              </div>
            </div>
            <Button
              size="lg"
              data-testid="start-building"
              disabled={paused || jobs.start || start.busy}
              onClick={() => void start.run(() => startBuilding())}
            >
              {jobs.start || start.busy ? (
                <>
                  <Loader2
                    className="h-4 w-4 animate-spin motion-reduce:animate-none"
                    aria-hidden="true"
                  />
                  {t("starting")}
                </>
              ) : (
                <>
                  <Hammer className="h-4 w-4" aria-hidden="true" />
                  {t("startBuilding")}
                </>
              )}
            </Button>
          </div>
        )}
        {(phase === "building" || phase === "done") && (
          <div data-testid="plan-building" role="status" className="flex items-start gap-2 text-sm">
            <Hammer className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
            <p>
              {t(phase === "building" ? "building" : "done")}{" "}
              <Link
                to="?tab=agents"
                className="font-medium text-primary underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                {t("viewAgents")}
              </Link>
            </p>
          </div>
        )}
        {inReview && !asking && (
          <div className="flex flex-wrap gap-2">
            <Button
              data-testid="plan-approve"
              disabled={regenerating}
              onClick={() => setConfirming(true)}
            >
              {t("approve")}
            </Button>
            <Button
              variant="outline"
              data-testid="plan-request-changes"
              disabled={regenerating || paused}
              onClick={() => setAsking(true)}
            >
              {t("requestChanges")}
            </Button>
          </div>
        )}
        {inReview && asking && (
          <FeedbackForm
            idPrefix="plan"
            label={t("feedbackLabel")}
            placeholder={t("feedbackPlaceholder")}
            submitLabel={t("feedbackSubmit")}
            cancelLabel={t("cancel")}
            busy={feedback.busy || regenerating}
            onCancel={() => setAsking(false)}
            onSubmit={async (text) => {
              const ok = await feedback.run(() => generatePlan(text));
              if (ok) setAsking(false);
              return ok;
            }}
          />
        )}
      </div>

      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("approveTitle")}
        description={t("approveDescription", {
          cost: formatCost(plan.estimate.cost_usd, lang),
          tokens: formatTokens(plan.estimate.tokens, lang),
        })}
        confirmLabel={t("approveConfirm")}
        destructive={false}
        onConfirm={approvePlan}
      />
    </div>
  );
}
