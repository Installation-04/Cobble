# 0008 — Module-manager, manifests and the official catalogue (v0.2)

Status: **draft, not accepted** — v0.2 is not open (v0.1 step 11 is not validated). Every "recommended" choice below is a proposal waiting for the project owner.

## Principles
- **The module-manager is the only holder of the Docker socket** (rule 5), as a **separate service** (`module-manager`), reachable only on an internal network. It takes over from v0.1's pack service for module containers. The backend never talks to Docker; it calls the module-manager's small internal HTTP API (the same pattern as `agent-service` in ADR 0006).
- **The core still names no product.** It resolves `provides:` capabilities (`git`, `ci`, `llm`, `agent-runner`, `preview`) to whichever module is installed, through the existing interfaces in `backend/cobble/capabilities/`.
- **Anti-conflict rules are enforced by the module-manager, never trusted to a manifest** (PLAN.md §6, §18): no host port except Caddy, per-module namespaces (`cobble-<id>` project, `cobble-<id>-*` volumes, prefixed containers), one private network per module, secrets generated and injected (the user never types one), default CPU/RAM limits.

## Manifest (schema under `sdk/`, Apache-2.0)
YAML as in PLAN.md §6: `id`, `version`, `category`, `description{fr,en}`, `license`, `provides`, `requires`, `exclusive`, `hardware`, `variants`, `web_ui`, `settings`, `secrets`, `healthcheck`, `integrations{ci,core}`, `backup`, `offline`.
Validation (unit-tested): images pinned by digest and never `:latest`; every `requires` resolvable in the catalogue; `exclusive` capabilities have at most one active provider; settings and secrets keys unique; FR and EN descriptions both present.

## Lifecycle
`resolve → check hardware → generate secrets → compose up (rewritten) → post-install → register-core → on-link (once per capability already present) → healthcheck`. Any failure rolls back in reverse order and reports a translated error code. Uninstall runs the inverse hooks, with an option to keep data. State lives in the database (tables `modules`, `module_secrets`, `module_events`, Alembic migration tested up and down) so the manager is resumable, like the scheduler.
The graph resolver and the rules engine are **pure functions**, tested by property tests over every install/uninstall order of a synthetic catalogue — this is the v0.2 criterion in test form.

## Catalogue
Recommended: a `catalog/` folder of this repository to begin with (a manifest per module plus a lock file listing the version combinations tested together in CI); a separate repository and third-party catalogues come in v0.4.

## From the v0.1 pack
`packs/v01/` is converted module by module (forgejo, woodpecker, ollama cpu/nvidia/amd, aider runner, agent-service, preview-service). Their hooks (`register-core`, `unlink`, `uninstall`) already follow the lifecycle above. `scripts/e2e_full.sh` must stay green after each conversion. The fake pack stays as the reference implementation of the capabilities for browser CI.

## Open points
1. Upgrade path from a v0.1 install: automatic migration or reinstall (no public install exists yet).
2. Hot reload of LiteLLM when Ollama is linked: confirm the supported mechanism in the pinned version.
3. GPU variants cannot run in CI: choose the variant by pure logic, unit-test it, test on real hardware by hand and say so in the release notes.
4. The licence of every catalogue module is checked before it is added (PLAN.md §16).
