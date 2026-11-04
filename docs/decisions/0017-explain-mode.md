# 0017 — "Explain me" mode

Status: accepted (v0.3, "Mode « Explique-moi »", PLAN.md section 17).

## Context

Beginners learn by seeing what was built and why. At each milestone the platform can write a
plain-language summary in the user's language (PLAN.md section 8, "agents answer in the user's
language"). It costs tokens, so it must be opt-in.

## Decision

- **Switch**: `projects.explain_mode` (boolean, default false), set at creation or with
  `PATCH /api/v1/projects/{id}` `{"explain_mode": true}`; toggle in the Demo tab.
- **Storage**: `milestones.explanation` (text, nullable). Migration `0016` adds both columns
  (tested up and down, and for drift against the models). A milestone that is re-opened (comment,
  revert) loses its summary: it described a build that no longer stands.
- **When**: when the scheduler marks a milestone `built` and the project has the mode on, it queues
  an `explain` job (`cobble:jobs`, fields `ref`, optional `force`). A queue failure is logged and
  never holds the build back. `POST /projects/{id}/milestones/{ref}/explain` queues the same job
  with `force` to write or rewrite a summary on demand (409 `explain_mode_off`, 409 `wrong_state`
  while the milestone is pending). Switching the mode on later does not back-fill by itself; the
  button does.
- **Who writes it**: `PlannerService.explain_milestone`, run by the worker like the other planner
  jobs. It reads the milestone title and the title and acceptance criteria of its tasks (at most
  30 tasks, 4 criteria each), asks in the user's language and stores the text.
- **Role**: the existing `reviewer` role. It reads what was built and describes it, which is the
  reviewer's job, and both presets already give it an affordable chain. No new role, so presets,
  routes, the Models settings and the CLI are unchanged. Every call goes through the cost router,
  so tokens and cost are recorded per project and per role (visible in the Costs tab and report).
  `local_only` projects are honoured by the router as for any call.
- **Idempotent and cheap**: the job does nothing when the mode is off, the milestone is pending or
  unknown, or it already has a summary (unless `force`). Its model call is checkpointed like the
  other planner steps (ADR 0016), so a replay after a crash does not pay twice. An answer that
  arrives after the milestone was re-opened is dropped.
- **Shown**: in the Demo tab, on the milestone card (with "write it again"), and kept visible if the
  mode is switched off later. `milestone.updated` is published when it is stored, so the UI reloads.
- **Report**: each milestone of `GET /projects/{id}/report` has an `explanation` field (no extra
  query) and the Markdown export adds an "Explained in plain words" section only when at least one
  summary exists. The Report tab of the UI is unchanged.

## Consequences

- Off by default: no job, no tokens, for existing and new projects.
- A summary is advice for learning, not a guarantee: it is model-written text, shown as plain text
  (never HTML).
- Out of scope: per-task explanations, a "quiz" mode, choosing the level of the reader.
