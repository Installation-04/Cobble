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

Starter packs (`catalog/packs/`) bundle them: `local-gpu`, `local-cpu` and `api-only`.

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
