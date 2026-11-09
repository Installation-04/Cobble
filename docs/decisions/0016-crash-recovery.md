# 0016 — Crash recovery (resume instead of restart)

Status: **proposed** (implemented in v0.3, waiting for the owner to accept; "Reprise après panne", PLAN.md section 17).

## Context: what happens today when the worker dies

Investigated in `backend/cobble/worker.py`, `scheduler/engine.py` and `orchestrator/service.py`.

| Situation | Behaviour before this ADR |
|---|---|
| Job (`reply`/`spec`/`plan`/`start`/`revert`) read from `cobble:jobs` but not acknowledged | Stays in the consumer group's pending list. At start-up `run_jobs` claims everything pending (`XAUTOCLAIM`, idle 0) and then every 60 s anything idle for 10 min. The job is run again. **Already handled.** |
| Job handler raises a bug-level exception | Logged, job acknowledged and dropped (no infinite loop). **Gap 3, closed below.** |
| Task `running` (`implementing`, `writing_tests`, `ci`) | All state is in `tasks`/`task_runs`. `Scheduler.reconcile()` runs at start-up: runs with an agent-service id are polled again, finished ones are processed, unknown ones are marked failed, tasks in `ci` are checked again. No second run starts while one is active. **Already handled.** |
| `task_runs` row `pending` (crash between the DB write and the agent-service answer) | Marked `lost`, no attempt counted, a fresh run is started. The first container may still be running (it ends at its time limit) and its tokens are spent for nothing. **Gap 2, closed below.** |
| Partial agent output | Lives in the agent container and its branch; the new run starts from the task branch, which keeps committed work. Uncommitted work is lost. Out of scope here. |
| LLM calls already recorded | `llm_calls` rows are written by the router when a call returns, so the cost is never lost. But a planner job replayed after a crash called the model **again** (spec, plan and every plan retry) and paid twice. `reply` was already a no-op when the answer was stored. **Gap 1.** |
| Multi-worker | Start-up reclaim uses idle 0, so a second live worker would steal jobs of the first. v0.1 assumes one worker. **Gap 4, closed below.** |

## Decision

One mechanism, the smallest one that closes the biggest gap (1): **step checkpoints in the
database**.

- Table `job_checkpoints (project_id, key, content, created_at)`, migration 0015 (tested up and
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

## Gaps 2, 3 and 4 (closed later in v0.3)

**Gap 3, a crashing handler.** A handler that raises no longer gets its job acknowledged.
The job stays pending; the worker reads its delivery count (`XPENDING`, incremented by every
read or claim). Below `MAX_DELIVERIES` (3) it is retried: the periodic reclaim takes the worker's
own entries back after `RETRY_DELAY_MS` (30 s). At the third delivery the job is appended to the
dead-letter stream `cobble:jobs:dead` (job JSON, entry id, delivery count, `ExceptionType:
message` cut to 300 characters, at most 1000 entries kept), a `job.failed` event with the code
`crashed` is published for the project (the existing `FailureBanner`, string `job_crashed` in FR
and EN) and the entry is acknowledged. The owner lists the parked jobs with
`redis-cli XRANGE cobble:jobs:dead - +`. A job that never raises because it kills its worker
(out of memory, SIGKILL) is also bounded: when the reclaim finds an entry already delivered
`MAX_DELIVERIES` times it is parked without being run. No schema change: the delivery counter is
Redis's own. Planner steps already done are not paid twice on a retry (checkpoints).

**Gap 4, two workers.** The reclaim is no longer "everything, idle 0". The consumer name is
stable per container (`COBBLE_WORKER_NAME`, else the host name, which a container restart keeps).
At start-up a worker takes back the entries owned by its own name at once (nobody else can be
running them); entries of any other consumer are taken only after `RECLAIM_IDLE_MS` (10 min) of
silence, at start-up and at every 60 s tick, so a live peer's jobs are left alone. Two live
workers must not share a name. Not covered: a worker container recreated under a new host name
gets its predecessor's jobs after 10 min instead of at once (pin `COBBLE_WORKER_NAME` to avoid
that), and a live job that runs longer than 10 min can be claimed by a peer (the checkpoints
limit the cost of the duplicate).

**Gap 2, a `pending` run.** The agent-service records every accepted run with its task id and
marker, so `GET /v1/runs?task_id=&marker=` lists the matching runs, newest first
(`AgentRunner.find(marker, task_id)` returns the newest id; an older service answering 404/405
means "none", the previous behaviour). For each `pending` row the scheduler rebuilds the marker
from the task ref, the run's role and attempt and asks:

- a run is found that no other row of the task owns: it is **adopted** (the row becomes
  `running` with that id, the task state and attempt counter are set as `start` would have, and
  the normal polling takes over, so nothing is started twice and the container's work is kept);
- nothing is found, or the newest match already belongs to an older row (a retried test-writer
  reuses its marker): the row is marked `lost` as before and a new run starts;
- the service cannot be reached: the row stays `pending` (no second run starts) and every tick
  asks again once the row is older than two minutes (younger rows may be a start in flight).

An adopted run that is stale is handled by the existing limits (time limit, `stop`); no extra
"stop the orphan" path was needed because adoption never leaves one.

## Not done (follow-ups, not v0.3 scope creep)

- Checkpoint uncommitted agent work (agent-service side): work that was not committed when the
  agent container died is lost.
- Real Redis: all of the above is covered with the in-memory stream fake in unit tests (including
  idle times and delivery counters); no integration test kills a real worker.
