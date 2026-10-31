import { AlertTriangle, Coins } from "lucide-react";
import { useTranslation } from "react-i18next";
import { errorMessage } from "../api/errors";
import type { CostLine } from "../api/types";
import { cn } from "../lib";
import { formatCost, formatTokens } from "./format";
import { useProjectData } from "./ProjectDataProvider";

export type BudgetLevel = "ok" | "warning" | "danger";

export const WARNING_RATIO = 0.8;

/** Fill ratio (uncapped) and level of a budget bar; null when there is no usable budget. */
export function budgetState(
  spent: string,
  budget: string | null,
): { ratio: number; level: BudgetLevel } | null {
  if (budget === null) return null;
  const limit = Number.parseFloat(budget);
  const used = Number.parseFloat(spent);
  if (!Number.isFinite(limit) || limit <= 0 || !Number.isFinite(used)) return null;
  const ratio = used / limit;
  return { ratio, level: ratio >= 1 ? "danger" : ratio >= WARNING_RATIO ? "warning" : "ok" };
}

const LEVEL_FILL: Record<BudgetLevel, string> = {
  ok: "bg-primary",
  warning: "bg-warning",
  danger: "bg-destructive",
};

function CostTable({
  testId,
  caption,
  firstColumn,
  rows,
  lang,
}: {
  testId: string;
  caption: string;
  firstColumn: string;
  rows: { key: string; label: string; line: CostLine }[];
  lang: string;
}) {
  const { t } = useTranslation("costs");
  return (
    <section aria-labelledby={`${testId}-title`} className="flex flex-col gap-2">
      <h3 id={`${testId}-title`} className="text-sm font-semibold">
        {caption}
      </h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("table.empty")}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table data-testid={testId} className="w-full text-left text-sm">
            <caption className="sr-only">{caption}</caption>
            <thead className="bg-muted text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">
                  {firstColumn}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  {t("table.calls")}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  {t("table.tokensIn")}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  {t("table.tokensOut")}
                </th>
                <th scope="col" className="px-3 py-2 text-right font-medium">
                  {t("table.cost")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ key, label, line }) => (
                <tr key={key} data-testid={`${testId}-row`} className="border-t border-border">
                  <th scope="row" className="px-3 py-2 font-medium">
                    {label}
                  </th>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatTokens(line.calls, lang)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatTokens(line.prompt_tokens, lang)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatTokens(line.completion_tokens, lang)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatCost(line.cost_usd, lang)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function CostsTab() {
  const { t, i18n } = useTranslation(["costs", "errors", "plan"]);
  const { costs, buildError, paused } = useProjectData();
  const lang = i18n.language;

  if (!costs) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
        {buildError != null ? (
          <p role="alert" data-testid="costs-error" className="text-sm text-destructive">
            {errorMessage(t, buildError)}
          </p>
        ) : (
          <p role="status" className="text-sm text-muted-foreground">
            {t("common:loading")}
          </p>
        )}
      </div>
    );
  }

  const budget = budgetState(costs.spent_usd, costs.budget_usd);
  const percent = budget ? Math.round(budget.ratio * 100) : 0;
  const totalTokens = costs.tokens.prompt + costs.tokens.completion;
  const spent = Number.parseFloat(costs.spent_usd);
  const estimate = costs.estimate_usd === null ? null : Number.parseFloat(costs.estimate_usd);
  const delta =
    estimate !== null && Number.isFinite(estimate) && estimate > 0
      ? Math.round(((spent - estimate) / estimate) * 100)
      : null;

  return (
    <div className="flex h-full min-h-0 flex-col gap-6 overflow-y-auto p-4" data-testid="costs-tab">
      {paused && (
        <div
          role="status"
          data-testid="costs-paused"
          className="flex items-start gap-2 rounded-md border border-destructive p-3 text-sm text-destructive"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <p>{t("paused")}</p>
        </div>
      )}

      <section
        aria-labelledby="budget-title"
        className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 text-card-foreground"
      >
        <h2 id="budget-title" className="flex items-center gap-2 text-base font-semibold">
          <Coins className="h-4 w-4" aria-hidden="true" />
          {t("budget.title")}
        </h2>
        <p className="flex flex-wrap items-baseline gap-x-3">
          <span className="text-2xl font-semibold" data-testid="costs-spent">
            {formatCost(costs.spent_usd, lang)}
          </span>
          <span className="text-sm text-muted-foreground" data-testid="costs-budget">
            {costs.budget_usd === null
              ? t("budget.none")
              : t("budget.of", { budget: formatCost(costs.budget_usd, lang) })}
          </span>
        </p>
        {budget && (
          <>
            <div
              role="progressbar"
              aria-label={t("budget.bar")}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.min(percent, 100)}
              aria-valuetext={t("budget.percent", { percent })}
              data-testid="budget-bar"
              data-level={budget.level}
              className="h-3 w-full overflow-hidden rounded-full bg-muted"
            >
              <div
                className={cn("h-full rounded-full transition-all", LEVEL_FILL[budget.level])}
                style={{ width: `${Math.min(percent, 100)}%` }}
              />
            </div>
            <p
              data-testid="budget-state"
              data-level={budget.level}
              className={cn(
                "text-sm",
                budget.level === "ok" && "text-muted-foreground",
                budget.level === "warning" && "font-medium text-warning",
                budget.level === "danger" && "font-medium text-destructive",
              )}
            >
              {t(`budget.level.${budget.level}`, { percent })}
            </p>
          </>
        )}
      </section>

      <dl className="grid gap-3 sm:grid-cols-3" data-testid="costs-totals">
        <div className="rounded-lg border border-border bg-card p-4 text-card-foreground">
          <dt className="text-xs font-medium text-muted-foreground">{t("totals.tokens")}</dt>
          <dd className="text-xl font-semibold" data-testid="costs-tokens-total">
            {formatTokens(totalTokens, lang)}
          </dd>
          <dd className="text-xs text-muted-foreground" data-testid="costs-tokens-split">
            {t("totals.split", {
              prompt: formatTokens(costs.tokens.prompt, lang),
              completion: formatTokens(costs.tokens.completion, lang),
            })}
          </dd>
        </div>
        <div className="rounded-lg border border-border bg-card p-4 text-card-foreground">
          <dt className="text-xs font-medium text-muted-foreground">{t("totals.estimate")}</dt>
          <dd className="text-xl font-semibold" data-testid="costs-estimate">
            {costs.estimate_usd === null
              ? t("totals.noEstimate")
              : formatCost(costs.estimate_usd, lang)}
          </dd>
        </div>
        <div className="rounded-lg border border-border bg-card p-4 text-card-foreground">
          <dt className="text-xs font-medium text-muted-foreground">{t("totals.actual")}</dt>
          <dd className="text-xl font-semibold">{formatCost(costs.spent_usd, lang)}</dd>
          {delta !== null && (
            <dd className="text-xs text-muted-foreground" data-testid="costs-delta">
              {t(delta > 0 ? "totals.over" : "totals.under", { percent: Math.abs(delta) })}
            </dd>
          )}
        </div>
      </dl>

      <CostTable
        testId="costs-by-task"
        caption={t("table.byTask")}
        firstColumn={t("table.task")}
        lang={lang}
        rows={costs.by_task.map((row) => ({
          key: row.ref ?? "planner",
          label: row.ref ?? t("table.planner"),
          line: row,
        }))}
      />
      <CostTable
        testId="costs-by-model"
        caption={t("table.byModel")}
        firstColumn={t("table.model")}
        lang={lang}
        rows={costs.by_model.map((row) => ({
          key: row.model ?? "unknown",
          label: row.model ?? t("table.unknown"),
          line: row,
        }))}
      />
      <CostTable
        testId="costs-by-role"
        caption={t("table.byRole")}
        firstColumn={t("table.role")}
        lang={lang}
        rows={costs.by_role.map((row) => ({
          key: row.role ?? "unknown",
          label: row.role
            ? t(`plan:task.role.${row.role}`, { defaultValue: row.role })
            : t("table.unknown"),
          line: row,
        }))}
      />
    </div>
  );
}
