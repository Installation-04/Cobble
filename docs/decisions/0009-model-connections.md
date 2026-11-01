# 0009 — Model connections: API keys and the default model

Status: **proposed** (implemented in v0.2, waiting for the owner to accept).

## Context
A v0.1 install can only ever talk to the built-in fake model. Settings has no API key field, and
`COBBLE_DEFAULT_MODEL` / `COBBLE_ROLE_MODELS` in `.env` are not passed to the containers (verified on a
running stack), so the clean-VM validation of v0.1 (step 11) could not have been run as written.
The first-run wizard of v0.2 also needs an optional "API key" step. Cobble needs one supported way to
connect a model service, check that it works, and make it the model that answers.

## Decision
- **A model connection** is a name (what the gateway exposes), a provider (`openai`, `anthropic`,
  `openrouter`, or `custom`: any OpenAI-compatible service at an address), a model name and an API key.
  The administrator creates them in the product (Settings → Models, the wizard, `cobble models`).
- **The key is encrypted by the module-manager's vault** (AES-256-GCM, bound to the connection's name, so
  a copied row cannot be read under another name) and stored in `llm_connections`. No API route, event,
  log line or `repr` returns it: it is registered with the log redactor, and `LlmEntry.api_key` is hidden
  from `repr`. The only place it appears in clear is the gateway's include file.
- **The gateway gets it through the file it already includes** (`models.yaml`, written by the
  module-manager, mounted read-only by LiteLLM, mounted by nothing else). The file is world-readable
  inside that private volume because the gateway's user is not ours and it runs without
  `DAC_OVERRIDE`. A change is applied to the gateway first (restart, wait until healthy) and committed to
  the database only if the gateway accepted it; otherwise the previous file is put back.
- **The default model** is `platform_state.default_model`, read at every call (`ModelPolicy`), so it
  changes with no restart. Unset, the configured `default_model` applies (`fake` in development). The
  first connection becomes the default. Roles pinned with `COBBLE_ROLE_MODELS` keep their model.
- **Testing a key** uses the gateway's own health check for that model (a one-token request made by the
  gateway, not a task: it is not in any project's costs). The result is a stable code (`ok`,
  `auth_failed`, `model_not_found`, `rate_limited`, `unreachable`, `failed`); the provider's text is
  never relayed because it can quote part of the key.
- A key is only accepted for the provider's own address, except `custom`, whose address must be
  `http(s)`, with no credentials in it and no query: a key is never sent to an address chosen under
  another service's name.

## Consequences
- A change restarts the gateway (about 20 s); calls in that window fail and are retried by the clients.
- The key exists in clear in the include file (and in the gateway's memory, as it must). Anyone with
  root on the host can read it, as they can already read `.env` and the volumes. Encryption protects the
  database, its backups and anything that reads rows without the vault key.
- Losing the vault key loses the stored keys (connections must be entered again), like module secrets.
- Per-role models, fallback chains, budgets per model and local-model presets stay in v0.3.

## Rejected
- Forwarding `COBBLE_DEFAULT_MODEL` and provider keys through `.env`/compose: needs a restart and a
  shell, keeps keys in a plain file, and cannot be done by the first-run wizard.
- LiteLLM's own database mode (`STORE_MODEL_IN_DB`): a second database and a second place for secrets;
  the spike showed regenerate-and-restart is enough.
