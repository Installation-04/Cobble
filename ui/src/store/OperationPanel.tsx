import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { errorMessage, moduleCodeMessage } from "../api/errors";
import { Button } from "../components/ui/button";
import type { Flow } from "./useModuleOperation";

interface Props {
  flow: Flow;
  onChoose: (capability: string, module: string) => void;
  onConfirmCascade: () => void;
  onStart: () => void;
  onCancel: () => void;
  onClose: () => void;
}

function List({ title, items, testId }: { title: string; items: string[]; testId: string }) {
  if (items.length === 0) return null;
  return (
    <p data-testid={testId} className="text-sm">
      {title} <span className="font-medium">{items.join(", ")}</span>
    </p>
  );
}

/** What the user sees between "Install" and the end: choices, the plan, progress, the outcome. */
export function OperationPanel({
  flow,
  onChoose,
  onConfirmCascade,
  onStart,
  onCancel,
  onClose,
}: Props) {
  const { t } = useTranslation(["store", "errors", "common"]);
  const [picked, setPicked] = useState<string>("");

  if (flow.stage === "idle") return null;

  const stepLabel = (step: string | null) =>
    step ? t(`store:step.names.${step}`, { defaultValue: step }) : "";

  return (
    <section
      aria-label={t("store:flow.label")}
      data-testid="module-flow"
      data-stage={flow.stage}
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 text-card-foreground"
    >
      {flow.stage === "planning" && (
        <p role="status" className="flex items-center gap-2 text-sm">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          {t("store:flow.planning")}
        </p>
      )}

      {flow.stage === "choose" && flow.choice && (
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (picked) onChoose(flow.choice!.capability, picked);
          }}
        >
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-medium">
              {t("store:flow.choose", { capability: flow.choice.capability })}
            </legend>
            {flow.choice.candidates.map((candidate) => (
              <label key={candidate} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="provider"
                  value={candidate}
                  checked={picked === candidate}
                  onChange={() => setPicked(candidate)}
                />
                {candidate}
              </label>
            ))}
          </fieldset>
          <div className="flex gap-2">
            <Button type="submit" disabled={!picked} data-testid="flow-choose">
              {t("store:flow.continue")}
            </Button>
            <Button variant="outline" onClick={onCancel}>
              {t("common:cancel")}
            </Button>
          </div>
        </form>
      )}

      {flow.stage === "confirm" && (
        <div className="flex flex-col gap-3">
          <p role="alert" className="text-sm" data-testid="flow-cascade">
            {t("store:flow.cascade", { modules: flow.cascade.join(", ") })}
          </p>
          <div className="flex gap-2">
            <Button variant="destructive" onClick={onConfirmCascade} data-testid="flow-cascade-ok">
              {t("store:flow.cascadeConfirm")}
            </Button>
            <Button variant="outline" onClick={onCancel}>
              {t("common:cancel")}
            </Button>
          </div>
        </div>
      )}

      {flow.stage === "preview" && flow.plan && (
        <div className="flex flex-col gap-3">
          <p className="text-sm font-medium">{t("store:flow.preview")}</p>
          <ul className="flex flex-col gap-1 text-sm" data-testid="flow-steps">
            {flow.plan.steps.map((step) => (
              <li key={`${step.action}-${step.module}`}>
                {t(`store:flow.action.${step.action}`)}{" "}
                <span className="font-medium">{step.module}</span>
              </li>
            ))}
          </ul>
          <List
            title={t("store:flow.autoAdded")}
            items={flow.plan.auto_added}
            testId="flow-auto-added"
          />
          <List
            title={t("store:flow.autoRemoved")}
            items={flow.plan.auto_removed}
            testId="flow-auto-removed"
          />
          <List
            title={t("store:flow.replaced")}
            items={flow.plan.replaced}
            testId="flow-replaced"
          />
          <div className="flex gap-2">
            <Button
              variant={flow.action === "uninstall" ? "destructive" : "default"}
              onClick={onStart}
              data-testid="flow-start"
            >
              {t(`store:flow.go.${flow.action ?? "install"}`)}
            </Button>
            <Button variant="outline" onClick={onCancel}>
              {t("common:cancel")}
            </Button>
          </div>
        </div>
      )}

      {flow.stage === "running" && (
        <div className="flex flex-col gap-2">
          <p role="status" className="flex items-center gap-2 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            {t("store:flow.running")}
          </p>
          <ol className="flex flex-col gap-1 text-sm" data-testid="flow-progress">
            {flow.steps.map((step, index) => (
              <li key={index} className="flex items-center gap-2">
                {step.ok ? (
                  <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
                ) : (
                  <XCircle className="h-4 w-4 text-destructive" aria-hidden="true" />
                )}
                <span className="font-medium">{step.module}</span>
                <span className="text-muted-foreground">
                  {step.kind === "rollback" ? `${t("store:flow.undoing")} · ` : ""}
                  {stepLabel(step.step)}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {flow.stage === "done" && (
        <div className="flex flex-col gap-3">
          <p role="status" className="flex items-center gap-2 text-sm" data-testid="flow-done">
            <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
            {flow.plan && flow.plan.steps.length === 0
              ? t("store:flow.nothing")
              : t("store:flow.done")}
          </p>
          <Button variant="outline" onClick={onClose} data-testid="flow-dismiss">
            {t("store:flow.dismiss")}
          </Button>
        </div>
      )}

      {flow.stage === "failed" && (
        <div className="flex flex-col gap-3">
          <div role="alert" className="flex flex-col gap-1 text-sm" data-testid="flow-failed">
            {flow.failure ? (
              <>
                <p className="flex items-start gap-2 text-destructive">
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  {t("store:flow.failedAt", {
                    module: flow.failure.module ?? "-",
                    step: stepLabel(flow.failure.step) || "-",
                    reason: moduleCodeMessage(t, flow.failure.code),
                  })}
                </p>
                {(flow.failure.rolled_back?.length ?? 0) > 0 && (
                  <p data-testid="flow-rolled-back">
                    {t("store:flow.rolledBack", { modules: flow.failure.rolled_back?.join(", ") })}
                  </p>
                )}
                {flow.failure.partial && <p>{t("store:flow.partial")}</p>}
              </>
            ) : (
              <p className="text-destructive">{errorMessage(t, flow.error)}</p>
            )}
          </div>
          <Button variant="outline" onClick={onClose} data-testid="flow-dismiss">
            {t("store:flow.dismiss")}
          </Button>
        </div>
      )}
    </section>
  );
}
