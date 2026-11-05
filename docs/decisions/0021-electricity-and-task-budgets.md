# ADR 0021 — Electricity of local models, per-task budgets, model-aware estimate

Status: **proposed** (implemented in v0.3, waiting for the owner to accept it).

## Context
PLAN.md §14 v0.3: "Routeur de coûts complet (rôles, chaînes de repli, escalade, budgets, estimation,
électricité)" and the criterion "aucun agent ne dépasse son budget". Three gaps remained: local models
looked free, only the project had a cap (one runaway task could eat it), and the plan estimate used one
flat price whatever models the routes name.

## Decision

### 1. Electricity of local models (an estimate)
- The owner sets, in Settings → Models (admin), with `cobble costs` or `PUT /api/v1/settings/costs`: a
  **price per kWh** (USD) and the **power draw in watts** of the machine while a local model generates.
  Stored in `platform_state` (migration `0018`). Unset or 0 = no electricity cost (the previous behaviour).
- `llm_calls` gets `duration_ms` (time the gateway took to answer, measured around the HTTP request) and
  `electricity_usd`. For a call to a model served on this machine (the module-manager's list, as for
  local-only projects) when both settings are set:
  `electricity_usd = watts x seconds / 3.6e6 x price_per_kwh` (`Decimal`). Remote models get `NULL`.
  `cost_usd` is untouched: it stays what providers charged. Old calls keep `NULL` (never invented).
- **It is an estimate, not a measure**: the real draw depends on the model, the load and the hardware, and
  the duration includes queueing and network on the machine. The UI, the CLI and the report say so.
- **Never mixed silently into API spend.** The Costs tab and the report show it on its own line
  (`electricity.usd`, `seconds`, `calls`) next to `api_usd`. A setting **"count the electricity in the
  amount spent and in the budget"** (default off) decides whether it enters `spent_usd`, the project
  budget check (`budget.spent`), the global costs list and the "actual" side of the savings counter. With
  it on, savings stay honest (a local model is not shown as free); with it off the savings counter
  compares API spend only, and the electricity line remains visible.
- Changing the price later does not rewrite history: each call stores the estimate made at the time.

### 2. Per-task budget
- Cap of a task = `max(floor, multiplier x estimate of a task of its size)`. Default multiplier 3
  (`COBBLE_TASK_BUDGET_MULTIPLIER`), floor 0.05 USD (`COBBLE_TASK_BUDGET_FLOOR_USD`, so a free or tiny
  estimate does not block a task costing cents). The owner overrides the multiplier in the same settings
  (`task_budget_multiplier`; 0 turns the cap off). The estimate of a size comes from the approved plan
  (`estimate.size_cost_usd`); a plan stored before that falls back to the flat settings.
- Checked by `BudgetService.ensure_can_spend(project_id, task_id)` before every call the router makes, on
  the sum of the task's calls across all its attempts and escalations (electricity included when it is
  counted). Over the cap: `TaskBudgetExceeded` (a `BudgetExceeded`), HTTP 402 `task_budget_reached` on the
  internal LLM endpoint, `task.budget_reached` project event (once), and `tasks.last_error =
  "task_budget_reached"`. **The project is not paused**: other tasks go on. The agent's run fails; the
  scheduler (not changed here) retries up to `max_attempts` — each retry is refused at once, for free —
  and then fails the task. The failure text and the error banner have an i18n message
  (`task_budget_reached`). Raising the multiplier lets the owner retry.
- The Costs tab shows each task's cap next to its cost.
- **Honest limit** (same as the project budget): a call already in flight when the cap is crossed still
  completes, so a task can overshoot by one call. The scheduler's `last_error` may be overwritten by the
  agent failure text of the run that hit the 402; the 402 code is in that text.

### 3. Model-aware estimate
- `estimate_plan` splits the base tokens of a task between worker (1.0), test-writer (0.25) and reviewer
  (0.25) (the old 1.5 multiplier) and prices each at the first model of that role's chain, using the
  gateway's per-token prices (75 % prompt / 25 % completion). A local or free model costs 0; a role whose
  model has no known price uses the flat configured price. Output shape unchanged, plus
  `size_cost_usd`. Without prices (no `role_price` given) the result is identical to before.
- Escalation is not in the estimate (it is the exception); electricity is not either.
- Comparing estimate and actual stays what the report already shows (`estimate_delta_percent`).

## Consequences
- New columns: `llm_calls.duration_ms`, `llm_calls.electricity_usd`, `platform_state.electricity_*`,
  `task_budget_multiplier`. Migration `0018` is tested up and down.
- Not done: failing the task in the scheduler at the first refusal (the scheduler is outside this change),
  measuring real power draw, per-model watts.
