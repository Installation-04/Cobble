import { AlertTriangle, Coins } from "lucide-react";
import { useTranslation } from "react-i18next";
import { errorMessage } from "../api/errors";
import type { ReactNode } from "react";
import type {
  CostElectricity,
  CostFallbacks,
  CostLine,
  CostSavings,
  ModelPriceLine,
} from "../api/types";
import { FreeBadge, PriceChange } from "../models/Prices";
import { cn } from "../lib";
import { useWorkspace } from "../workspace/WorkspaceProvider";
import { formatCost, formatTokens } from "./format";
import { useAsyncAction } from "./useAsyncAction";
import { useProjectData } from "./ProjectDataProvider";

export type BudgetLevel = "ok" | "warning" | "danger";

export const WARNING_RATIO = 0.8;

/** Above this share of calls answered by a fallback, the tab suggests looking at the routes. */
export const HIGH_FALLBACK_SHARE = 20;

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
  rows: { key: string; label: ReactNode; line: CostLine }[];
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

/** Estimated electricity of local models: its own line, never mixed silently into API spend. */
export function ElectricityCard({
  electricity,
  apiUsd,
  lang,
}: {
  electricity: CostElectricity | undefined;
  apiUsd: string | undefined;
  lang: string;
}) {
  const { t } = useTranslation("costs");
  if (!electricity || electricity.calls === 0) return null;
  return (
    <section
      aria-labelledby="electricity-title"
      data-testid="costs-electricity"
      data-counted={electricity.counts_in_budget ? "yes" : "no"}
      className="flex flex-col gap-1 rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      <h3 id="electricity-title" className="text-sm font-semibold">
        {t("electricity.title")}
      </h3>
      <p className="text-xl font-semibold" data-testid="costs-electricity-amount">
        {formatCost(electricity.usd, lang)}
      </p>
      {apiUsd !== undefined && (
        <p className="text-sm text-muted-foreground" data-testid="costs-api-spend">
          {t("electricity.api", { amount: formatCost(apiUsd, lang) })}
        </p>
      )}
      <p className="text-xs text-muted-foreground">
        {t("electricity.detail", {
          calls: formatTokens(electricity.calls, lang),
          seconds: formatTokens(electricity.seconds, lang),
        })}
      </p>
      <p className="text-xs text-muted-foreground">
        {electricity.counts_in_budget ? t("electricity.counted") : t("electricity.apart")}
      </p>
    </section>
  );
}

/** Free-tier calls (counted as free) and models of this project whose price changed lately. */
function PricesCard({ freeCalls, changes }: { freeCalls: number; changes: ModelPriceLine[] }) {
  const { t } = useTranslation("costs");
  if (freeCalls === 0 && changes.length === 0) return null;
  return (
    <section
      aria-labelledby="prices-title"
      data-testid="costs-prices"
      className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      <h3 id="prices-title" className="text-sm font-semibold">
        {t("prices.title")}
      </h3>
      {freeCalls > 0 && (
        <p className="text-sm text-muted-foreground" data-testid="costs-free-calls">
          {t("prices.freeCalls", { count: freeCalls })}
        </p>
      )}
      {changes.length > 0 && (
        <div
          role="status"
          data-testid="costs-price-changes"
          className="flex items-start gap-2 text-sm font-medium text-warning"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <p>{t("prices.changed")}</p>
            <ul className="font-normal">
              {changes.map((c) => (
                <li key={c.model}>
                  <PriceChange line={c} />
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  );
}

/** Confidential projects: only models served on this machine, nothing leaves. */
function LocalOnlyCard() {
  const { t } = useTranslation(["costs", "errors"]);
  const { project } = useProjectData();
  const { updateProject } = useWorkspace();
  const action = useAsyncAction();
  const on = project.local_only === true;
  return (
    <section
      aria-labelledby="local-only-title"
      data-testid="costs-local-only"
      data-state={on ? "on" : "off"}
      className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      <h3 id="local-only-title" className="text-sm font-semibold">
        {t("localOnly.title")}
      </h3>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={on}
          disabled={action.busy}
          data-testid="local-only-toggle"
          onChange={(e) =>
            void action.run(() => updateProject(project.id, { local_only: e.target.checked }))
          }
        />
        <span>{t("localOnly.label")}</span>
      </label>
      <p className="text-xs text-muted-foreground">
        {on ? t("localOnly.onHelp") : t("localOnly.offHelp")}
      </p>
      {action.error && (
        <p role="alert" className="text-sm text-destructive" data-testid="local-only-error">
          {action.error}
        </p>
      )}
    </section>
  );
}

/** What the cheaper models saved compared with the strongest one doing everything. */
export function SavingsCard({ savings, lang }: { savings: CostSavings | null; lang: string }) {
  const { t } = useTranslation("costs");
  const saved = savings !== null && !savings.saved_usd.startsWith("-") && savings.saved_percent > 0;
  return (
    <section
      aria-labelledby="savings-title"
      data-testid="costs-savings"
      data-state={savings === null ? "unavailable" : saved ? "saved" : "none"}
      className="flex flex-col gap-1 rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      <h3 id="savings-title" className="text-sm font-semibold">
        {t("savings.title")}
      </h3>
      {savings === null ? (
        <p className="text-sm text-muted-foreground">{t("savings.unavailable")}</p>
      ) : saved ? (
        <>
          <p className="text-xl font-semibold text-success" data-testid="costs-saved">
            {t("savings.saved", {
              amount: formatCost(savings.saved_usd, lang),
              percent: savings.saved_percent,
            })}
          </p>
          <p className="text-xs text-muted-foreground">
            {t("savings.detail", {
              model: savings.reference_model,
              reference: formatCost(savings.reference_cost_usd, lang),
              actual: formatCost(savings.actual_cost_usd, lang),
            })}
          </p>
        </>
      ) : (
        <>
          <p className="text-sm text-muted-foreground" data-testid="costs-saved">
            {t("savings.none", { model: savings.reference_model })}
          </p>
          <p className="text-xs text-muted-foreground">
            {t("savings.detail", {
              model: savings.reference_model,
              reference: formatCost(savings.reference_cost_usd, lang),
              actual: formatCost(savings.actual_cost_usd, lang),
            })}
          </p>
        </>
      )}
    </section>
  );
}

/** Where calls were answered by a fallback model: who answered instead of whom, at what cost. */
function FallbackSection({ fallbacks, lang }: { fallbacks: CostFallbacks; lang: string }) {
  const { t } = useTranslation("costs");
  const share =
    fallbacks.total_calls > 0 ? Math.round((fallbacks.calls / fallbacks.total_calls) * 100) : 0;
  return (
    <section
      aria-labelledby="fallbacks-title"
      className="flex flex-col gap-2"
      data-testid="costs-fallbacks"
    >
      <h3 id="fallbacks-title" className="text-sm font-semibold">
        {t("fallbacks.title")}
      </h3>
      <p className="text-sm text-muted-foreground" data-testid="costs-fallbacks-summary">
        {t("fallbacks.summary", {
          calls: formatTokens(fallbacks.calls, lang),
          total: formatTokens(fallbacks.total_calls, lang),
          percent: share,
        })}
      </p>
      {share > HIGH_FALLBACK_SHARE && (
        <p className="text-sm font-medium text-warning" data-testid="costs-fallbacks-hint">
          {t("fallbacks.hint")}
        </p>
      )}
      <div className="overflow-x-auto rounded-lg border border-border">
        <table data-testid="costs-fallbacks-table" className="w-full text-left text-sm">
          <caption className="sr-only">{t("fallbacks.title")}</caption>
          <thead className="bg-muted text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("fallbacks.answeredBy")}
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("fallbacks.insteadOf")}
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                {t("table.calls")}
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                {t("table.cost")}
              </th>
            </tr>
          </thead>
          <tbody>
            {fallbacks.by_model.map((row) => (
              <tr
                key={`${row.model}|${row.fallback_from ?? ""}`}
                data-testid="costs-fallbacks-row"
                className="border-t border-border"
              >
                <th scope="row" className="px-3 py-2 font-medium">
                  {row.model}
                </th>
                <td className="px-3 py-2">{row.fallback_from ?? t("table.unknown")}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatTokens(row.calls, lang)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatCost(row.cost_usd, lang)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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

      <SavingsCard savings={costs.savings ?? null} lang={lang} />
      <ElectricityCard electricity={costs.electricity} apiUsd={costs.api_usd} lang={lang} />
      <PricesCard freeCalls={costs.free_calls ?? 0} changes={costs.price_changes ?? []} />
      <LocalOnlyCard />

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
          label: (
            <>
              {row.ref ?? t("table.planner")}
              {row.ref !== null && row.cap_usd != null && (
                <span
                  className="ml-2 text-xs font-normal text-muted-foreground"
                  data-testid="task-cap"
                >
                  {t("table.cap", { amount: formatCost(row.cap_usd, lang) })}
                </span>
              )}
            </>
          ),
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
          label: (
            <>
              {row.model ?? t("table.unknown")}
              {row.free === true && <FreeBadge />}
            </>
          ),
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
      {costs.fallbacks && costs.fallbacks.calls > 0 && (
        <FallbackSection fallbacks={costs.fallbacks} lang={lang} />
      )}
    </div>
  );
}
