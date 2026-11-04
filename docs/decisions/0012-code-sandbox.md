# ADR 0012 — A sandbox for untrusted code, held by the module-manager

Status: **proposed** (implemented in v0.3, waiting for the owner to accept it).

## Context
The local model benchmark (PLAN.md §8) scores a model by running the code it writes. That code is
untrusted. It must not run in the API or the worker, and CLAUDE.md rule 5 says that only the
module-manager touches Docker.

## Decision
- The module-manager offers one primitive, `POST /v1/sandbox/run {program, timeout_s}`, behind its
  bearer token: it runs a short Python program in a **throwaway container** and returns
  `{exit_code, stdout, stderr, timed_out}`. Nothing else is exposed (no arbitrary image, no mounts,
  no network, no options from the caller).
- The container (`module_manager/sandbox.py`, every option in one tested function): the image
  pinned by digest (`COBBLE_SANDBOX_IMAGE`, default `python:3.12-slim@sha256:…`; empty turns the
  sandbox off), `--network none`, `--read-only` with a 16 MB `noexec` tmpfs, `--cap-drop ALL`,
  `no-new-privileges`, user `10001`, 256 MB memory (no swap), 1 CPU, 64 processes, `--rm`. The
  program arrives on stdin (`python -I -`); no volume is mounted and no socket is shared. The
  caller's time limit (1 to 60 s) is enforced by killing the container by name.
- Limits on the service: programs up to 100 KB, output clipped to 64 KB per stream, two runs at
  once (the third gets `429 sandbox_busy`), codes `sandbox_unavailable` / `docker_unavailable` /
  `program_too_large`.
- **Checked for real** with the pinned image: the program runs as uid 10001; a connection attempt,
  a write to the root filesystem and a look for the Docker socket all fail; a 2 GB allocation is
  OOM-killed (137), a fork bomb stops at the process limit, an infinite loop is killed at the time
  limit; no container is left behind.

## Consequences
The module-manager gains the ability to start containers that are not modules. They carry the
label `cobble.sandbox=true`, have no network and no data, and live for at most the caller's time
limit. The first run needs the image (pulled by Docker, once; offline installs must pre-pull it).
