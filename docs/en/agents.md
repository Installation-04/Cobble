# Coding agents: runner, agent-service and egress proxy

Agents write the code of generated projects. They run in sandboxed containers started by
**agent-service**, the service of the `aider` module (`catalog/aider`, sources in `services/agent-service/`). The core only talks to it through
the `AgentRunner` capability (HTTP, [ADR 0006](../decisions/0006-agent-runner-and-scheduler.md));
it never knows which tool runs inside (today: Aider).

```
 backend / worker ──HTTP+bearer──▶ agent-service ──Docker socket──▶ agent container (runner image)
                                      │  clone / push (Forgejo token stays here)        │
                                      ▼                                                 │ HTTP(S)_PROXY
                                   Forgejo                                              ▼
                       Cobble API  ◀──── agent-proxy (allow-list) ◀───── network cobble_agents (internal)
                 /internal/llm/v1                        └──▶ pypi.org, files.pythonhosted.org, registry.npmjs.org
```

| Piece | Where | What |
|---|---|---|
| Runner image | `runners/aider/` | Python 3.12, Aider 0.86.2 (locked with hashes in `uv.lock`), git, uv, Node 22 + pnpm 10.28 (corepack). Runs as uid 10001. |
| agent-service | `services/agent-service/` | FastAPI app; creates the worktree, starts and supervises the container, pushes the result. |
| agent-proxy | `services/agent-proxy/` | tinyproxy (GPL-2.0-or-later, unmodified, separate container) in default-deny mode. |
| Module | `catalog/aider/` | compose project `cobble-aider`; no published port. Images are built by CI and pinned by digest. |

## What one run does

1. `POST /v1/runs`: agent-service validates the request, answers `202 {run_id}` and continues in the
   background.
2. It clones the repository into a bare repository it keeps for itself (`repo.git`) using the Forgejo
   service token, then makes the worktree `runs/<id>/work` (task branch created from the base branch,
   or continued if it already exists on the remote), and writes `.cobble/instructions.md`.
3. It starts the runner container with the worktree mounted on `/work` and nothing else.
4. The runner entrypoint (`cobble-agent`) prepends the marker line to the instructions and runs
   `aider` headless (`--yes-always --no-stream --edit-format whole --test-cmd ... --auto-test`,
   model `openai/<alias>`, endpoint = the Cobble API). Aider commits locally.
5. Output is streamed to `runs/<id>/agent.log` (served by `GET .../logs?offset=N`, next offset in
   `X-Next-Offset`). Loop detection reads the same stream.
6. When the container ends, agent-service **fetches** the branch into its own repository, checks that
   history was not rewritten, counts the commits and pushes the branch itself. State `done` needs exit
   code 0 and at least one commit; otherwise `failed` (`reason`: `agent_failed`, `no_commits`,
   `history_rewritten`, `push_failed`, `max_iterations`, ...), or `timeout`, `loop_detected`, `stopped`.
7. The container is removed. The run directory (worktree, log, metadata) is kept for
   `COBBLE_AGENT_RETENTION_HOURS` (24 h) and then deleted.

Iterations are test runs: the runner wraps the test command (`cobble-test`) and prints
`[cobble:test-run N]`, `[cobble:test-fail <fingerprint>]`, `[cobble:test-pass]`. The exit code of the
runner is the result of the last local test run (0 only when the tests pass). Aider itself reflects at
most 3 times per message; `max_iterations` is a hard ceiling enforced by agent-service (the container
is killed when test run `max_iterations + 1` starts).

Loop detection (`COBBLE_LOOP_THRESHOLD`, default 8): the same line (ANSI codes, timestamps and
addresses removed; numbers kept) repeated that many times in a row, or the same test-failure
fingerprint on two consecutive test runs, ends the run with `loop_detected`.

### HTTP API

Exactly ADR 0006 (`Authorization: Bearer <COBBLE_AGENT_SERVICE_TOKEN>`, constant-time comparison;
`/healthz` is open). Errors use `{"error": {"code", "params"}}`: `401 unauthorized`, `404
run_not_found`, `422 invalid_request`, `400 repo_url_not_allowed`, `429 too_many_runs`. The status
body adds optional fields to the ADR's `state`, `iterations`, `exit_code`, `head_sha`, `log_tail`:
`run_id`, `reason`, `commits`, `diff_stat`, `pushed`, `started_at`, `finished_at`. Limits above the
service caps are lowered, not rejected.

## Security model

**The agent container can**: read and write its worktree and `/tmp` (tmpfs, `COBBLE_AGENT_TMP_MB`),
run processes within its CPU, memory (swap disabled), PID and wall-clock limits, call the Cobble API's
internal LLM endpoint with its run token, and download packages from the allowed registries.

**It cannot**: see the Docker socket; run as root (uid 10001, `no-new-privileges`); keep any capability
(`cap_drop ALL`); write the root filesystem (read-only); see other runs' worktrees (it only gets the
sub-path of its own run); read any git credential (the Forgejo token exists only in agent-service's
environment and in the environment of the `git clone`/`push` processes, through `GIT_ASKPASS`; it is
not in a URL, a git config, a file, or the container environment, and tests check this); push (no
credentials, no route to Forgejo); reach LiteLLM, Redis, Postgres or the internet; resolve names other
than through the proxy. Its only secret is the run token: valid for the run's duration, bound to one
task and role, and accepted only by the internal LLM endpoint, which applies the budget and records the
cost.

**agent-service** is the one component with the Docker socket (rule 5; the core never touches it).
Access to the socket is equivalent to root on the host, so it is kept small: it runs as uid 10001
(joins the socket's group with `group_add: [DOCKER_GID]`), read-only root filesystem, no capabilities,
no published port, bearer token on every route, and it only ever creates containers from its own
fixed template (the request cannot choose image, mounts, network, user or capabilities). It also
refuses to start a run if the agents network is not `internal`.

**The worktree is untrusted.** The agent can write `.git/config` and hooks. agent-service therefore
never runs git inside a worktree: it fetches the branch from the worktree into its own clean bare
repository (fetch from a path executes no repository code) and inspects and pushes from there, always
to the task branch, never forced.

**Clone URLs** must start with `COBBLE_PACK_FORGEJO_URL` (after the optional
`COBBLE_AGENT_GIT_REWRITE=public-prefix=internal-prefix`), so a caller cannot make the service send its
token to another host.

### Egress allow-list

The network `cobble_agents` is `internal: true`: no route out. The only container attached to both it
and the core network is `agent-proxy`. The agent's `HTTP(S)_PROXY` points at it. The default list is
`api,pypi.org,files.pythonhosted.org,registry.npmjs.org`; change it with `AGENT_PROXY_ALLOW`
(comma-separated host names, `*.example.org` allowed; invalid entries abort the start; an empty list
refuses to start). The proxy filters on the destination host, default deny, and CONNECT tunnels are
limited to port 443. `api` must match the host of `COBBLE_INTERNAL_API_URL`.

### Known limits (v0.1)

- Anyone with the Docker socket owns the host: agent-service is trusted code. gVisor/Sysbox are
  future modules (PLAN section 11).
- The worktree has no disk quota (only `/tmp` has a size limit); the log is capped at 50 MiB.
- Agent containers can reach each other on `cobble_agents` (they hold different run tokens and no
  other secrets).
- Plain-HTTP requests through the proxy are filtered by host, not port: do not put a host on the list
  that exposes unrelated HTTP services.
- Agent-written files such as the CI definition are pushed as is; the merge request and CI are the
  gate (CI pipelines never run "trusted").
- Needs Docker 26 or later (volume sub-path mounts, API 1.45).

## Install

```
cobble modules install aider        # the Git server it needs is added with it
```

The module takes the Git server's address and API token from the module that provides `git`
(a `pre_up` hook; the token never reaches the core), generates its own service token, pulls the
three images (agent-service, proxy, and the ~2 GB runner image) and starts. The core finds it
through the module-manager (`GET /v1/connections`): nothing to configure by hand. The images are
published by the "Module images" workflow (`.github/workflows/images.yml`) to
`ghcr.io/<owner>/cobble-*` and pinned in `catalog/aider` with `scripts/pin_images.py`.

agent-service is configured by the module's compose file: `COBBLE_AGENT_SERVICE_TOKEN`,
`COBBLE_INTERNAL_API_URL`, `COBBLE_PACK_FORGEJO_URL|TOKEN|OWNER`, `COBBLE_AGENT_DATA_VOLUME`,
`COBBLE_AGENT_NETWORK`, `COBBLE_AGENT_RUNNER_IMAGE`, `COBBLE_AGENT_PROXY_URL` (the volume and the
network are the ones the platform names `cobble-aider-agents-data` and `cobble-aider-agents`).
Optional: `COBBLE_AGENT_GIT_REWRITE`, `COBBLE_LOOP_THRESHOLD`, `COBBLE_AGENT_MAX_RUNS` (8),
`COBBLE_AGENT_RETENTION_HOURS` (24), `COBBLE_AGENT_MAX_CPU` / `_MEMORY_MB` / `_PIDS` / `_SECONDS`
(caps). `COBBLE_AGENT_CMD` is a test hook: it replaces Aider in the runner with a shell command;
never set it in production.

After a restart, agent-service resumes supervising running containers (found by label),
finalises finished ones, marks the ones whose container vanished `failed` (`container_lost`) and
removes labelled containers it has no record of. Uninstalling the module stops the agent containers
it started.

## Dependencies

agent-service uses `fastapi`, `uvicorn`, `httpx` (already in the backend; BSD/MIT) and talks to the
Docker Engine API over the unix socket with httpx, instead of adding the Docker SDK. The runner adds
Aider (Apache-2.0) and its locked dependencies; tinyproxy is GPL-2.0-or-later and only runs as a
separate program.

## Tests

```
cd services/agent-service
uv sync && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
cd backend && uv run pytest tests/unit/test_service_images.py   # static checks of images and compose
```

The unit tests use a fake Docker engine and real git repositories in a temporary directory: lifecycle,
auth, validation, loop detection, timeout, stop, restart recovery, secret leakage, hostile `.git`
config. Agent tests never call a real model; for end-to-end trials use the fake LLM with a marker
cassette (`providers/fake-llm/README.md`).
