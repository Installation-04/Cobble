# ADR 0011 — Local-only projects

Status: **proposed** (implemented in v0.3, waiting for the owner to accept it).

## Context
PLAN.md §17 ("Projet « local seulement »"): a per-project option that forbids every call to an
external API; the router only uses local models. For confidential code (an industrial client,
internal data).

## Decision
- `projects.local_only` (boolean, default false, migration `0012`), set at creation or with
  `PATCH /projects/{id}`, switchable in the Costs tab (Privacy card, FR/EN).
- **Enforced in the cost router, the single door for every model call** (planner jobs and the
  agents' calls through the internal endpoint). For a local-only project the candidates (the role's
  chain, and the explicit escalation model) are filtered to the models served on this machine; the
  rest are never asked. The route, the presets, the escalation and the fallbacks all stay inside
  that set. If nothing is left, the call raises `LocalOnlyUnavailable` *before* anything is sent:
  planner jobs fail with `local_only_unavailable`, the internal endpoint answers 409.
- **"Local" means what the module-manager reports** (`GET /v1/models` → `local`: the models of
  running `llm-backend` modules). The router reads it with a ten-second cache
  (`router/local.py`).
- **Fails closed.** If the list of local models cannot be read (module-manager down, no token), no
  model is local; if the project row cannot be read, the project counts as local-only. The
  platform's built-in `fake` model is not local, so a local-only project does not run in
  development without a local backend.

## Not covered (said in the UI)
Only calls to language models are governed. Package downloads of the generated app (pip, npm
through the agent proxy's allow-list), the Git server and the demos are not changed by this option.
A network-level guarantee (an agent network with no route out at all for these projects) would be
a separate, later step.
