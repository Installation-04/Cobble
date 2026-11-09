# ADR 0025 — Questions from agents to the user

Status: **proposed** (implemented in v0.3, waiting for the owner to accept it).

## Context
PLAN.md §14 v0.3 ("questions à l'humain"): an agent may put a question in a queue ("Should the
amount include taxes?") instead of inventing an answer; other tasks go on meanwhile. Until now an
agent that lacked a decision guessed, or looped until the guard rails killed it and a failed
attempt was counted.

## Decision

### Protocol (agent side, provider-agnostic)
An agent ends its run with ONE line on its output:

    [cobble:question] {"question": "Should the amount include taxes?", "choices": ["yes", "no"]}

`choices` is optional. The runner image also turns a file `.cobble/question.json` (same JSON) into
that line when the agent exits, so an agent that can only write files can ask. The agent-service
reads it with the output it already follows for loop detection (`detector.py`, parsing in
`questions.py`); the first valid line of a run wins. When seen, the container is killed at once
(nothing more is spent), the work committed so far is pushed to the task branch (best effort), and
the run ends in the new state `question` with `question: {question, choices}` in its status. The
core does not name any agent product: the capability `AgentRunner.poll` returns the outcome
`AgentOutcome.QUESTION` with an `AgentQuestion` (text, choices).

### Scheduler
- Table `task_questions` (migration `0020`): task, run, question, choices (JSON), status
  `open | answered | skipped`, answer, creation and answer times.
- A `question` run is **not** a failure and **does not use an attempt** (it is not in `COUNTED`).
  The question is stored before the run is closed, so a crash in between records it once.
- The task goes to the new state `waiting_human`. It runs nothing and holds no agent slot, so no
  token is spent while it waits; its dependents stay `todo` (not blocked); the project does not
  finish while it waits. Other tasks continue.
- Waiting has no clock: the scheduler has no per-task duration timer (a run's limit,
  `max_seconds`, belongs to the run, which is over), the project budget is money only, and the
  CI timeout applies to `ci` only. Nothing punishes the wait.
- On answer (or skip), the task becomes `paused` (waiting for a slot) and the scheduler starts the
  next run of the SAME kind with the same attempt number, so the attempt counter reads as if the
  question never happened. The prompt gets a block with every answered question ("Q / A"); a
  skipped one says "no answer: decide yourself". `_launch` refuses to start while a question of
  the task is open.
- Bounds: at most 3 questions per task (the prompt says how many are left; an agent that asks a
  fourth time has that run counted as FAILED, so a disobedient agent cannot loop for free),
  question 2000 characters, 6 choices of 200, answer 2000. Control characters are removed.
  Question and answer texts are never written to logs; the agent-service log keeps only the marker
  line the agent printed, like any other output.
- Controls: `pause` and `resume` are no-ops on a waiting task; `stop` and `retry` work and close
  the open question as skipped.

### API and events
`GET /api/v1/projects/{id}/questions` (open first, with the open count),
`POST .../questions/{qid}/answer` `{answer}` and `POST .../questions/{qid}/skip`: owner only and
CSRF header like the other routes; 404 for another project's question, 409 `question_closed`,
422 `answer_empty` / `validation_error`. Events: `task.question` (task, question id, text,
choices) when recorded, `task.answered` (task, question id, status) when closed, plus the usual
`task.updated`.

### UI
Agents tab: a badge counts the open questions, a waiting card says "Waiting for you" (column
"Needs attention"); the task drawer shows the question with its choices as buttons, a text box,
Send and "Skip: let the agent decide", and lists the earlier questions. The Chat tab is unchanged.

## Out of scope
Notifications outside the app (push, e-mail) are v0.4. The planner's own questions are the
interview and are not affected. The runner's prompt is advisory: how often a model asks is tuned
with the reference benchmark, not here.

## Consequences
- `waiting_human` is a new task state (a text column, no schema change for it); the UI, the control
  table and the rules know it.
- `AgentOutcome` gains `QUESTION`; an agent-service older than this change never sends it.
- Work done before a question is kept on the branch, so the resumed run continues from it.
- Migration `0020` follows `0019` (reviewer).
