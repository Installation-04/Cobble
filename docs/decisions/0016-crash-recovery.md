# 0016 — Crash recovery (resume instead of restart)

Status: accepted (v0.3, "Reprise après panne", PLAN.md section 17).

## Context: what happens today when the worker dies

Investigated in `backend/cobble/worker.py`, `scheduler/engine.py` and `orchestrator/service.py`.

| Situation | Behaviour before this ADR |
|---|---|
| Job (`reply`/`spec`/`plan`/`start`/`revert`) read from `cobble:jobs` but not acknowledged | Stays in the consumer group's pending list. At start-up `run_jobs` claims everything pending (`XAUTOCLAIM`, idle 0) and then every 60 s anything idle for 10 min. The job is run again. **Already handled.** |
| Job handler raises a bug-level exception | Logged, job acknowledged and dropped (no infinite loop). |
| Task `running` (`implementing`, `writing_tests`, `ci`) | All state is in `tasks`/`task_runs`. `Scheduler.reconcile()` runs at start-up: runs with an agent-service id are polled again, finished ones are processed, unknown ones are marked failed, tasks in `ci` are checked again. No second run starts while one is active. **Already handled.** |
| `task_runs` row `pending` (crash between the DB write and the agent-service answer) | Marked `lost`, no attempt counted, a fresh run is started. The first container may still be running (it ends at its time limit) and its tokens are spent for nothing. **Gap 2.** |
| Partial agent output | Lives in the agent container and its branch; the new run starts from the task branch, which keeps committed work. Uncommitted work is lost. Out of scope here. |
| LLM calls already recorded | `llm_calls` rows are written by the router when a call returns, so the cost is never lost. But a planner job replayed after a crash called the model **again** (spec, plan and every plan retry) and paid twice. `reply` was already a no-op when the answer was stored. **Gap 1.** |
| Dropped jobs on handler bug | See above. **Gap 3.** |
| Multi-worker | Start-up reclaim uses idle 0, so a second live worker would steal jobs of the first. v0.1 assumes one worker. **Gap 4.** |

## Decision

One mechanism, the smallest one that closes the biggest gap (1): **step checkpoints in the
database**.

- Table `job_checkpoints (project_id, key, content, created_at)`, migration 0014 (tested up and
  down).
- `PlannerService._chat` is the only place a planner job calls the model. Inside `run_job` it
  looks for a checkpoint keyed by `sha256(step, role, messages)`; when found (and younger than
  one hour) it returns the stored answer without calling the router, so nothing is billed twice.
  Otherwise it calls the router and stores the answer **before** anything else uses it. The plan
  retry loop passes its attempt number as `step`, so a replay resumes at the retry it had reached.
- When a job ends (success or reported failure) its checkpoints are deleted. A process killed
  mid-job leaves them, and the job that `XAUTOCLAIM` hands back finds them. Stale rows
  (older than `CHECKPOINT_TTL`, 1 h, a job nobody replayed) are ignored and purged on read, and
  are removed with the project (`ON DELETE CASCADE`).
- Outside `run_job` (direct calls) nothing is checkpointed: behaviour unchanged.

The scheduler needs no new mechanism: its steps (`task_runs.state`, `agent_run_id`,
`head_sha`, `tasks.state`, `pr_number`) already are the checkpoints, and `reconcile()` plus
the pending-job reclaim are the resume path. This ADR records and tests that this is the
contract.

## Not done (follow-ups, not v0.3 scope creep)

- Gap 2: adopt an orphan run by marker (`[cobble-task:REF:ROLE:ATTEMPT]`). Needs a `find(marker)`
  on `AgentRunner`, in the agent-service API, the HTTP provider and the fakes.
- Gap 3: leave a job pending (bounded redelivery count) instead of dropping it when the handler
  itself crashes.
- Gap 4: a consumer liveness lease so that start-up reclaim only takes entries of dead consumers
  (`XINFO CONSUMERS` idle time) when several workers run.
- Checkpoint uncommitted agent work (agent-service side).
- Real Redis: the reclaim is covered with the in-memory stream fake in unit tests; no
  integration test kills a real worker.
