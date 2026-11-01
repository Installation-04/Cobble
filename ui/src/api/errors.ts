import type { TFunction } from "i18next";
import { ApiError, NetworkError } from "./client";

export const KNOWN_ERROR_CODES = [
  "invalid_credentials",
  "unauthenticated",
  "activation_invalid",
  "activation_expired",
  "already_initialized",
  "too_many_attempts",
  "csrf_failed",
  "not_found",
  "validation_error",
  "wrong_phase",
  "project_paused",
  "plan_invalid",
  "llm_error",
  "budget_reached",
  "wrong_state",
  "queue_unavailable",
  "agent_unavailable",
  "git_unavailable",
  "forbidden",
  "module_manager_unavailable",
  "module_busy",
  "module_needs_choice",
  "module_needs_confirmation",
  "module_conflict",
  "module_unsatisfiable",
  "module_unknown",
  "module_not_installed",
  "module_invalid_choice",
  "module_cycle",
  "module_no_compatible_variant",
  "module_invalid",
  "invalid_request",
  "model_unknown",
  "model_gateway_failed",
] as const;

/** Failure codes of an install or removal step, translated as `errors:module_code_<code>`. */
export function moduleCodeMessage(t: TFunction, code: string): string {
  const key = `errors:module_code_${code}`;
  return t(key, { defaultValue: t("errors:module_code_unknown") });
}

/** Translate any thrown value into a user-facing message via `errors.<code>`. */
export function errorMessage(t: TFunction, error: unknown): string {
  if (error instanceof NetworkError) return t("errors:network");
  if (error instanceof ApiError && (KNOWN_ERROR_CODES as readonly string[]).includes(error.code)) {
    // Lists of names (candidates, cascade, modules, fields) are shown comma separated.
    const params: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(error.params)) {
      params[key] = Array.isArray(value)
        ? value.filter((item) => typeof item !== "object").join(", ")
        : value;
    }
    return t(`errors:${error.code}`, { fields: "", ...params });
  }
  return t("errors:unknown");
}
