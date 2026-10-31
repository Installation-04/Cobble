/**
 * Shared constants of the e2e suite: the admin account and the scripted interview.
 * USER_MESSAGES must match, in order, the user turns recorded in the fake-LLM cassettes
 * (providers/fake-llm/cassettes): the key of a cassette is a hash of the exact messages.
 */
import { execSync } from "node:child_process";

export const ADMIN_EMAIL = "admin@example.com";
export const ADMIN_PASSWORD = "correct-horse-battery-staple";

/** Where the setup project saves the logged-in browser state. */
export const STORAGE_STATE = "test-results/.auth/admin.json";

export const PROJECT_NAME = "Todo list";

export const USER_MESSAGES = [
  "I want a simple to-do list app",
  "Just for me, on the web, with tasks I can add, complete and delete",
] as const;

const ACTIVATION_CMD =
  process.env.E2E_ACTIVATION_CMD ??
  "docker compose -f ../core/compose.yml exec -T api python -m cobble.cli activation-link";

/** Path + query of a fresh activation link (works whatever public URL the stack advertises). */
export function activationPath(): string {
  const out = execSync(ACTIVATION_CMD, { encoding: "utf-8" });
  const match = /https?:\/\/\S+/.exec(out);
  if (!match) throw new Error(`no activation URL in command output: ${out}`);
  const url = new URL(match[0]);
  return `${url.pathname}${url.search}`;
}
