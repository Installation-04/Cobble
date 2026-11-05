import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { modelsApi } from "../api/endpoints";
import type { BenchmarkStatus, ModelListing, RoleRoutes as RoleRoutesData } from "../api/types";
import { Button } from "../components/ui/button";
import { useAsyncAction } from "../project/useAsyncAction";
import { useFetched } from "../project/useFetched";

const POLL_MS = 2000;

/** The worker route with `model` first; the other models stay as fallbacks (within the limit). */
export function workerChainWith(model: string, current: string[], max: number): string[] {
  return [model, ...current.filter((name) => name !== model)].slice(0, max);
}

/** Starts a local benchmark and follows it: models to choose, progress, how it ended. */
function RunBenchmark({
  running,
  status,
  onStarted,
}: {
  running: boolean;
  status: BenchmarkStatus | null;
  onStarted: (next: BenchmarkStatus) => void;
}) {
  const { t } = useTranslation(["models", "errors"]);
  const action = useAsyncAction();
  const listing = useFetched<ModelListing>(() => modelsApi.list(), "benchmark-models");
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<Record<string, boolean>>({});
  const local = (listing.data?.local ?? []).map((m) => m.name);
  const paid = (listing.data?.models ?? []).map((m) => m.name);
  const isChosen = (name: string) => chosen[name] ?? local.includes(name);
  const selected = [...local, ...paid].filter(isChosen);

  async function start() {
    const allowPaid = selected.some((name) => paid.includes(name));
    await action.run(async () => {
      onStarted(await modelsApi.runBenchmark(selected, allowPaid));
      setOpen(false);
    });
  }

  const progress =
    running && status !== null
      ? t("benchmark.running", {
          model: status.model ?? "",
          task: status.task,
          tasks: status.tasks,
          index: status.model_index + 1,
          count: status.models.length,
        })
      : null;

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          size="sm"
          variant="outline"
          onClick={() => setOpen((v) => !v)}
          disabled={running}
          data-testid="bench-run-open"
        >
          {t("benchmark.run.open")}
        </Button>
        {progress !== null && (
          <p role="status" className="text-sm text-muted-foreground" data-testid="bench-progress">
            {progress}
          </p>
        )}
      </div>
      {open && !running && (
        <fieldset
          className="grid gap-2 rounded-md border border-border p-3"
          data-testid="bench-run"
        >
          {local.length + paid.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("benchmark.run.none")}</p>
          ) : (
            <>
              {local.length > 0 && (
                <legend className="text-xs text-muted-foreground">
                  {t("benchmark.run.local")}
                </legend>
              )}
              {local.map((name) => (
                <label key={name} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={isChosen(name)}
                    onChange={(e) => setChosen({ ...chosen, [name]: e.target.checked })}
                    data-testid={`bench-choose-${name}`}
                  />
                  {name}
                </label>
              ))}
              {paid.length > 0 && (
                <p className="mt-1 text-xs text-muted-foreground">{t("benchmark.run.paid")}</p>
              )}
              {paid.map((name) => (
                <label key={name} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={isChosen(name)}
                    onChange={(e) => setChosen({ ...chosen, [name]: e.target.checked })}
                    data-testid={`bench-choose-${name}`}
                  />
                  {name}
                </label>
              ))}
            </>
          )}
          <div className="flex gap-2">
            <Button
              size="sm"
              onClick={() => void start()}
              disabled={action.busy || selected.length === 0}
              data-testid="bench-run-start"
            >
              {t("benchmark.run.start")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
              {t("benchmark.run.close")}
            </Button>
          </div>
        </fieldset>
      )}
      {action.error && (
        <p role="alert" className="text-sm text-destructive" data-testid="bench-run-error">
          {action.error}
        </p>
      )}
    </div>
  );
}

/** Local benchmark: run it from here, see the results and the proposed worker. */
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
  const [status, setStatus] = useState<BenchmarkStatus | null>(null);
  const wasRunning = useRef(false);
  const [finished, setFinished] = useState(false);
  const running = status?.state === "running";

  // Follow the job: once at mount (a run may already be going), then while it runs.
  useEffect(() => {
    let cancelled = false;
    const read = () =>
      void modelsApi
        .benchmarkStatus()
        .then((next) => {
          if (!cancelled) setStatus(next);
        })
        .catch(() => undefined);
    read();
    const timer = running ? setInterval(read, POLL_MS) : undefined;
    return () => {
      cancelled = true;
      if (timer !== undefined) clearInterval(timer);
    };
  }, [running]);

  // A run that ends refreshes the results.
  const { reload } = bench;
  useEffect(() => {
    if (running) {
      wasRunning.current = true;
    } else if (wasRunning.current) {
      wasRunning.current = false;
      setFinished(true);
      reload();
    }
  }, [running, reload]);

  const data = bench.data;

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

  const failure = !running && status?.error ? status.error : null;
  const failureText =
    failure === null ? null : t(`benchmark.failed.${failure in FAILURES ? failure : "unknown"}`);

  return (
    <div className="grid gap-3" data-testid="benchmarks">
      <h3 className="text-sm font-semibold">{t("benchmark.title")}</h3>
      <p className="text-sm text-muted-foreground">{t("benchmark.description")}</p>
      <RunBenchmark running={running} status={status} onStarted={setStatus} />
      {failureText !== null && (
        <p role="alert" className="text-sm text-destructive" data-testid="bench-failed">
          {t("benchmark.failed.title")} {failureText}
        </p>
      )}
      {finished && failure === null && !running && (
        <p role="status" className="text-sm text-muted-foreground" data-testid="bench-finished">
          {t("benchmark.finished")}
        </p>
      )}
      {data !== null && data.results.length === 0 && (
        <p className="text-sm text-muted-foreground">{t("benchmark.empty")}</p>
      )}
      {data !== null && data.results.length > 0 && (
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
                <tr
                  key={r.model}
                  className="border-t border-border"
                  data-testid={`bench-${r.model}`}
                >
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
      )}
      {action.error && (
        <p role="alert" className="text-sm text-destructive">
          {action.error}
        </p>
      )}
    </div>
  );
}

const FAILURES: Record<string, true> = {
  sandbox_unavailable: true,
  docker_unavailable: true,
  sandbox_busy: true,
  sandbox_error: true,
  module_manager_unavailable: true,
  model_error: true,
  interrupted: true,
  internal_error: true,
};
