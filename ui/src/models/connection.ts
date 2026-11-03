import type { ModelProvider } from "../api/types";

export const PROVIDERS: readonly ModelProvider[] = ["openai", "anthropic", "openrouter", "custom"];

/** An example of a model name to type, per provider (the user can type any model of the service). */
export const MODEL_EXAMPLE: Record<ModelProvider, string> = {
  openai: "gpt-4.1-mini",
  anthropic: "claude-haiku-4-5",
  openrouter: "openai/gpt-4.1-mini",
  custom: "llama3",
};

export function isProvider(value: string): value is ModelProvider {
  return (PROVIDERS as readonly string[]).includes(value);
}

/**
 * The name under which the gateway knows a connection: the provider and the model, in the
 * characters the platform accepts (lower case letters, digits, `.`, `_`, `-`; 40 at most).
 * The same provider and model always give the same name, so connecting it again replaces it.
 */
export function connectionName(provider: ModelProvider, model: string): string {
  const slug = `${provider}-${model}`
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^[^a-z0-9]+/, "")
    .replace(/-{2,}/g, "-")
    .slice(0, 40)
    .replace(/[-._]+$/, "");
  return slug;
}

/** What an address starts with (not a translatable text). */
export const URL_EXAMPLE = "https://";
