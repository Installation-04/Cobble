# The official modules

Cobble's core never names a product: it talks to the `GitProvider`, `CIProvider`, `AgentRunner`,
`PreviewProvider` and `LLMClient` capabilities. The official modules in `catalog/` implement them;
the module-manager installs, links and removes them ([ADR 0008](../decisions/0008-module-manager.md)).
Install from the Store tab, or `cobble modules install <id>` / `cobble modules install --pack <id>`.

| Module | Provides | Needs | What it runs |
|---|---|---|---|
| `forgejo` | `git` | | Forgejo, the Git server (SQLite, HTTP only, private repositories), under `/git` |
| `woodpecker` | `ci` | `git` | Woodpecker server and agent (SQLite), under `/ci`; signed in to Forgejo through OAuth |
| `ollama` | `llm-backend` | | Ollama, in a CPU, NVIDIA or AMD flavour chosen from the machine; its models are added to the gateway |
| `aider` | `agent-runner` | `git` | agent-service, the egress proxy and the Aider runner image: [agents](agents.md) |
| `preview` | `preview` | `git` | preview-service, which builds and serves the milestone demos under `/demo`: [demos](demo.md) |

| `verdaccio` | `package-cache`, `npm-cache` | | Verdaccio, a read-through cache of the npm registry; no web page, nobody can publish |
| `devpi` | `package-cache`, `pypi-cache` | | devpi, a read-through mirror of PyPI; reachable on the platform network only |

Starter packs (`catalog/packs/`) bundle them: `local-gpu`, `local-cpu` and `api-only`. The two
package caches are in no pack: they are optional, install them from the Store.

## Local package cache (optional)

`verdaccio` and `devpi` keep a copy of every package they have served, so that the next install is
fast, still works offline for what was already downloaded, and uses less bandwidth. They run on the
platform network only (`web_ui.public: false`, no host port, no route on the reverse proxy), keep
their data in a volume (included in backups), and are limited to 512 MB / 1 CPU (Verdaccio) and
768 MB / 1 CPU (devpi). Other modules reach them at `http://cobble-verdaccio-verdaccio:4873` and
`http://cobble-devpi-devpi:3141` (the Python index is `/root/pypi/+simple/`). Each provides the
shared capability `package-cache` and an ecosystem one (`npm-cache`, `pypi-cache`): a consumer
should require the specific one, since a module linked to a capability sees only one provider.

**Not wired to the agents yet.** The manifest has no optional requirement, and the agents' egress
proxy only allows the public registries, so the agent runners do not use the caches yet. Doing it
needs a small core change (optional links in the manifest and the resolver, then the allow-list and
the `npm` / `pip` index variables for the runner); it is described in
[ADR 0015](../decisions/0015-package-cache.md).

## What every module follows

- **Images pinned by digest**, never `:latest`. The images of `aider` and `preview` are built from
  this repository by the "Module images" workflow (`.github/workflows/images.yml`), published to
  `ghcr.io/<owner>/cobble-*` and pinned with `scripts/pin_images.py`. The GHCR packages must be
  public for an installation without a registry login.
- **No published host port**: the module-manager removes them; the reverse proxy exposes a web
  address only for modules that declare one (`web_ui`, public unless `public: false`).
- **Names, networks and limits are the platform's**: everything is renamed `cobble-<id>-…`, only
  declared services join the shared network, default CPU/memory/PID limits apply.
- **Secrets**: generated or produced by hooks, stored encrypted; the core reads only a module's
  `core_secrets`, a module that requires a capability reads only the provider's `link_secrets`.
- **The Docker socket** is mounted by exactly three modules, each declaring `host_access:
  [docker_socket]`: `woodpecker` (its agent starts pipeline containers), `aider` (starts the agent
  containers) and `preview` (builds and starts the demo containers). Each runs as an unprivileged user
  that joins the socket's group; none runs the code it starts.

## Writing one

`cobble-sdk init`, `lint` and `test` (see `sdk/README.md`) scaffold, check and try a module.

## Coming from the v0.1 pack

The v0.1 pack (`packs/v01`, installed by hand) is gone. If you installed it, remove its containers and
volumes (compose projects `cobble-pack`, `cobble-pack-agents`, `cobble-pack-preview`) and install the
modules instead: repositories and CI history of the old Forgejo and Woodpecker are not migrated.
