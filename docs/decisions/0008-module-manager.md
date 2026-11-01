# 0008 — Module-manager, manifests and the official catalogue (v0.2)

Status: **draft, not accepted** — v0.2 work started before the v0.1 step 11 validation, by explicit owner decision. The text below is the original proposal; "What the implementation settled" records where the code differs from it or fills a gap. The owner still has to accept it.

## Principles
- **The module-manager is the only holder of the Docker socket** (rule 5), as a **separate service** (`module-manager`, the same backend image with another entry point), reachable only on an internal network. It takes over from v0.1's pack service for module containers. The backend never talks to Docker; it calls the module-manager's small internal HTTP API (the same pattern as `agent-service` in ADR 0006).
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

## What the implementation settled (v0.2, steps 1 to 16)
- **Where it lives.** `backend/cobble/module_manager/` (its own container from the backend image, compose profile `modules`, switched on by `COMPOSE_PROFILES` in `.env`); the SDK (`sdk/`, Apache-2.0) never imports `cobble`. The API and the CLI only call its HTTP service with a bearer token (`providers/module_manager.py`); they hold neither the vault key nor the Docker socket.
- **One operation endpoint.** `POST /v1/operations` with an action (install or uninstall) instead of two endpoints; one operation at a time; progress on the Redis stream `cobble:modules:events`.
- **Convergence.** The installed set is a pure function of the explicitly requested modules (resolver in the SDK), so any order of installs and uninstalls ends in the same state; dependencies are added automatically (a choice is requested when several modules can provide a capability) and cascades need confirmation.
- **What the core may read.** Only the secrets a manifest lists in `core_secrets` (for example a Git server's API token) are given to the core, by `GET /v1/connections` (worker only). `link_secrets` are shared with the hooks of modules that require the capability, as `COBBLE_PEER_<CAPABILITY>_*`, never with the core or the browser.
- **Hooks.** Bash, idempotent, run in the module-manager's container with a minimal environment (never its own settings): `pre_up` (after the required modules run, before the module starts: it can register an OAuth application and hand its secrets to the compose file), `post_install`, `register_core`, `pre_uninstall`, and provider-first link hooks. A hook gives secrets back as `::secret::KEY=VALUE` lines; nothing else is read.
- **Routes.** `web_ui` becomes a Caddy route built from validated fields only; routes are written validate-then-rename and loaded through Caddy's admin API on a unix socket in a volume shared with the module-manager only; a refused route rolls the install back.
- **Language-model gateway.** Backends declare `llm` (address and models, with per-flavour overrides); the manager writes the list to a file LiteLLM includes and restarts it (the supported way in the pinned version), restoring the previous list if it does not come back. The hardware flavour (CPU, NVIDIA, AMD) is chosen from the machine; a flavour may bring its own compose file. GPU flavours are verified by the compose rules and unit tests only, not on real hardware.
- **Failure model.** Any failure rolls the whole plan back; crashes are recovered at start-up; a removal never fails because the proxy or the gateway cannot be updated.
- **Still open.** Image distribution for modules that build their images locally (the agent and preview services are still the v0.1 pack until the owner decides between building on the host and CI-published digests); `keep-data` on uninstall; settings and secrets from the UI; a CA bundle option for module containers behind a TLS-inspecting proxy.
