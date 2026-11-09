# 0026 — Lessons learned per project

Status: accepted (v0.3, "leçons apprises", PLAN.md section 14).

## Context

Inside one project, agents repeat the same mistake: the same failing test, the same command that
loops, the same step that times out. A task that failed twice teaches something the next tasks
of the same project could use. This must cost nothing by default and must never leak secrets.

## Decision

- **Table** `project_lessons` (migration `0021`, tested up and down and for drift): `id`,
  `project_id` (cascade), `text` (at most 300 characters), `source`
  (`ci_failure|loop|timeout|manual`), `task_ref`, `active`, `hits`, `created_at`. `hits` is how
  many times the same mistake was seen (1 when first captured).
- **Capture, deterministic, no model call** (`cobble/scheduler/lessons.py`). When a worker attempt
  of a task fails and the task has already failed `escalate_after` times (the point where it
  escalates; a first failure is usually fixed by the next attempt and would be noise), a signal is
  extracted from what the scheduler already has:
  - `ci_failure`: the first failing test and its message from the CI log (pytest `FAILED name -
    message`, or `E ...` lines, or a vitest `FAIL name` block). A CI timeout or a refused merge
    gives no signal and no lesson.
  - `loop`: the line the agent repeated most in a loop-detected run (else its last line).
  - `timeout`: the last line before the run ran out of time.
  The text is redacted (keyed values such as `token=...`, bearer tokens, vendor prefixes like
  `ghp_`, passwords in URLs, long random tokens), whitespace-squashed and cut to 300 characters.
  Capturing never raises into the scheduler.
- **De-duplication**: a lesson with the same normalised text (case, digits and spacing ignored)
  only gains a hit. A lesson the owner disabled stays disabled and still counts hits.
- **Cap**: 20 active lessons per project. Over it, the captured lesson with the fewest hits, then
  the oldest, is deleted. Manual lessons are never dropped automatically; when only manual ones
  remain, a new captured lesson is not stored, and adding or re-enabling one through the API
  answers 409 `lessons_full`.
- **Injection**: when a worker or test-writer run starts (not demo-data tasks), the scheduler
  appends a block "Lessons from this project" with at most 5 active lessons, most hits first then
  most recent, at most 1200 characters in total (about 300 tokens, the cost of the feature: it is
  prompt tokens of the runs that already happen, counted by the cost router with the rest). The
  block is empty, and nothing is added, when the project has no active lesson. The marker line
  stays first, so the recorded-answer lookup of the fake provider is unchanged.
- **Owner control**: Agents tab, "Lessons learned" section, backed by
  `GET/POST /projects/{id}/lessons` and `PATCH/DELETE /projects/{id}/lessons/{lesson_id}`
  (project ownership and the CSRF header like every other route). The owner reads, edits the text,
  disables, deletes and adds lessons; each shows its source, task, hits and whether the next agent
  will see it. Text only, never rendered as markup.

## Not done

- No model summarises or merges lessons (it would cost tokens; a later option).
- No lessons shared between projects (privacy: lessons may quote project code).
- Not in the end-of-project report (it is a computed JSON with its own tests and locale keys;
  not trivial enough for this change).
- Redaction is best effort pattern matching, like any log scrubbing; lessons stay inside the
  project and are only shown to its owner and its own agents.

## Consequences

Migration `0021` follows `0020` (human questions).
