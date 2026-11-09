# ADR 0027 — Wiring the package caches to the agents with optional requirements

Status: **proposed** (implemented in v0.3, waiting for the owner to accept; no image was run, see "Not verified").

## Context
ADR 0015 shipped `verdaccio` and `devpi` but left the agents downloading from the public
registries: a `requires:` would make the cache mandatory, and the agents' egress proxy only allowed
the public hosts. PLAN.md section 17 wants the caches "plugged into the runners automatically".

## Decision
1. **SDK: `wants`.** A manifest may list `wants: [capability]`: "use it if it is installed".
   - It never adds a module to the installed set and never blocks an install or an uninstall (no
     cascade). `resolve` ignores it, so *the installed set is still a function of the requested
     modules*; only `desired_links` includes it, so the links, and the `on_link` / `on_unlink`
     hooks, appear and disappear with the provider, in any order.
   - `install_order` puts a provider of a wanted capability first when it can (the consumer then
     starts with the address), and drops that preference when it would make a cycle.
   - Validated by the manifest (`cobble-sdk lint`): no duplicates, not also in `requires`, not a
     capability the module provides. A provider may add `endpoint` (a path under its address) to a
     `provides` entry; `verdaccio` says `/`, `devpi` says `/root/pypi/+simple/`.
2. **Module-manager: the address as environment.** For each wanted capability with a running
   provider (the first by id) the compose rendering and the hooks of the consumer get
   `COBBLE_WANT_<CAPABILITY>_{MODULE,HOST,PORT,URL}` (an address only, never a secret; unset when
   nobody provides it). When a provider is linked after the consumer, or removed, the consumer is
   re-rendered and `up`-ed again (`rewire` event): Compose recreates only the services whose
   configuration changed. A rewire failure is reported and never rolls back or blocks the install
   or removal that caused it; the next change retries it.
3. **`aider` wants `npm-cache` and `pypi-cache`.** Its compose file appends exactly the cache host
   names to `AGENT_PROXY_ALLOW` and hands the two URLs to `agent-service`
   (`COBBLE_AGENT_NPM_REGISTRY`, `COBBLE_AGENT_PYPI_INDEX`), which sets in each agent container
   `npm_config_registry`, `PIP_INDEX_URL` + `PIP_TRUSTED_HOST` (plain HTTP index) and
   `UV_DEFAULT_INDEX` (plus `COBBLE_NPM_REGISTRY` / `COBBLE_PYPI_INDEX`). The agents still go out
   only through the proxy (`NO_PROXY` is unchanged, the network stays internal, no new capability,
   no Docker socket). The proxy filter matches host names, not ports; the cache modules expose a
   single port and the host name is the cache's own container.
4. **Offline behaviour.** On a miss the cache fetches from the public registry through its own
   uplink (already configured) and keeps the result. When the cache is down the install fails with
   the tool's network error (connection refused, or 502 from the proxy): there is **no silent
   fallback** to the public registry, because that would hide a broken cache and the restricted
   network is the safety property. The public hosts stay in the allow-list (a lock file such as
   `uv.lock` can record absolute URLs), so those files bypass the cache but not the proxy. To go
   back to the public registries, start the cache again or uninstall it (rewire). No dedicated
   message is added: the tools' own errors are what the agent and the task log show.

## Consequences
- The core names neither product: it knows `wants`, `endpoint` and capability names from the
  catalogue's manifests only; the URL layout lives in the providers' manifests.
- Wiring or unwiring restarts `agent-service` and the proxy; a run in flight is not guaranteed to
  survive it. Documented: do it when no agent works.
- A failed `agent-service` rewire leaves the old wiring until the next change.
- No migration: links already store `(consumer, provider, capability)`.

## Not verified
No image was run (no Docker daemon). Checked: `docker compose config` of the agents' compose file
with and without the cache variables, the fake runner for the rewire sequence, and the unit tests of
the SDK, the module-manager and agent-service. To check on a real host: that npm, pnpm, pip and uv
honour the variables in the runner image, that the proxy lets plain HTTP through to the cache host,
and the message seen by an agent when the cache is stopped.
