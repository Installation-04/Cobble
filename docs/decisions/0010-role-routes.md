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

## Savings counter (v0.3 step 4)
- **Definition:** the project's real cost against the cost of the same tokens priced at the
  reference model, `saved = tokens x reference prices - real cost`, and its percentage of the
  reference cost. Negative values are shown as "no saving"; they are never clamped or hidden.
- **Reference model:** the first model of the `escalation` route (by the existing precedence:
  route, `COBBLE_ESCALATION_MODEL`, the planner's chain): the strongest the owner configured.
- **Prices:** from the gateway's `GET /model/info` (`router/prices.py`: the effective
  `model_info` price, else the custom price in `litellm_params`; half a price is no price), asked
  at most every five minutes and never raising. No price (unknown model, unreachable gateway) means
  the card says "not available": Cobble does not invent a figure. Checked against the pinned
  LiteLLM v1.106.6.
- **When:** computed each time the report is read, with the current reference model and price;
  nothing is stored, so changing the escalation route changes the comparison for past calls too.
  The up-to-date price table of PLAN.md §17 is a separate, later item.

## Visibility of fallbacks (v0.3 step 3)
- Nothing is stored for a failed attempt (no tokens, no cost). The call that finally answers
  records `llm_calls.fallback_from` (the first model that could not) and `fallbacks` (how many
  failed before it), migration `0011`. The costs report adds `fallbacks`: calls answered by a
  fallback, total calls, and per (answering model, failed model) the calls and cost; the Costs tab
  shows it only when there is one, and suggests checking the routes above 20 % of calls.
- The gateway answers HTTP 400 `Invalid model name` when a model is not configured (a connection
  removed while a route still names it). That is about *this* model, not the request, so it now
  hands over like the 401/402/403/404/408/429/5xx statuses; any other 400 still does not.

## Presets and models served here (v0.3 step 2)
- The models of running `llm-backend` modules are listed next to the connections (`local` in the
  listing: name, gateway model, module) and a route may name them; they are free and need no key.
- A **preset** is a template over three slots, `local`, `cheap` and `strong`, in the pure module
  `router/presets.py`. The platform has no price or quality table yet, so it never guesses which
  connected model is strong or cheap: the owner picks (defaults: first local model; the platform
  default for `strong`; `cheap` falls back to `strong`).
  - `economical-local`: planner `[strong, cheap]`, test-writer / worker / reviewer
    `[local, cheap]`, escalation `[strong]`. Needs `local` and `strong`.
  - `balanced`: planner / reviewer / escalation `[strong]`, test-writer / worker `[cheap, strong]`.
    Needs `strong`.
- Applying a preset replaces the routes of all five roles (stored in the same `role_routes`);
  a preset missing a required slot is unavailable and changes nothing. Chains are deduplicated and
  capped at four.

## Not decided here (later v0.3 steps)
The local benchmark that picks the worker, up-to-date prices, free tiers, "local only" projects,
the savings counter.
