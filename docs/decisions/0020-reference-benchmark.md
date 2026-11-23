# 0020 — Reference benchmark of the agents

Status: **proposed** (implemented in v0.3, waiting for the owner to accept; v0.3 acceptance criterion, PLAN.md sections 14 and 15). The real run is NOT done: it needs the owner's API key.

## Context

v0.3 is accepted when, on 5 reference projects, the success rate and the average cost are measured and published, and no agent exceeds its budget. Everything except the paid run can be built and tested without a model.

## Decisions

- **Five projects** in `reference-projects/`: `todo` (floor), `blog` (fine print), `invoicing` (exact money), `dashboard` (aggregation and time zones), `bot` (exact texts and priorities). Each has a frozen spec in English (`spec.md`) and French (`spec.fr.md`), written so a small cheap model can finish it but only by following the details.
- **Hidden acceptance tests** (`hidden/`, pytest + FastAPI `TestClient`, public HTTP API only) are never copied into a generated repository. The runner clones the generated code after the build and runs the tests from a temporary directory outside it (`_common/conftest.py` gives each test a fresh data directory and a fresh working directory, and simulates a restart by re-importing the app). A guard (`assert_unreachable`) refuses a code tree that contains the tests, and a unit test checks no compose file, template, runner or module mentions `reference-projects`.
- **Known to be satisfiable and discriminating**: each project has a reference solution (`solution/tree`, laid over the template; for `todo` it is the existing cassette solution) and `mutations.json`, deliberate breakages that each must fail at least one test. `make bench-check` runs it (solution passes, empty template fails, every mutation caught: 8, 11, 14, 15 and 17 mutations).
- **Runner** (`scripts/cobble_bench/`, standard library only for the real run): through the public API only: create project, cap its budget (`PATCH budget_usd`), send the frozen spec as the interview, generate and approve spec and plan, start, follow (validating each demo), read costs, clone the code (`GitFetcher`, token in the environment of `git`), run the hidden tests. The platform's cost router remains the only enforcer of the budget; the runner measures and records whether any project ended above its cap, and a total budget skips or caps the remaining projects. Success = project `done` and all hidden tests pass.
- **Safety against accidents**: `make bench` refuses without `--yes-real-models` (or `COBBLE_BENCH_REAL_MODELS=yes`), credentials, a code source, and an instance whose roles all use a real (non-`fake`) model. Messages are printed in French and English. It is never run in CI (a test checks the workflows do not mention it). `--dry-run` swaps the platform for an in-memory simulator and the reference solutions as "generated code": whole pipeline, no cost; its reports are labelled as a simulation.
- **Results**: `reference-projects/results/<run id>/report.json` plus `report.fr.md` and `report.en.md`; the directory is ignored by version control except two summary templates to fill when publishing.
- Not wired to the preset-by-preset CI run of PLAN section 15 ("each version"): v0.3 needs one published run; a recurring run belongs to a later version.

## Consequences

- The v0.3 criterion is provable once the owner runs `make bench` with a key; until then the report format and the budget bookkeeping are tested on the simulator only.
- The repository name rule (`<slug>-<6 hex of the id>`) is duplicated from the scheduler; the API does not expose the clone URL. A future `repo_url` field would remove this.
- Hidden tests exercise the backend API only: frontend quality is not scored in v0.3.
