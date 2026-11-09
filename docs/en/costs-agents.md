# Agents and costs API

All routes are under `/api/v1`, need the session cookie, only see the caller's projects (`404`
otherwise), and `POST` routes need the `X-Requested-With: cobble` header.

## Following and controlling a task

| Route | Answer |
|---|---|
| `GET /projects/{id}/tasks/{ref}/logs?offset=N` | `200 text/plain`, the latest run's log from `offset`; header `X-Next-Offset` is the offset to ask next. Falls back to the stored log tail when the agent service no longer has the run. Poll every 2 s while the task runs. |
| `GET /projects/{id}/tasks/{ref}/diff` | `200 {"diff": "...", "truncated": false}`: unified diff of the task branch against `main` (cut at 200 KB, then `truncated` is true). Empty before the first push. `503 git_unavailable` if the git server cannot be reached. |
| `POST .../pause` `.../resume` `.../stop` `.../retry` | `200` with the task (same shape as the task list). `409 wrong_state` (params `{state}`) when not allowed; `503 agent_unavailable` when a run must be stopped and the agent service cannot be reached (nothing changed, try again). |

Each change publishes `task.updated` on the project stream. Every action is idempotent.

| Task state | pause | resume | stop | retry |
|---|---|---|---|---|
| `todo` | `paused` | no-op | `stopped` | no-op |
| `writing_tests`, `implementing`, `ci`, `review` | `paused` | no-op | `stopped` | 409 |
| `paused` (held by you) | no-op | continues | `stopped` | `todo` (409 while a run is active) |
| `paused` (waiting for a slot or budget) | held | no-op | `stopped` | `todo` |
| `stopped` | 409 | 409 | no-op | `todo` |
| `failed`, `blocked` | 409 | 409 | 409 | `todo` |
| `merged` | 409 | 409 | 409 | 409 |

- A paused task is left alone by the scheduler; a run already running keeps going but is only
  followed again after `resume` (which puts the task back in `writing_tests`, `implementing` or
  `ci`, or lets the scheduler start the next run).
- `stop` ends the active run and the task is never restarted until `retry`.
- `retry` resets attempts, escalation and the last error, keeps the branch, marks earlier runs
  `retired` (they stay visible but no longer count as attempts) and frees the tasks that were
  blocked only because of this one.

### Code review and task time limit (ADR 0024)

- **Reviewer agent** (off by default, it costs tokens): `review_enabled` on `POST /projects` and
  `PATCH /projects/{id}`, and a switch in the Agents tab. When CI is green the task moves to `review`
  (`task.review_started`); a reviewer reads the task's acceptance criteria and diff and answers
  `approve` (merge) or `request_changes` with a short list of issues (`task.reviewed`). Requested
  changes start another attempt like a red CI would (the issues are added to the worker's prompt;
  `COBBLE_ESCALATE_AFTER` and `COBBLE_MAX_ATTEMPTS` apply). An unreadable verdict is asked again once,
  then the task is approved with a warning (`review_unparsable`, `review_unavailable`; when no attempt
  is left, `review_unresolved`). The latest verdict is in `GET /projects/{id}/tasks/{ref}` as
  `review` `{verdict, issues, attempt, warning}`. Its cost shows under the role `reviewer`; the
  `reviewer` route in Settings → Models picks the model and `local only` is honoured.
- **Time limit per task**: `COBBLE_TASK_MAX_SECONDS` (default 2700 = 45 min, `0` turns it off) bounds a
  task, all its attempts together. Over it the task is stopped and `failed` with `last_error`
  `task_timeout` (exposed in the task detail, translated in the drawer, event `task.timeout`); the
  project goes on and `retry` starts a fresh clock.

## Costs

`GET /projects/{id}/costs`:

```json
{
  "budget_usd": "5.00", "spent_usd": "0.17651235",
  "tokens": {"prompt": 1711, "completion": 708},
  "estimate_usd": "1.50",
  "by_task":  [{"ref": "T-002", "cost_usd": "0.0215", "prompt_tokens": 440, "completion_tokens": 100, "calls": 3},
               {"ref": null, "cost_usd": "0.15", "prompt_tokens": 1200, "completion_tokens": 600, "calls": 3}],
  "by_model": [{"model": "strong", "cost_usd": "0.17", "prompt_tokens": 1500, "completion_tokens": 630, "calls": 3}],
  "by_role":  [{"role": "planner", "cost_usd": "0.15", "prompt_tokens": 1200, "completion_tokens": 600, "calls": 2}]
}
```

Money is a string with 2 to 8 decimals. `ref: null` groups the calls without a task (planning).
`by_task` is sorted by task number (null last); `by_model` and `by_role` by decreasing cost.
`estimate_usd` is the estimate of the approved plan (`null` if none). `budget_usd` is `null`
when unlimited.

`GET /costs` lists the caller's projects: `[{"project_id", "name", "spent_usd", "budget_usd", "status"}]`.

`GET /models/prices` (any signed-in user): `{"prices": [{"model", "prompt_per_million_usd",
"completion_per_million_usd", "free", "changed", "previous_prompt_per_million_usd",
"previous_completion_per_million_usd", "changed_at"}], "change_window_days": 14}`, changed models first.
It reads the gateway's prices and remembers the last one seen, so a provider's price change shows up
as `changed` for 14 days (ADR 0013). Nothing is reordered: it is a warning.

The costs report also has `free_calls` (calls to free-tier models, counted as free: zero cost),
`by_model[].free`, and `price_changes` (recent changes among the models the project used). **Free
tiers**: a model priced at zero by the gateway, or an OpenRouter `:free` model. Local models are not
free tiers. Provider caveat: free tiers have their own rate limits and terms (training on your
requests, offer changes); Cobble cannot check them for you, and a `local only` project avoids them
altogether. On a 429 the next model of the route answers and the limited one is tried last for 30 s
(doubling up to 10 min).

### Electricity and per-task caps (ADR 0021)

`GET`/`PUT /api/v1/settings/costs` (admin; also Settings → Models and `cobble costs`):
`electricity_price_kwh_usd`, `electricity_watts`, `electricity_counts_in_budget` and
`task_budget_multiplier`. With a price and a power draw set, each call to a model served on this machine
records `electricity_usd = watts x answer seconds / 3.6e6 x price`. **It is an estimate, not a
measure.** The costs report gets `api_usd` (what providers charged) and `electricity` (`usd`,
`seconds`, `calls`, `counts_in_budget`) on their own line; `spent_usd` includes the electricity only
when `electricity_counts_in_budget` is on (then the project budget and the savings counter include it
too). Each `by_task` line has `cap_usd`: a task may spend its multiple (default 3) of its estimate, at
least 0.05 USD; 0 turns the cap off. Over its cap a task's calls are refused (HTTP 402
`task_budget_reached`) while the project goes on. A call already running when a cap is crossed still
completes: a project or a task can overshoot by one call.

## End-of-project report

`GET /projects/{id}/report` (the project's "Report" tab) summarises the project. It also works
before the end: `project.finished` is then false and the figures are those of the moment.

```json
{
  "project": {"id": "…", "name": "Todo", "phase": "done", "status": "active", "finished": true},
  "span": {"started_at": "…", "ended_at": "…", "duration_seconds": 11100},
  "build": {
    "milestones": [{"ref": "M1", "title": "…", "status": "validated", "validated_at": "…",
                    "tasks_total": 4, "tasks_done": 3, "tasks_failed": 1}],
    "milestones_validated": 1,
    "tasks": {"total": 4, "done": 3, "failed": 1, "escalated": 2, "attempts": 6}
  },
  "costs": {
    "spent_usd": "0.17", "budget_usd": "5.00", "estimate_usd": "1.50",
    "budget_used_percent": 3, "estimate_delta_percent": -89,
    "tokens": {"prompt": 1711, "completion": 708},
    "savings": {"reference_model": "…", "saved_usd": "…", "saved_percent": 92, "…": "…"},
    "by_model": [], "by_role": [], "fallbacks": {"calls": 0, "total_calls": 0, "by_model": []}
  }
}
```

`span.ended_at` is the last activity (last task changed or last milestone validated).
`costs.savings` is the Costs tab's savings counter (`null` when the strongest model has no
price). `GET /projects/{id}/report?format=md` returns the same report as a Markdown download
(`Content-Disposition: attachment`) in the user's language (`fr` or `en`). Any other `format`
gives `422`. The report costs a fixed number of SQL queries.
