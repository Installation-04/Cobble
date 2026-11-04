import { useTranslation } from "react-i18next";
import { modelsApi } from "../api/endpoints";
import type { RoleRoutes as RoleRoutesData } from "../api/types";
import { Button } from "../components/ui/button";
import { useAsyncAction } from "../project/useAsyncAction";
import { useFetched } from "../project/useFetched";

/** The worker route with `model` first; the other models stay as fallbacks (within the limit). */
export function workerChainWith(model: string, current: string[], max: number): string[] {
  return [model, ...current.filter((name) => name !== model)].slice(0, max);
}

/** Local benchmark results (started with `cobble models benchmark`) and the proposed worker. */
export function Benchmarks({
  routes,
  onApplied,
}: {
  routes: RoleRoutesData;
  onApplied: (next: RoleRoutesData) => void;
}) {
  const { t } = useTranslation(["models", "errors"]);
  const bench = useFetched(() => modelsApi.benchmarks(), "model-benchmarks");
  const action = useAsyncAction();
  const data = bench.data;
  if (data === null || data.results.length === 0) return null;

  async function use(model: string) {
    const current = routes.routes.worker ?? routes.effective.worker ?? [];
    await action.run(async () => {
      onApplied(
        await modelsApi.saveRoutes({
          ...routes.routes,
          worker: workerChainWith(model, current, routes.max_chain),
        }),
      );
    });
  }

  return (
    <div className="grid gap-3" data-testid="benchmarks">
      <h3 className="text-sm font-semibold">{t("benchmark.title")}</h3>
      <p className="text-sm text-muted-foreground">{t("benchmark.description")}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1 pr-3">{t("benchmark.model")}</th>
              <th className="py-1 pr-3">{t("benchmark.quality")}</th>
              <th className="py-1 pr-3">{t("benchmark.speed")}</th>
              <th className="py-1" />
            </tr>
          </thead>
          <tbody>
            {data.results.map((r) => (
              <tr key={r.model} className="border-t border-border" data-testid={`bench-${r.model}`}>
                <td className="py-1 pr-3 font-medium">
                  {r.model}
                  {r.model === data.suggested_worker && (
                    <span className="ml-2 text-xs text-muted-foreground">
                      {t("benchmark.suggested")}
                    </span>
                  )}
                </td>
                <td className="py-1 pr-3">
                  {t("benchmark.percent", { n: Math.round(r.quality * 100) })}
                </td>
                <td className="py-1 pr-3">
                  {r.tokens_per_second === null
                    ? t("benchmark.unknown")
                    : t("benchmark.tps", { n: Math.round(r.tokens_per_second) })}
                </td>
                <td className="py-1 text-right">
                  {r.model === data.suggested_worker && (
                    <Button
                      size="sm"
                      onClick={() => void use(r.model)}
                      disabled={action.busy}
                      data-testid={`bench-use-${r.model}`}
                    >
                      {t("benchmark.use")}
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {action.error && (
        <p role="alert" className="text-sm text-destructive">
          {action.error}
        </p>
      )}
    </div>
  );
}
