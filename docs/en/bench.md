# Agent bench: running it and publishing the results

The bench measures, on five frozen reference projects, how often the agents deliver an application that passes hidden acceptance tests, and what it costs ([ADR 0020](../decisions/0020-reference-benchmark.md)). It is the acceptance criterion of v0.3.

| Project | What it measures |
|---|---|
| `todo` | the whole loop on a tiny app |
| `blog` | slugs, drafts, tag filter, delete cascade |
| `invoicing` | exact money (Decimal), rounding, numbering, state machine |
| `dashboard` | aggregation, time zones, half-open date ranges |
| `bot` | exact reply texts, rule priorities, an expression parser without `eval` |

## Without spending anything

```bash
make bench-check     # hidden tests vs reference solutions and their mutations (no model)
make bench-dry-run   # the whole runner against an in-memory simulator; reports start with dry-
```

The simulator invents its numbers: never publish a `dry-` report.

## The real run (spends money)

Needs a running instance (`make dev` is not enough: its model is the fake one) with a real model connection in Settings, an admin account, and read access to the generated repositories.

```bash
export COBBLE_BENCH_URL=http://localhost:8080
export COBBLE_BENCH_EMAIL=admin@example.com COBBLE_BENCH_PASSWORD=...
export COBBLE_BENCH_GIT_URL='http://<git server>/<owner>/{repo}.git'   # {repo} is replaced
export COBBLE_BENCH_GIT_TOKEN=...
make bench ARGS="--yes-real-models --preset balanced --slot cheap=<model> --slot strong=<model> --total-budget 8 --label v0.3"
```

Without `--yes-real-models` (or `COBBLE_BENCH_REAL_MODELS=yes`), credentials, a code source, or with a role still on the `fake` model, it prints why, in French and English, and exits with status 2 before creating anything. Other options: `--projects todo,bot`, `--cap USD` (per-project cap, default 1 to 2 USD each), `--total-budget USD` (default 8), `--timeout-scale`, `--lang fr|en`, `--code-dir DIR` (code already on disk as `DIR/<project>/`), `--python` (interpreter for the hidden tests; default `uv run --project {code} python`, i.e. the generated project's own lockfile). Never run it in CI.

Each project gets a budget cap on the platform (the cost router pauses it at 100 %); the runner stops waiting if the spend passes the cap and records it. The exit status is 1 when a project or the total ended above its budget.

## Results

`reference-projects/results/<run id>/` gets `report.json`, `report.en.md` and `report.fr.md` (ignored by version control). Figures: success rate (project `done` and all hidden tests pass), average cost per project and per successful project, tokens, duration, escalated tasks, fallback calls, and "no project exceeded its budget".

To publish: copy the figures into `reference-projects/results/SUMMARY.template.en.md` / `.fr.md` (fill both languages), attach the Markdown reports, and note the models and preset. Publish real runs only.

## Adding or changing a project

Keep the spec frozen once published. A change to a spec or to the hidden tests changes what is measured: record it in the changelog and do not compare runs across it. After editing, run `make bench-check`.

Hidden tests must stay unreachable from agents: they live only under `reference-projects/`, which no module, template or runner mounts.
