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
| `writing_tests`, `implementing`, `ci` | `paused` | no-op | `stopped` | 409 |
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
