import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { PHASES, type Phase } from "../api/types";
import { cn } from "../lib";

const STEP_KEY: Record<Phase, "interview" | "spec" | "plan" | "ready"> = {
  interview: "interview",
  spec_review: "spec",
  plan_review: "plan",
  ready: "ready",
};

export function PhaseStepper({ phase }: { phase: Phase }) {
  const { t } = useTranslation("chat");
  const current = PHASES.indexOf(phase);
  return (
    <ol
      aria-label={t("stepper.label")}
      data-testid="phase-stepper"
      data-phase={phase}
      className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm"
    >
      {PHASES.map((p, index) => {
        const state = index < current ? "done" : index === current ? "current" : "upcoming";
        return (
          <li
            key={p}
            data-testid={`phase-step-${p}`}
            data-state={state}
            aria-current={state === "current" ? "step" : undefined}
            className="flex items-center gap-2"
          >
            {index > 0 && <span aria-hidden="true" className="h-px w-4 bg-border" />}
            <span
              className={cn(
                "flex items-center gap-1 rounded-full px-2.5 py-0.5",
                state === "current" && "bg-primary font-medium text-primary-foreground",
                state === "done" && "bg-secondary text-secondary-foreground",
                state === "upcoming" && "text-muted-foreground",
              )}
            >
              {state === "done" && <Check className="h-3 w-3" aria-hidden="true" />}
              {t(`stepper.${STEP_KEY[p]}`)}
              {state !== "upcoming" && (
                <span className="sr-only">
                  {t(state === "current" ? "stepper.current" : "stepper.done")}
                </span>
              )}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
