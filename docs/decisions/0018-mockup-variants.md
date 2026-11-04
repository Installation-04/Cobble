# ADR 0018 — Mockup variants

Status: **proposed** (implemented in v0.3, waiting for the owner to accept it).

## Context
PLAN.md §17 ("Variantes de maquette"): for a few cents the planner proposes 2 or 3 different
mockups and the user picks one **before** the code starts. Fixing a mockup costs far less than
fixing code (PLAN.md §5).

How the flow works today (`orchestrator/service.py`, `api/routes_planning.py`): interview →
spec (`spec_review`, the user approves it) → plan (`plan_review`, approved) → `ready` → build.
Planner jobs (`reply`, `spec`, `plan`) call the model only through `PlannerService._chat`, which
goes through the cost router (role `planner`, project accounting) and, inside a job, through the
step checkpoints of ADR 0016.

## Decision
The smallest thing that fits: a fourth planner job, `mockups`, between spec approval and plan
generation. No new phase.

- **Optional per project, off by default**: `projects.mockups_enabled` (migration `0017`),
  switched with `PATCH /projects/{id}` (`mockups_enabled`) from the Plan tab. Off: nothing
  changes, the plan prompt is byte-for-byte the same as before (cassettes unaffected).
- **Job `mockups`** (`PlannerService.generate_mockups`): allowed in `spec_review` and
  `plan_review` once the spec is approved. One planner call (`_chat(Role.PLANNER, ..., step)`),
  asking for 2 or 3 variants as JSON `{title, summary, wireframe}`; one automatic retry when the
  answer is invalid, then `job.failed` with code `mockups_invalid`. Cost: one short call, billed
  to the project like any planner call, and checkpointed so a replay after a crash is not paid
  twice. The job accepts `count` (2 or 3, default 3) and optional `feedback`.
- **Storage**: table `mockup_variants` (`project_id`, `position`, `title`, `summary`,
  `wireframe`, `chosen`). A new batch replaces the previous one, and with it the previous choice.
  Event `mockups.updated` (new batch or new choice).
- **API**: `GET /projects/{id}/mockups`, `POST /projects/{id}/mockups/generate` (202, body
  `{count?, feedback?}`), `POST /projects/{id}/mockups/{variant_id}/choose` (exactly one chosen).
- **The choice feeds the plan**: when the option is on and a variant is chosen,
  `plan_messages(..., mockup=...)` adds it to the plan prompt ("front end tasks must follow its
  layout"). `POST /plan/generate` answers `409 mockup_choice_required` while the option is on and
  nothing is chosen (turn the option off to skip).
- **Safety: a mockup is text, never code.** The prompt asks for an ASCII wireframe, not HTML.
  Whatever the model sends is stored as plain text after removing control characters and
  capping sizes (title 120 characters, summary 600, wireframe 30 lines of 80 characters).
  The UI renders it as an escaped text node inside `<pre>` (React escapes it); there is no
  `dangerouslySetInnerHTML`, no iframe and no script path, so a `<script>` in a wireframe is
  displayed, not run. A rendered HTML mockup would need a sandboxed iframe with CSP and was
  left out on purpose.

## Consequences
- Wireframes are rough. Good enough to compare layouts; a pixel mockup is a later idea.
- The variants belong to the project, not to a spec version: changing the spec leaves them in
  place; regenerate to refresh.
- Local-only projects work like any planner call (the router filters models).

## Migration note
`0017` declares `down_revision = "0015"` because it was written in parallel with `0016`
(summaries). When both are merged, set it to `"0016"`.
