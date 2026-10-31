# The v0.1 pack: git server and CI

Cobble's core never names a product: it talks to the `GitProvider` and `CIProvider` capabilities.
The fixed v0.1 pack (`packs/v01/`) implements them with **Forgejo** (git) and **Woodpecker** (CI).

| Service | Image (pinned by digest) | Role |
|---|---|---|
| `forgejo` | `codeberg.org/forgejo/forgejo:15.0.11-rootless@sha256:3cd6bc2b...` | git server (SQLite, HTTP only, private repos) |
| `woodpecker-server` | `quay.io/woodpeckerci/woodpecker-server:v3.20.1@sha256:0f31560e...` | CI server (SQLite) |
| `woodpecker-agent` | `quay.io/woodpeckerci/woodpecker-agent:v3.20.1@sha256:a7d7299a...` | runs pipeline steps in containers |
| `pack-gateway` | `caddy:2-alpine@sha256:e70b164d...` | lets pipeline containers reach the public git URL |

Compose project `cobble-pack`, own networks and volumes (`cobble-pack-*`). **No port is published**:
the core's Caddy exposes the web UIs.

## Install and wiring

```
make dev                               # the core first: the pack joins its `cobble_core` network
COBBLE_PACK_PUBLIC_URL=http://192.168.1.20 packs/v01/hooks/install.sh
```

`install.sh` is idempotent (re-running keeps existing secrets; `--rotate` regenerates them). Without
any human interaction it:

1. generates secrets into `packs/v01/.env` (mode 600, git-ignored);
2. starts Forgejo and creates the service account (`forgejo admin user create`) and its API token;
3. creates the OAuth application of Woodpecker in Forgejo (`/api/v1/user/applications/oauth2`) and
   gives its client id/secret to `woodpecker-server`;
4. starts Woodpecker, then **signs the service account in headlessly** (`hooks/wp_login.py`, run in
   a throw-away container on the private network: it plays the browser through the OAuth redirects
   and accepts the consent screen) and mints its Woodpecker API token. The service account is the
   Woodpecker admin (`WOODPECKER_ADMIN`);
5. writes `packs/v01/.env.pack` (`hooks/register-core.sh`).

Per repository, `WoodpeckerCI.activate` registers the repository in Woodpecker, which creates the
webhook in Forgejo by itself, and applies safe settings (never "trusted", 30 minute timeout).

Other hooks: `register-core.sh` (rewrite `.env.pack`), `unlink.sh` (delete it), `uninstall.sh [--purge]`
(stop the pack; `--purge` also deletes data and secrets), `test-flow.sh` (see below).

## How the core consumes it

Load `packs/v01/.env.pack` in the `api` and `worker` services (`env_file`) and attach them to the
network shared with the pack (the pack declares `cobble_core` as external). It defines:

```
COBBLE_PACK_FORGEJO_URL=http://forgejo:3000
COBBLE_PACK_FORGEJO_TOKEN=...
COBBLE_PACK_FORGEJO_OWNER=cobble-bot
COBBLE_PACK_WOODPECKER_URL=http://woodpecker-server:8000/ci
COBBLE_PACK_WOODPECKER_TOKEN=...
```

Optional: `COBBLE_PACK_DEFAULT_BRANCH` (main), `COBBLE_PACK_MERGE_STYLE` (squash), `COBBLE_PACK_REQUIRED_CHECK`
(`ci/woodpecker/pr/*`), `COBBLE_PACK_CI_POLL_INTERVAL_S` (5). In code:
`from cobble.providers import ForgejoGit, WoodpeckerCI, load_settings`.
`ForgejoGit(settings, ci=WoodpeckerCI(settings))`.

Web UIs: import `packs/v01/caddy/pack.caddy` in the core's site block: `/git/*` goes to Forgejo (prefix
stripped, `ROOT_URL=<public url>/git/`) and `/ci/*` to Woodpecker (`WOODPECKER_HOST=<public url>/ci`).

## "Green or no merge", enforced twice

* `ForgejoGit.merge` raises `MergeRefused` unless the pipeline of the pull request's **current** head
  commit is green (checked through the CI provider; without one, through Forgejo's commit statuses).
* When a repository is created, the default branch is protected in Forgejo: no direct push, required
  status check `ci/woodpecker/pr/*`, and the rule applies to administrators too. A merge that bypasses our
  code is refused by the server.

Repositories are created from a template directory. `{{project_name}}` is replaced by the repository
name in every text file. The template `templates/fastapi-react` ships a pipeline with lint, backend and
frontend tests, Semgrep, Trivy and Gitleaks (images pinned, failing on high severity findings).

## Security notes

* `woodpecker-agent` is the **only** container that mounts the Docker socket (CLAUDE.md rule 5 allows
  it for a pack service). Whoever controls a pipeline controls the host's Docker. Mitigations: the agent
  has no published port and no capabilities, runs as an unprivileged user (socket access through the
  Docker group), repositories are never "trusted" (no privileged steps, no host volumes), steps have
  memory/CPU limits (`PACK_STEP_MEM_BYTES`, `PACK_STEP_CPU_QUOTA`), only Cobble-created repositories are
  activated. Do not give untrusted people write access to the Forgejo instance.
* Git credentials reach pipelines only through Woodpecker's clone step. The service account token is
  never given to pipelines. Tokens live in files of mode 600; `ForgejoGit` passes credentials to `git`
  by environment, never on the command line nor in `.git/config`.
* The private `pack` network is `internal`. Forgejo and pipeline steps share the `ci` network, which has
  internet access (package registries).

## Limits of v0.1

* The Woodpecker web login (browser OAuth) is not available: the CI server talks to Forgejo over the
  private network. Pipeline results are read through the API; the git UI is at `/git/`.
* If the public URL is an IP address, pipeline containers must be able to reach it (host firewall);
  with a host name, `pack-gateway` answers to that name on the `ci` network.
* Scanners need the network (Trivy database, Semgrep rules, PyPI/npm). On hosts without internet,
  set `COBBLE_PACK_SKIP_STEPS=trivy,semgrep` at install time: an operator setting, not a repository one.
  Behind a TLS-inspecting proxy set `COBBLE_PACK_STEP_CA=/path/ca.pem`.
* SQLite for both services. Rebase of a branch that fell behind is not automated here.

## Testing

* `make test-backend` runs `test_pack_providers.py` (mocked HTTP) and `test_pack_invariants.py`.
* `packs/v01/hooks/test-flow.sh` starts a throw-away pack (own project, ONE port on `127.0.0.1:18081`),
  runs `backend/tests/integration/test_pack_flow.py` (green merge request merged, red one refused, direct
  merge and push refused by the server) and removes everything. It needs the core network and `uv`.
