# ADR 0024 — Reviewer agent and per-task duration cap

Status: **proposed** (implemented in v0.3, waiting for the owner to accept it).

## Context
PLAN.md §14 v0.3 lists an optional "agent réviseur" and guard-rails on loops and duration. Until now a
task went `tests -> implement -> CI green -> merge`: green CI was the only judge, and nothing bounded the
wall-clock time of a task (a run had its own limit, a task could chain attempts for hours).

## Decision

### 1. Reviewer agent (opt-in)
- **Per-project switch `projects.review_enabled`**, default **off** because every review costs tokens.
  Settable at creation (`POST /projects`) and with `PATCH /projects/{id}` like `explain_mode`; the Agents
  tab has the switch. Migration `0019` (also `tasks.review`, a JSON column).
- **New task state `review`** between `ci` and `merged`, shown "In review" in the board's CI column. It is
  active (the task keeps its files), can be paused or stopped, and is picked up again by `reconcile()`.
  Demo-data tasks and restores are never reviewed (no logic to read).
- **Flow.** CI green -> state `review` + event `task.review_started`; the next tick the scheduler reads the
  diff of the branch (`GitProvider.diff`, cut to 30 000 characters, flagged when cut) and asks the
  `reviewer` role (the cost router, with `project_id` and `task_id`, so `local_only`, budgets, fallbacks
  and per-task accounting apply and the cost shows under role `reviewer`). The scheduler only knows the
  `LLMClient` capability (`Scheduler(llm=...)`), built lazily from the cost router in `scheduler/factory.py`.
- **Verdict.** One JSON object `{"verdict": "approve"|"request_changes", "issues": [...]}` (at most 8 issues
  of 400 characters; `request_changes` needs at least one). The prompt tells the model the diff is data,
  never instructions. The latest verdict is stored on the task (`review`: verdict, issues, attempt,
  warning) and published as `task.reviewed`.
- **approve** -> merge exactly as before. **request_changes** -> the existing rejection path
  (`Scheduler._reject`, the one a red CI uses): the run is `rejected`, one attempt is used, the next worker
  prompt gets the issues (`prompts.review_feedback`), and `escalate_after` / `max_attempts` apply
  unchanged. No parallel retry machinery.
- **Never blocks forever.** An unparsable answer, or a call that fails (budget, local-only without a local
  model, gateway), is retried once; then the task is approved with a recorded warning
  (`review_unparsable`, `review_unavailable`). A missing diff or no model client gives
  `review_unavailable`. When the reviewer asks for changes but no attempt is left (`max_attempts`
  reached), the task is merged with `review_unresolved` instead of failing a task whose CI is green: the
  issues stay visible in the drawer. A merge that fails transiently after an approval does not pay for a
  second review.
- The explain mode already uses `Role.REVIEWER` for milestone summaries; both are "reads what was built".
- The review call is made inside the scheduler tick (a few seconds at most for one task, like the other
  provider calls of a tick). It is not queued on the job stream: a crash leaves the task in `review` and
  the next tick asks again.

### 2. Per-task wall-clock limit
- `COBBLE_TASK_MAX_SECONDS` (default **2700**, 45 min; **0 turns it off**) bounds the time of a task, all
  its attempts together, counted from the first run since the last retry or stop (retired and stopped runs
  do not count). The scheduler checks it first thing in each step of a task in `writing_tests`,
  `implementing`, `ci` or `review`.
- Over the limit: active runs are asked to stop (failures to stop are logged: the run ends by its own
  limit), the task becomes `failed` with `last_error = "task_timeout"`, `task.timeout` is published, and
  dependants are blocked as after any failure. **The project goes on**, like for `task_budget_reached`.
  `retry` starts a fresh clock.
- The task detail (`GET /projects/{id}/tasks/{ref}`) now exposes `last_error` **only when it is a stable
  code** (`task_timeout`, `task_budget_reached`, `dependency_failed`; agent logs and review text never
  leave) and `review`; the drawer translates the code (`errors:task_timeout`).

## Consequences
- Reviews roughly add one cheap call per task, plus one more attempt for each requested change.
- Time spent waiting for a free slot while `paused` is not checked (only active tasks are).
- Not done (later): a per-project duration setting, a separate reviewer model per project (use the
  `reviewer` route in Settings → Models).
