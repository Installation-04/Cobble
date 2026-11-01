import { useTranslation } from "react-i18next";
import type { ModulePack } from "../api/types";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "../components/ui/sheet";
import { packProblems } from "./moduleView";
import { OperationPanel } from "./OperationPanel";
import type { useModuleOperation } from "./useModuleOperation";

type Operation = ReturnType<typeof useModuleOperation>;

export function packText(pack: ModulePack, field: "name" | "description", lang: string): string {
  const value = pack[field];
  return (lang === "fr" ? value.fr : value.en) || value.en || value.fr || "";
}

/** One starter pack: what it contains, whether it fits, and installing all of it in one go. */
export function PackSheet({
  pack,
  operation,
  onClose,
}: {
  pack: ModulePack | null;
  operation: Operation;
  onClose: () => void;
}) {
  const { t, i18n } = useTranslation(["store", "common"]);
  const { flow } = operation;
  const busy = flow.stage !== "idle" && flow.stage !== "done" && flow.stage !== "failed";

  const close = () => {
    if (flow.stage !== "running") operation.reset();
    onClose();
  };

  return (
    <Sheet open={pack !== null} onOpenChange={(open) => !open && close()}>
      <SheetContent data-testid="pack-sheet">
        {pack && (
          <>
            <div className="flex flex-col gap-1 pr-8">
              <SheetTitle className="text-lg font-semibold">
                {packText(pack, "name", i18n.language)}
              </SheetTitle>
              <SheetDescription className="text-sm text-muted-foreground">
                {packText(pack, "description", i18n.language)}
              </SheetDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {pack.recommended && <Badge tone="primary">{t("store:packs.recommended")}</Badge>}
              {pack.installed ? (
                <Badge tone="success">{t("store:packs.installed")}</Badge>
              ) : (
                pack.installed_modules.length > 0 && (
                  <Badge tone="neutral">
                    {t("store:packs.progress", {
                      count: pack.installed_modules.length,
                      total: pack.modules.length,
                    })}
                  </Badge>
                )
              )}
              {!pack.fit.ok && <Badge tone="warning">{t("store:fit.no")}</Badge>}
            </div>
            {!pack.fit.ok && (
              <ul className="text-sm text-muted-foreground" data-testid="pack-problems">
                {packProblems(t, pack).map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            )}
            <dl className="flex flex-col gap-2">
              <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-3">
                <dt className="w-32 shrink-0 text-xs text-muted-foreground">
                  {t("store:packs.modules")}
                </dt>
                <dd className="text-sm" data-testid="pack-modules">
                  {pack.modules.join(", ")}
                </dd>
              </div>
            </dl>

            <OperationPanel
              flow={flow}
              onChoose={operation.choose}
              onConfirmCascade={operation.confirmCascade}
              onStart={() => void operation.start()}
              onCancel={operation.reset}
              onClose={operation.reset}
            />

            {flow.stage === "idle" && !pack.installed && (
              <div className="flex gap-2">
                <Button
                  onClick={() => operation.begin("install", pack.modules, pack.id)}
                  disabled={!pack.fit.ok || busy}
                  data-testid="pack-install"
                >
                  {t("store:packs.install")}
                </Button>
              </div>
            )}
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
