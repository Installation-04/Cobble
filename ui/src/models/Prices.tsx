import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { modelsApi } from "../api/endpoints";
import type { ModelPriceLine } from "../api/types";
import { useFetched } from "../project/useFetched";

/** A free-tier model: zero price or a provider's free offer (limits and terms still apply). */
export function FreeBadge() {
  const { t } = useTranslation("models");
  return (
    <span
      data-testid="free-badge"
      className="ml-2 rounded-full bg-success px-2 py-0.5 text-xs font-medium text-success-foreground"
    >
      {t("prices.free")}
    </span>
  );
}

/** "model: input 3 → 4, output 15 → 15", per million tokens. */
export function PriceChange({ line }: { line: ModelPriceLine }) {
  const { t } = useTranslation("models");
  return (
    <span data-testid={`price-change-${line.model}`}>
      {t("prices.change", {
        model: line.model,
        oldIn: line.previous_prompt_per_million_usd ?? "?",
        newIn: line.prompt_per_million_usd ?? "?",
        oldOut: line.previous_completion_per_million_usd ?? "?",
        newOut: line.completion_per_million_usd ?? "?",
      })}
    </span>
  );
}

/** Settings → Models: the prices last seen, a warning when one changed, the free tiers. */
export function Prices() {
  const { t } = useTranslation(["models"]);
  const prices = useFetched(() => modelsApi.prices(), "model-prices");
  const lines = prices.data?.prices ?? [];
  if (lines.length === 0) return null;
  const changed = lines.filter((l) => l.changed);
  const free = lines.some((l) => l.free);
  return (
    <div className="grid gap-3" data-testid="prices">
      <h3 className="text-sm font-semibold">{t("prices.title")}</h3>
      {changed.length > 0 && (
        <div
          role="status"
          data-testid="price-warning"
          className="flex items-start gap-2 text-sm font-medium text-warning"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div>
            <p>{t("prices.changed", { days: prices.data?.change_window_days ?? 14 })}</p>
            <ul className="font-normal">
              {changed.map((c) => (
                <li key={c.model}>
                  <PriceChange line={c} />
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 pr-3">{t("prices.model")}</th>
              <th className="py-1 pr-3">{t("prices.input")}</th>
              <th className="py-1">{t("prices.output")}</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.model} className="border-t border-border" data-testid={`price-${l.model}`}>
                <td className="py-1 pr-3 font-medium">
                  {l.model}
                  {l.free && <FreeBadge />}
                </td>
                <td className="py-1 pr-3 tabular-nums">{l.prompt_per_million_usd ?? "—"}</td>
                <td className="py-1 tabular-nums">{l.completion_per_million_usd ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">{t("prices.unit")}</p>
      {free && (
        <p className="text-xs text-muted-foreground" data-testid="free-terms">
          {t("prices.terms")}
        </p>
      )}
    </div>
  );
}
