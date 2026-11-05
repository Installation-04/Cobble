# ADR 0019 — The local benchmark as a background job

Status: **proposed** (v0.3, waiting for the owner to accept it).

## Context
ADR 0012 added the local model benchmark, run only by `cobble models benchmark`. The owner wants to
start it from Settings → Models. A run takes minutes (8 model answers and 8 sandbox runs per
model), so the API must not do it inside a request, and two runs at once would only compete for the
same model and the same two sandbox slots.

## Decision
- **A job on the existing stream.** `POST /api/v1/models/benchmarks/run {models, allow_paid}`
  (administrators only) checks the names against the module-manager's list, then queues
  `{"kind": "benchmark", "models": [...]}` on `cobble:jobs` and answers 202 at once. No models
  chosen means every model served on this machine. A paid model (a connection with a key) needs
  `allow_paid`, the API twin of `--allow-paid`: without it, 422 `benchmark_paid`. Nothing to
  measure: 422 `benchmark_nothing`.
- **One run at a time.** A Redis lock (`SET NX EX`, 30 min) is taken by the API before queuing;
  a second request gets 409 `benchmark_running`. The worker renews the lock after every task, so a
  crashed worker frees it by itself within 30 minutes; the status then reads `interrupted`. If
  queuing fails the lock is released (503 `queue_unavailable`).
- **Status in Redis, no table, no migration.** `GET /api/v1/models/benchmarks/status` returns
  `{state: running|idle, models, model, model_index, task, tasks, started_at, finished_at, error}`.
  It is transient by nature; the results themselves stay in `model_benchmarks` (migration 0013) and
  are stored by the same service as before. `error` is a stable code, never provider text:
  `sandbox_unavailable`, `docker_unavailable`, `sandbox_busy`, `sandbox_error`,
  `module_manager_unavailable`, `model_error`, `interrupted`, `internal_error`. The UI translates
  them in French and English.
- **One runner for the CLI and the job.** `cobble/benchmark/job.py` holds `BenchRig`/`LiveBench`
  (moved out of `cli_models.py`), `run_models` (loop, progress callbacks, failure codes) and
  `BenchmarkStatus`. All model calls still go through the gateway (`role="benchmark"`), all code
  runs in the module-manager sandbox.
- **A failure that is not the model's fault stops the run and stores nothing** for the model being
  measured (before, the CLI stored a zero score when the sandbox was down).
- **UI.** The "Run benchmark" button opens a list of checkboxes (local models checked, paid models
  unchecked under a cost warning), then polls the status every 2 s while a run goes, shows
  "task x of 8", and reloads the results when it ends.

## Consequences
The worker runs jobs one by one: during a benchmark (minutes) planner jobs of projects wait. The
benchmark is an occasional, deliberate action, so we accept it rather than add a second worker
loop; if it hurts, a dedicated consumer can be added later without changing the API.
