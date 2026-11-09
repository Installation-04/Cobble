# ADR 0015 — Local package cache: Verdaccio and devpi as modules

Status: **proposed** (implemented in v0.3, waiting for the owner to accept); the agent wiring left out here is done in [ADR 0027](0027-package-cache-wiring.md).

## Context
PLAN.md §17 ("Cache local des paquets", v0.3) asks for npm and PyPI caches so that agent installs
are faster, work offline and use less bandwidth, plugged into the runners automatically.

## Decision
- Two official modules, `verdaccio` (npm) and `devpi` (PyPI), in `catalog/`. Each is a read-through
  cache: no web page (`web_ui.public: false`, no route on the reverse proxy, no host port), data in
  a named volume that is part of the backup, hard CPU / RAM / PID limits, a health check, images
  pinned by digest. Verdaccio runs with a shipped `config.yaml`: web interface off, no sign-up,
  nobody can publish. devpi uses the community image `jonasal/devpi-server` (MIT), because
  upstream publishes none; it is pinned by digest like the others.
- Capabilities: each provides `package-cache` and one specific capability (`npm-cache`,
  `pypi-cache`). The module-manager gives a consumer only the first provider of a capability
  (`_required_peers`), so a consumer that needs both ecosystems must require the specific ones.
- Neither module is in a starter pack and none is installed by default: they are optional.
- The core names neither product.

## Not done here (done in ADR 0027): wiring to the agent runners
The manifest only has `requires`, which is mandatory: if `aider` required `npm-cache` the cache
would become a hard dependency of the agents. Wiring them automatically needs more than a manifest
field:
1. an optional requirement (`wants:`) in the SDK schema and the resolver (links without
   installing, no cascade on removal, link hooks run when the cache appears later);
2. the agents' egress proxy allow-list (`COBBLE_AGENT_PROXY_ALLOW`) extended with the cache host,
   and the agent containers given `npm_config_registry` / `PIP_INDEX_URL` pointing at it by the
   agent service;
3. a decision on offline behaviour of the proxy for a cache miss.
This touches the resolver, the module-manager and the agent service, each with its own tests, so
it is left to a later step rather than done here as a "small addition".

## Consequences
The caches can be installed and used by hand today (and by any module that requires the specific
capability), and they are covered by the install / uninstall matrix test. The wiring to the agents is described in ADR 0027;
without a cache installed, agents still download from the public registries.

## Not verified
The images were not run (no Docker daemon where this was written): the data path of the devpi
image (`/devpi`), the Verdaccio read-only root file system and both health checks must be checked
with `make smoke-modules`-style runs on a real host.
