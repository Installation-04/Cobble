# ADR 0013 — Price table with change warnings, and free tiers

Status: **proposed** (implemented in v0.3, waiting for the owner to accept it).

## Context
PLAN.md §17 ("Prix à jour", "Paliers gratuits"): keep model prices current, warn when one changes,
and use the free models some providers offer (for example OpenRouter's `:free` models) while
respecting their rate limits and terms.

## Decision
- **The gateway stays the only source of prices** (`/model/info`, as for the savings counter). New
  table `model_prices` (migration `0014`) only **remembers the last price seen** per model, with the
  previous one and the date of the change. It is updated when the Costs report or
  `GET /api/v1/models/prices` is read (the gateway answer is cached five minutes) and by
  `cobble models prices`. No background job.
- **A change is a warning, never an action.** The router does not reorder or replace a model in an
  owner's chain because of a price: the owner's routes are theirs. Warnings last 14 days
  (`CHANGE_WINDOW`) and show in Settings → Models (Prices) and in the project's Costs tab (for the
  models that project used). "Prefer the cheapest model that is good enough" stays the owner's
  decision, helped by presets and the benchmark.
- **Free = a price of zero from the gateway, or a free-tier name**: `…:free` (OpenRouter), or a
  connection named `openrouter-…-free` (a connection name cannot contain `:`). A model served on this
  machine costs nothing too but is **not** a free tier (it uses your hardware and electricity): local
  models are never marked free. A free-tier model with no price is recorded at zero.
- **Free calls are counted as free**: they cost 0 in `llm_calls`; the Costs report adds
  `free_calls` and `by_model[].free`, and the UI shows a "free" badge.
- **Rate limits.** The existing fallback chain already hands over on HTTP 429. On top, the cost router
  remembers the refusal (`RateLimitBackoff`, in memory, shared by the process): the model is tried
  **after the others** for 30 s, doubling at each consecutive 429 up to 10 min, and forgotten at its
  first answer. It is delayed, not removed: if nothing else is left it is still tried. Not persisted:
  a restart forgets it, which at worst costs one more 429.

## Terms caveat (also in the UI and the docs)
Free tiers have provider-specific rate limits and terms: some use the requests to train models, may
change or end the offer, and are not suitable for confidential code. Cobble cannot know a provider's
terms; the owner must read them. For confidential code use a *local only* project (ADR 0011).

## Not done
No automatic price import from provider websites (the gateway's table is the source); no automatic
choice of the cheapest model; no `Retry-After` handling (the gateway does not pass it on); the
"free" mark of a model the gateway cannot price relies on its name.
