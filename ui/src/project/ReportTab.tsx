import type { TFunction } from "i18next";
import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import { errorMessage } from "../api/errors";
import { reportApi } from "../api/endpoints";
import type { ProjectReport } from "../api/types";
import { SavingsCard } from "./CostsTab";
import { formatCost, formatTokens } from "./format";
import { useProjectData } from "./ProjectDataProvider";
import { useFetched } from "./useFetched";

const SEPARATOR = "/";

function duration(seconds: number | null, t: TFunction<"report">): string {
  if (seconds === null) return t("na");
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return t("duration.days", { days, hours });
  if (hours > 0) return t("duration.hours", { hours, minutes });
  return t("duration.minutes", { minutes });
}

function Stat({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 text-card-foreground">
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="text-xl font-semibold" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

function ReportBody({ report, lang }: { report: ProjectReport; lang: string }) {
  const { t } = useTranslation("report");
  const { build, costs, span } = report;
  const tasks = build.tasks;
  const fallbacks = costs.fallbacks;
  const date = (iso: string | null) =>
    iso === null
      ? t("na")
      : new Intl.DateTimeFormat(lang, { dateStyle: "medium" }).format(new Date(iso));
  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm text-muted-foreground" data-testid="report-state">
        {t(report.project.finished ? "state.finished" : "state.ongoing")}
      </p>

      <section aria-labelledby="report-built" className="flex flex-col gap-3">
        <h3 id="report-built" className="text-sm font-semibold">
          {t("built.title")}
        </h3>
        <p className="text-sm" data-testid="report-built-summary">
          {t("built.summary", {
            validated: build.milestones_validated,
            milestones: build.milestones.length,
            done: tasks.done,
            total: tasks.total,
            failed: tasks.failed,
            escalated: tasks.escalated,
          })}
        </p>
        {build.milestones.length > 0 && (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table data-testid="report-milestones" className="w-full text-left text-sm">
              <caption className="sr-only">{t("built.title")}</caption>
              <thead className="bg-muted text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">
                    {t("col.milestone")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    {t("col.status")}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t("col.tasks")}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t("col.failed")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {build.milestones.map((m) => (
                  <tr key={m.ref} className="border-t border-border">
                    <th scope="row" className="px-3 py-2 font-medium">
                      {m.ref} {m.title}
                    </th>
                    <td className="px-3 py-2">{t(`milestoneStatus.${m.status}`)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {[m.tasks_done, m.tasks_total].join(SEPARATOR)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{m.tasks_failed}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <dl className="grid gap-3 sm:grid-cols-3" data-testid="report-totals">
        <Stat
          label={t("time.duration")}
          value={duration(span.duration_seconds, t)}
          testId="report-duration"
        />
        <Stat label={t("time.started")} value={date(span.started_at)} testId="report-started" />
        <Stat label={t("time.ended")} value={date(span.ended_at)} testId="report-ended" />
        <Stat
          label={t("costs.spent")}
          value={formatCost(costs.spent_usd, lang)}
          testId="report-spent"
        />
        <Stat
          label={t("costs.budget")}
          value={
            costs.budget_usd === null ? t("costs.noBudget") : formatCost(costs.budget_usd, lang)
          }
          testId="report-budget"
        />
        <Stat
          label={t("costs.estimate")}
          value={costs.estimate_usd === null ? t("na") : formatCost(costs.estimate_usd, lang)}
          testId="report-estimate"
        />
      </dl>
      <p className="text-sm text-muted-foreground" data-testid="report-tokens">
        {t("costs.tokens", {
          prompt: formatTokens(costs.tokens.prompt, lang),
          completion: formatTokens(costs.tokens.completion, lang),
        })}
      </p>

      <SavingsCard savings={costs.savings} lang={lang} />

      <section aria-labelledby="report-fallbacks" className="flex flex-col gap-1">
        <h3 id="report-fallbacks" className="text-sm font-semibold">
          {t("fallbacks.title")}
        </h3>
        <p className="text-sm text-muted-foreground" data-testid="report-fallbacks">
          {t("fallbacks.summary", { calls: fallbacks.calls, total: fallbacks.total_calls })}
        </p>
      </section>

      {(
        [
          ["byModel", "model", costs.by_model],
          ["byRole", "role", costs.by_role],
        ] as const
      ).map(([id, column, rows]) => (
        <section key={id} aria-labelledby={`report-${id}`} className="flex flex-col gap-2">
          <h3 id={`report-${id}`} className="text-sm font-semibold">
            {t(`${id}.title`)}
          </h3>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table data-testid={`report-${id}`} className="w-full text-left text-sm">
              <caption className="sr-only">{t(`${id}.title`)}</caption>
              <thead className="bg-muted text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">
                    {t(`col.${column}`)}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t("col.calls")}
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">
                    {t("col.cost")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const name = "model" in row ? row.model : row.role;
                  return (
                    <tr key={name ?? "unknown"} className="border-t border-border">
                      <th scope="row" className="px-3 py-2 font-medium">
                        {name ?? t("unknown")}
                      </th>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {formatTokens(row.calls, lang)}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {formatCost(row.cost_usd, lang)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

/** End-of-project report (ADR 0014): what was built, how long it took, what it cost and saved. */
export function ReportTab() {
  const { t, i18n } = useTranslation(["report", "errors"]);
  const { project } = useProjectData();
  const report = useFetched(() => reportApi.get(project.id), project.id);
  const lang = i18n.language;

  return (
    <div
      className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto p-4"
      data-testid="report-tab"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">{t("report:title", { name: project.name })}</h2>
        <a
          href={reportApi.markdownUrl(project.id)}
          download
          data-testid="report-download"
          className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium text-card-foreground hover:bg-accent hover:text-accent-foreground"
        >
          <Download className="h-4 w-4" aria-hidden="true" />
          {t("report:download")}
        </a>
      </div>
      {report.data ? (
        <ReportBody report={report.data} lang={lang} />
      ) : report.error != null ? (
        <p role="alert" data-testid="report-error" className="text-sm text-destructive">
          {errorMessage(t, report.error)}
        </p>
      ) : (
        <p role="status" className="text-sm text-muted-foreground">
          {t("common:loading")}
        </p>
      )}
    </div>
  );
}
