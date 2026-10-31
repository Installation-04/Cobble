# Full-chain end-to-end run (`make e2e-full`)

`make e2e` drives the browser on in-memory fakes. This manual harness runs the **real chain** on
the to-do reference project, with no model and no API key: Forgejo, Woodpecker, agent-service
with the Aider runner, and preview-service, all answered by the fake LLM replaying cassettes.

```bash
make e2e-full                        # scripts/e2e_full.sh; add ARGS, e.g. --keep --comment
scripts/e2e_full.sh --keep --timeout 5400 --lang fr
```

Options: `--keep` (leave the stack up), `--timeout SECONDS` (building time, default 3600), `--lang en|fr`,
`--comment` (after `done`, comment on the last demo and follow the new `C-001` task), `--force`
(replace pack secrets already present in `packs/v01`). `E2E_PORT` sets the host port (18080).

## What it does

1. Generates secrets in a temporary directory, starts the core (compose project `cobble`), installs
   the pack, builds and starts agent-service and preview-service. It refuses to run next to a dev
   stack named `cobble`, and tears down with `down -v` (everything is deleted) unless `--keep`.
2. Activates the admin through the API, creates the project "Todo list".
3. Replays the scripted interview (`USER_MESSAGES` in
   `providers/fake-llm/scripts/make_todo_cassettes.py`), generates and approves the spec and the plan.
4. `POST /projects/{id}/start`, then polls `GET /projects/{id}/tasks` and the project `phase`. It
   validates each milestone demo as soon as it is `built` (the phase only reaches `done` when every
   milestone is validated), and stops early when a task fails or is blocked.
5. Prints the final task table, tokens and cost (`GET /projects/{id}/costs`, else the `llm_calls`
   table through `psql`) and the elapsed time. Exit status 0 only when the phase is `done`.

Endpoints that answer 404 (not yet available) are reported as `SKIPPED` and do not fail the run.

## The agent cassettes

Agents are replayed by marker cassettes `providers/fake-llm/cassettes/agent-todo-<ref>-<role>-<attempt>.json`,
generated from the reference solution `reference-projects/todo/solution/` (one folder of exact file
contents per plan task, tests first):

```bash
python3 scripts/make_agent_cassettes.py            # rewrite cassettes and solution/tree
python3 scripts/make_agent_cassettes.py --check    # fail when out of date
python3 scripts/make_agent_cassettes.py --table    # tasks, files, dependencies
python3 scripts/verify_solution.py --orders 2      # replay the tasks against the template's CI
```

After changing the plan in `make_todo_cassettes.py` or a solution file, rerun the first command (and the
todo generator). Tasks that share a file must be ordered by `depends_on`: the script fails otherwise.
`C-001` ("show a due date") answers the first comment; `X-LOOP` is a fictional task whose worker
answer is wrong on purpose, to test loop detection (`loop_detected`).
