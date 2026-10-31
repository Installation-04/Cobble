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
] as const;

/** Translate any thrown value into a user-facing message via `errors.<code>`. */
export function errorMessage(t: TFunction, error: unknown): string {
  if (error instanceof NetworkError) return t("errors:network");
  if (error instanceof ApiError && (KNOWN_ERROR_CODES as readonly string[]).includes(error.code)) {
    const fields = Array.isArray(error.params.fields) ? error.params.fields.join(", ") : "";
    return t(`errors:${error.code}`, { ...error.params, fields });
  }
  return t("errors:unknown");
}
