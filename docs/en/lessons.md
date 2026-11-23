# Lessons learned

When a task keeps failing inside a project, Cobble keeps a short note of the cause and tells the next agents of the same project, so they stop repeating the mistake ([ADR 0026](../decisions/0026-lessons-learned.md)). No model is called to write them: they cost nothing by themselves.

## What is captured

A lesson is recorded when an agent attempt fails and the task has already failed as many times as it takes to escalate (2 by default):

- **CI failure**: the first failing test and its message.
- **Loop**: the line the agent kept repeating.
- **Timeout**: the last thing it printed before running out of time.

Texts are plain, at most 300 characters, and secrets (tokens, passwords, keys) are masked. The same mistake seen again only raises its counter. A project keeps at most 20 active lessons; beyond that the least useful automatic one is removed (the ones you wrote are never removed).

## What agents see

Test-writer and worker runs of the project get a short "Lessons from this project" block with at most 5 active lessons (most seen first, then most recent), about 300 tokens at most. A project without lessons gets nothing added.

## Managing them

Open the project, **Agents** tab, **Lessons learned** section. You can add a lesson, edit its text, disable it (kept but not shown to agents) or delete it. A badge shows which ones the next agent will see.

API (same ownership and CSRF rules as the other routes): `GET` and `POST /api/v1/projects/{id}/lessons`, `PATCH` and `DELETE /api/v1/projects/{id}/lessons/{lesson_id}`. `409 lessons_full` when 20 are already active.
