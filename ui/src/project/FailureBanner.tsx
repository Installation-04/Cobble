import { AlertTriangle, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { JobKind } from "../api/types";
import { useProjectData } from "./ProjectDataProvider";

const KNOWN_CODES = [
  "plan_invalid",
  "llm_error",
  "budget_reached",
  // Start job (ADR 0006)
  "repo_error",
  "ci_error",
  "no_plan",
  "wrong_phase",
  "internal_error",
  "scheduler_unavailable",
];

/** Last failed job (job.failed), with its translated error code. */
export function FailureBanner({ kinds }: { kinds?: JobKind[] }) {
  const { t } = useTranslation(["chat", "errors"]);
  const { failure, clearFailure } = useProjectData();
  if (!failure || (kinds && !kinds.includes(failure.kind))) return null;
  const key = KNOWN_CODES.includes(failure.code) ? failure.code : "unknown";
  return (
    <div
      role="alert"
      data-testid="job-failed"
      data-code={failure.code}
      className="flex items-start gap-2 rounded-md border border-destructive p-3 text-sm text-destructive"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-medium">
          {t("chat:failure.title", { job: t(`chat:failure.job.${failure.kind}`) })}
        </p>
        <p>{t(`errors:job_${key}`)}</p>
      </div>
      <button
        type="button"
        onClick={clearFailure}
        aria-label={t("chat:failure.dismiss")}
        data-testid="job-failed-dismiss"
        className="rounded-sm p-1 hover:opacity-80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
