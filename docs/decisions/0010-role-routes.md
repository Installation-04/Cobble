# ADR 0010 — Per-role model routes with fallback chains

Status: **proposed** (implemented in v0.3, waiting for the owner to accept it).

## Context
PLAN.md §8: each model role has a fallback chain (local → economical API → strong API). Until now
a role could only be pinned to one model by an environment variable, and a model that could not
answer (refused key, empty balance, rate limit, service down) failed the whole task attempt.

## Decision
- Roles: `planner`, `test-writer`, `worker`, `reviewer` and `escalation` (the model a task moves
  to after `escalate_after` failed attempts).
- The chain of a role is stored in `platform_state.role_routes` (JSON, role → ordered connection
  names, at most four, no duplicates), set by the administrator in Settings → Models or with
  `cobble models route`. It is read at every call: no restart, no gateway reload (the connections
  themselves did not change).
- Precedence for a role: the route set in the product, else `COBBLE_ROLE_MODELS`, else the platform
  default. `escalation`: its route, else `COBBLE_ESCALATION_MODEL`, else the planner's chain.
- The cost router (`router/costs.py`) tries the chain in order. It moves on for statuses that
  mean "this model cannot answer now" (401, 402, 403, 404, 408, 429, 5xx) and for transport errors;
  it does not move on for a request the service rejects (400), which would fail the same way on
  every model. The budget is checked once per call, and every attempt that answers is recorded by
  the gateway with the model that answered.
- A model passed explicitly (escalation) goes first; the role's chain follows as fallbacks.
- The API validates that a route only names connected models (or the built-in default), known
  roles and a short chain; a removed connection left in a chain is simply skipped by the fallback.

## Not decided here (later v0.3 steps)
Presets ("Économique local", "Équilibré"), the local benchmark that picks the worker, free tiers,
"local only" projects, the savings counter.
