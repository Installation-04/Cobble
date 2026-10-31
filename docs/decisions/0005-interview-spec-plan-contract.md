# 0005 — Interview, spec and plan: contract (step 5)

Status: accepted (v0.1, step 5)

## Flow
A project has a `phase`: `interview` → `spec_review` → `plan_review` → `ready`.
1. **interview**: the user chats with the `planner` role, who asks targeted questions (audience, features, data, platform, constraints). It answers in the user's language (`users.lang`; prompts themselves are English).
2. The user clicks "generate spec": the planner writes a **spec** (Markdown). Phase → `spec_review`. The user approves it or asks for changes (free-text feedback → a new spec version).
3. After approval the user clicks "generate plan": the planner returns a **plan** as JSON. It is validated against the strict schema below (up to 2 automatic retries that feed the validation errors back to the planner). Phase → `plan_review`. A **cost estimate** is stored with the plan and shown before launch.
4. The user approves the plan. Phase → `ready` (the agents start in step 7).

All LLM calls go through the `CostRouter` (role `planner`, with the project's budget). Long calls run in the **worker**: the API enqueues a job on the Redis stream `cobble:jobs` (consumer group `workers`), the worker runs it and publishes progress on the project's event stream.

## Endpoints (under `/api/v1`, owner-scoped, unsafe methods need `X-Requested-With: cobble`)
`ProjectOut` gains `phase`.

| Method + path | Body | Success | Errors |
|---|---|---|---|
| `GET /projects/{id}/messages` | — | `200 [{id, role: "user"\|"assistant", content, created_at}]` oldest first | `404 not_found` |
| `POST /projects/{id}/messages` | `{content}` (1–8000 chars) | `202 {message}` (the stored user message); enqueues the planner reply | `409 wrong_phase` (not `interview`), `409 project_paused`, `422` |
| `POST /projects/{id}/spec/generate` | `{feedback?}` | `202 {}` | `409 wrong_phase` (needs `interview` or `spec_review`), `409 project_paused` |
| `GET /projects/{id}/spec` | — | `200 {version, content, status: "draft"\|"approved", created_at}` (latest) | `404 not_found` |
| `POST /projects/{id}/spec/approve` | — | `200 {…spec}` | `404`, `409 wrong_phase` |
| `POST /projects/{id}/plan/generate` | `{feedback?}` | `202 {}` | `409 wrong_phase` (needs an approved spec and phase `spec_review`/`plan_review`), `409 project_paused` |
| `GET /projects/{id}/plan` | — | `200 {version, status: "draft"\|"approved", plan, estimate, created_at}` (latest) | `404 not_found` |
| `POST /projects/{id}/plan/approve` | — | `200 {…plan}`; phase → `ready` | `404`, `409 wrong_phase` |
| `GET /projects/{id}/stream` | — | `text/event-stream` (see below) | `401`, `404` |

`estimate` = `{tokens: int, cost_usd: "0.00" (string), milestones: [{id, tokens, cost_usd}]}`. Tokens per task: `S` = `COBBLE_ESTIMATE_TOKENS_S` (default 20000), `M` = `COBBLE_ESTIMATE_TOKENS_M` (50000), multiplied by 1.5 for the test-writer and reviewer passes; price = `COBBLE_ESTIMATE_USD_PER_1K_TOKENS` (default 0.002).

## Server-sent events: `GET /projects/{id}/stream`
Events (SSE `event:` name, JSON `data:`, `id:` = Redis stream id so `Last-Event-ID` resumes): `message.created {message}`, `spec.updated {version}`, `plan.updated {version}`, `phase.changed {phase}`, `job.started {kind}`, `job.failed {kind, code}` where `kind` ∈ `reply`, `spec`, `plan` and `code` ∈ `plan_invalid`, `llm_error`, `budget_reached`. A `: ping` comment every 15 s. Per-project Redis stream `cobble:project:{id}:events` (maxlen ~1000). Auth is the session cookie (EventSource, same origin).

## Plan schema (JSON; Pydantic model + exported JSON Schema)
```json
{
  "milestones": [{"id": "M1", "title": "…"}],
  "tasks": [{
    "id": "T-001", "title": "…", "milestone": "M1",
    "depends_on": ["T-000"], "files": ["app/api/todos.py", "tests/test_todos.py"],
    "acceptance": ["POST /api/todos returns 201 …"],
    "tests": "tests/test_todos.py", "size": "S", "role": "backend"
  }]
}
```
Rejected when: a task has no (or an empty) acceptance criterion; `size` is not `S` or `M` (so `L` is rejected); `files` is empty or has absolute / `..` paths; `tests` is empty; ids are duplicated or malformed (`T-\d+`, `M\d+`); `milestone` or a `depends_on` id is unknown; dependencies contain a cycle; there are no milestones or no tasks. `role` ∈ `backend`, `frontend`, `fullstack`, `devops`, `docs`.

## Reference project and cassettes
`reference-projects/todo/` holds the spec of the "to-do list" reference project. Cassettes in `providers/fake-llm/cassettes/` replay the whole scripted flow (interview turns, spec, valid plan, plus an invalid plan for the retry test). Prompts are English and deterministic (key = hash of the exact messages), so changing a prompt means regenerating its cassettes with the helper script documented in `providers/fake-llm/README.md`.
