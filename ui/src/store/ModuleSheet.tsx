import { ExternalLink } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { modulesApi } from "../api/endpoints";
import { moduleCodeMessage } from "../api/errors";
import type { ModuleEntry } from "../api/types";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "../components/ui/sheet";
import { useFetched } from "../project/useFetched";
import { fitProblems, localizedDescription, stateTone } from "./moduleView";
import { OperationPanel } from "./OperationPanel";
import type { useModuleOperation } from "./useModuleOperation";

type Operation = ReturnType<typeof useModuleOperation>;

function Row({ label, children, testId }: { label: string; children: ReactNode; testId?: string }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-3">
      <dt className="w-32 shrink-0 text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm" data-testid={testId}>
        {children}
      </dd>
    </div>
  );
}

function Secrets({ module }: { module: ModuleEntry }) {
  const { t } = useTranslation("store");
  const { data } = useFetched(
    () => (module.installed ? modulesApi.secrets(module.id) : Promise.resolve({})),
    `${module.id}:${module.installed?.state ?? "none"}`,
  );
  const entries = Object.entries(data ?? {}).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) return null;
  return (
    <Row label={t("sheet.secrets")} testId="module-secrets">
      <ul className="flex flex-col gap-0.5">
        {entries.map(([key, isSet]) => (
          <li key={key} className="flex items-center gap-2">
            <span className="font-mono text-xs">{key}</span>
            <Badge tone={isSet ? "success" : "neutral"}>
              {t(isSet ? "sheet.secretSet" : "sheet.secretUnset")}
            </Badge>
          </li>
        ))}
      </ul>
    </Row>
  );
}

/** One module in detail: what it is, whether it fits, its state, and install / remove. */
export function ModuleSheet({
  module,
  operation,
  onClose,
}: {
  module: ModuleEntry | null;
  operation: Operation;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation(["store", "common"]);
  const { flow } = operation;
  const busy = flow.stage !== "idle" && flow.stage !== "done" && flow.stage !== "failed";
  const state = module?.installed?.state;
  const problems = module ? fitProblems(t, module) : [];

  const close = () => {
    // A running operation goes on in the background (the page shows a banner); anything else ends.
    if (flow.stage !== "running") operation.reset();
    onClose();
  };

  return (
    <Sheet open={module !== null} onOpenChange={(open) => !open && close()}>
      <SheetContent data-testid="module-sheet">
        {module && (
          <>
            <div className="flex flex-col gap-1 pr-8">
              <SheetTitle className="text-lg font-semibold">{module.name}</SheetTitle>
              <SheetDescription className="text-sm text-muted-foreground">
                {localizedDescription(module, i18n.language)}
              </SheetDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={stateTone(state)} data-testid="module-state">
                {t(`store:state.${state ?? "none"}`)}
              </Badge>
              {module.hardware.ok ? (
                <Badge tone="neutral">
                  {module.hardware.variant
                    ? t("store:fit.okVariant", { variant: module.hardware.variant })
                    : t("store:fit.ok")}
                </Badge>
              ) : (
                <Badge tone="warning">{t("store:fit.no")}</Badge>
              )}
            </div>
            {problems.length > 0 && (
              <ul className="text-sm text-muted-foreground" data-testid="module-problems">
                {problems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            )}
            <dl className="flex flex-col gap-2">
              <Row label={t("store:sheet.version")}>{module.version}</Row>
              <Row label={t("store:sheet.license")}>{module.license}</Row>
              <Row label={t("store:sheet.category")}>
                {t(`store:category.${module.category}`, { defaultValue: module.category })}
              </Row>
              {module.provides.length > 0 && (
                <Row label={t("store:sheet.provides")}>{module.provides.join(", ")}</Row>
              )}
              {module.requires.length > 0 && (
                <Row label={t("store:sheet.requires")}>{module.requires.join(", ")}</Row>
              )}
              {module.host_access.length > 0 && (
                <Row label={t("store:sheet.hostAccess")}>{t("store:sheet.dockerSocket")}</Row>
              )}
              {state === "running" &&
                module.web_ui &&
                module.web_ui.public !== false &&
                module.web_ui.path !== "/" && (
                  <Row label={t("store:sheet.open")}>
                    <a
                      href={`${module.web_ui.path.replace(/\/$/, "")}/`}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 font-medium text-primary underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                      data-testid="module-open"
                    >
                      {module.web_ui.path}
                      <ExternalLink className="h-3 w-3" aria-hidden="true" />
                      <span className="sr-only">{t("store:sheet.newTab")}</span>
                    </a>
                  </Row>
                )}
              <Secrets module={module} />
            </dl>

            {module.installed?.error && state === "failed" && (
              <p role="alert" className="text-sm text-destructive" data-testid="module-last-error">
                {t("store:sheet.lastError", {
                  reason: moduleCodeMessage(t, module.installed.error),
                })}
              </p>
            )}

            <OperationPanel
              flow={flow}
              onChoose={operation.choose}
              onConfirmCascade={operation.confirmCascade}
              onStart={() => void operation.start()}
              onCancel={operation.reset}
              onClose={operation.reset}
            />

            {flow.stage === "idle" && (
              <div className="flex gap-2">
                {!module.installed && (
                  <Button
                    onClick={() => operation.begin("install", [module.id])}
                    disabled={!module.hardware.ok || busy}
                    data-testid="module-install"
                  >
                    {t("store:flow.go.install")}
                  </Button>
                )}
                {module.installed && (
                  <Button
                    variant="destructive"
                    onClick={() => operation.begin("uninstall", [module.id])}
                    disabled={state === "installing" || state === "removing"}
                    data-testid="module-uninstall"
                  >
                    {t("store:flow.go.uninstall")}
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
