# Installing Cobble

Cobble installs on a fresh Ubuntu or Debian machine with one command. The installer is
idempotent: running it again repairs or completes the install and never deletes your data.

## Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/Installation-04/Cobble/main/installer/install.sh | sudo bash
```

The script downloads the **latest release** from GitHub (`Installation-04/Cobble`), checks its
SHA-256, then installs it. A release uses the published, digest-pinned images: nothing is built
on your machine. If no release is published yet, the installer says so and suggests
`--ref main` (see below).

To install a specific release or another branch:

```bash
curl -fsSL https://raw.githubusercontent.com/Installation-04/Cobble/main/installer/install.sh | sudo bash -s -- --version v0.3.0
curl -fsSL https://raw.githubusercontent.com/Installation-04/Cobble/main/installer/install.sh | sudo bash -s -- --ref main     # NOT a verified release, built from source
```

At the end the installer prints the address of your Cobble and a **one-use activation
link**. Open it in a browser to create the admin account.

## The cautious way

Download, verify, read, then run, using the files attached to the release:

```bash
curl -fsSLO https://github.com/Installation-04/Cobble/releases/latest/download/install.sh
curl -fsSLO https://github.com/Installation-04/Cobble/releases/latest/download/install.sh.sha256
sha256sum -c install.sh.sha256      # must print: install.sh: OK
less install.sh                     # read it
sudo bash install.sh
```

The `install.sh` of a release then downloads the `cobble.tar.gz` of the same release and its
`cobble.tar.gz.sha256`, compares the SHA-256 and **stops without installing anything** if the
checksum file is missing, malformed or different. Nothing is unpacked before the check passed.
To do that step by hand too: download `cobble.tar.gz` and `cobble.tar.gz.sha256` from the
release page, run `sha256sum -c cobble.tar.gz.sha256`, then
`sudo bash install.sh --source ./cobble.tar.gz` (a local file is used as is).

## From a checkout

```bash
git clone <repository-url> cobble && cd cobble
sudo installer/install.sh
```

Without `--source`, the installer copies the checkout it runs from. Run this way, no
download URL is needed.

## Requirements

| | Minimum |
|---|---|
| OS | Ubuntu Server 24.04 or 26.04, Debian 12 or 13 |
| CPU architecture | amd64 (arm64 is not supported yet) |
| Resources | 2 vCPU, 4 GB RAM, 40 GB free disk (no local models) |
| Network | Internet access; ports 80 (used) and 443 (reserved) free |
| Access | root or `sudo` |

A VM is recommended. In Proxmox LXC the container must be privileged with `nesting=1` and
`keyctl=1`; the installer detects LXC and warns.

## Options

| Option | Meaning |
|---|---|
| `--dir <path>` | install directory (default `/opt/cobble`) |
| `--source <src>` | source tree: directory, tarball (file or URL) or git URL. Default: the checkout the script runs from, otherwise the latest GitHub release. A tarball URL needs a `<URL>.sha256` file next to it |
| `--version vX.Y.Z` | install that release (`cobble.tar.gz` from its GitHub release, SHA-256 verified) |
| `--ref <branch\|tag\|sha>` | install a GitHub archive of that ref (`codeload.github.com`), built from source. **Not a verified release** (no checksum exists): a warning is printed. For testing and development |
| `--no-verify` | skip the SHA-256 check of a downloaded tarball. **Unsafe**: only for tests or an air-gapped mirror you trust |
| `COBBLE_REPO=owner/name` | environment variable: download from another GitHub repository (a fork). Default `Installation-04/Cobble` |
| `--lang fr\|en` | language of the installer, the CLI and the app (default: from `$LANG`) |
| `--gpu auto\|nvidia\|amd\|none` | GPU handling (default `auto`). In v0.1 the GPU is only detected and recorded |
| `--yes`, `-y` | no confirmation prompt (non-interactive) |
| `--skip-checks` | skip the CPU/RAM/disk/port/Internet checks (CI, tests) |
| `--help` | show the help |

Example: `sudo bash install.sh --yes --lang en --dir /opt/cobble`.

## Published images and updates

A release tarball contains `core/compose.release.yml`, an override that replaces the local
`build:` of the core services by `image: ghcr.io/installation-04/cobble-<service>@sha256:<digest>`.
When this file is present in `/opt/cobble/src/core/`, the installer, the systemd unit and the
`cobble` command add it to every `docker compose` call, so the images are **pulled** and nothing
is built. A tree without it (a checkout, `--ref`) is built from source as before.

To update: `sudo cobble update --latest` (or `--version vX.Y.Z`). The new tree replaces
`/opt/cobble/src`, your `.env` and your data stay (a dated copy of `.env` is kept), the new
images are pulled and the stack restarts. `sudo cobble update` alone restarts the installed
version. Switching from a release to `--ref` (or back) is allowed: the build method follows
the tree you installed.

## What gets installed

| Path | Content |
|---|---|
| `/opt/cobble/src` | copy of the source tree; images are built from it (or pulled, for a release) |
| `/opt/cobble/.env` | secrets and settings, mode 0600, generated once and **never overwritten** |
| `/opt/cobble/compose.install.yml` | generated override that gives the API its public URL |
| `/opt/cobble/state.json` | install version, date, OS, GPU, language |
| `/etc/systemd/system/cobble.service` | starts Cobble at boot (`docker compose up -d --wait`) |
| `/usr/local/bin/cobble` | the CLI |
| `/var/log/cobble-install.log` | install journal (appended on each run) |
| Docker volumes `cobble_*` | database, Redis, Caddy data |

Docker Engine comes from the official Docker apt repository (never the distribution
package). An existing Docker is reused if `docker compose` works and the server is 24 or
later. If `ufw` is active, ports 80 and 443 are opened; SSH is not touched.

## The `cobble` command

| Command | What it does |
|---|---|
| `cobble status` | containers and web health |
| `cobble logs [service]` | follow the logs |
| `cobble update [--latest\|--version V\|--ref R\|--source S]` | back up `.env`, then rebuild (or pull the published images) and restart; with an option, fetch that source first (`--latest`: the latest release) with the same SHA-256 check as the installer |
| `cobble doctor` | check Docker, containers, HTTP health, disk, port, `.env` mode, systemd unit, GPU; each failure comes with a fix; exit code 1 if any check fails |
| `cobble reset-admin [--yes]` | sign the admin out and print a one-use link to set a new email and password (projects and data are kept) |
| `cobble modules list` / `status <id>` | the catalogue with each module's state and whether it fits this machine; the details of one module (which secrets are set, never their values) |
| `cobble modules packs` | the starter packs (a ready-made set of modules), whether each fits this machine, and which one is recommended |
| `cobble modules install --pack <id>` | install a starter pack: all its modules in one go |
| `cobble modules install <id>... [--yes] [--choose capability=module] [--replace]` | install modules; what they need is added automatically, you are shown the plan and asked first |
| `cobble modules uninstall <id>... [--yes]` | remove modules; if other modules depend on them you are asked about those too |
| `cobble models list` / `add <openai\|anthropic\|openrouter\|custom> <model> [--base-url URL] [--no-default]` / `test <name>` / `default <name>` / `remove <name> [--yes]` | connect a model service with an API key (typed at a hidden prompt or piped on stdin, never an argument), test it and choose the default model. Same as the **Models** tab in Settings. The gateway restarts: allow about 20 seconds |
| `cobble models route [role [model...]] [--clear]` | which models each role tries, in order: the first one, then fallbacks if it cannot answer (key refused, no balance, rate limit, unknown model, service down). Roles: `planner`, `test-writer`, `worker`, `reviewer`, `escalation`. No arguments: show them all. Same as the role routes in **Settings → Models**; takes effect at the next request |
| `cobble models preset [id] [--local M] [--cheap M] [--strong M]` | ready-made routes for all roles. `economical-local`: code and tests on a model served on this machine, the strong model plans and takes over; `balanced`: an inexpensive model writes tests and code, the strong one plans and reviews. A preset only arranges the models you give it (`--local` defaults to the first model an installed backend serves, `--strong` to the default model, `--cheap` to the strong one); without an id it lists the presets and what each still needs. Same as **Presets** in Settings → Models; it replaces the routes of every role |
| `cobble models benchmark [model...] [--show] [--allow-paid] [--apply]` | measures models on 8 small coding tasks with hidden test cases. The generated code runs in the module-manager sandbox (no network, read-only, limited CPU/RAM/time), never on the host. Only models served on this machine are measured unless you name others and pass `--allow-paid` (that spends tokens). Prints the share of cases passed and tokens/s, and proposes the best `worker` model: the fastest among those within 5 points of the best quality (at least 50 %). `--apply` puts it first in the `worker` route, keeping the rest as fallbacks; `--show` prints the last results without running. The same benchmark runs from **Settings → Models → Local benchmark → Run benchmark**: tick the models (paid ones are unticked and spend tokens), watch the progress (task x of 8 for the model being measured), see the results refresh when it ends. It runs as a background job of the worker (one run at a time; the worker does no other job meanwhile), and a failure such as an unavailable sandbox is shown there. Same results as the command |
| `cobble models prices` | the last price seen of each model (USD per million tokens), with a **free tier** mark and a warning when a price changed in the last 14 days. Your routes are never changed because of a price. Free tiers (zero price, or OpenRouter `:free` models) have low rate limits (a model that answers 429 is tried after the others for a while, 30 s doubling up to 10 min) and provider terms: check them, some use your requests for training. Same data as **Prices** in Settings → Models |
| `cobble uninstall [--keep-data] [--yes]` | stop and remove Cobble. `--keep-data` keeps `.env` and the data volumes |
| `cobble version` | versions |
| `cobble backup`, `cobble restore` | not available yet |

### Modules

From v0.2 the installer also starts the **module-manager**, the only part of Cobble that talks to
Docker to install other software (Git server, CI, model server...). It is configured in `.env`:
`MODULE_MANAGER_TOKEN` (generated, a secret), `COBBLE_CATALOG_DIR` (the catalogue shipped in
`<dir>/src/catalog`), `DOCKER_GID` (the group of the Docker socket) and `COMPOSE_PROFILES=modules`.
The same thing is available in the browser: the **Store** entry in the sidebar (administrators only)
starts with the **starter packs** (a ready-made set of modules; the one recommended for this machine
is marked) and lists the modules with their state and whether they fit this machine (a module that needs more memory
or a GPU you do not have is greyed, with the reason), and its drawer installs or removes a module:
you see what will happen first, you choose when several modules can provide something, you confirm
when removing a module takes others with it, and you follow the steps live.
Nothing is installed until you ask: try `cobble modules list`, then for example
`cobble modules install woodpecker` (the Git server it needs is added with it).

The module-manager keeps the secrets of the modules in an encrypted vault whose key lives in the
Docker volume `cobble-module-keys`. `cobble uninstall --keep-data` keeps that volume; without it, the
key and the modules' secrets are deleted together. If the key is lost while the modules remain, their
stored secrets cannot be read any more: remove and reinstall the modules.

The agents and the demo previews are modules too (`cobble modules install --pack local-cpu` installs
the whole set). If you installed the **v0.1 pack by hand**, it is no longer supported or detected:
remove its containers and volumes yourself (compose projects `cobble-pack`, `cobble-pack-agents`,
`cobble-pack-preview`) and install the modules instead; nothing is converted or deleted for you
(see [the official modules](modules.md)).

If you installed with `--dir`, set `COBBLE_DIR` only when the CLI cannot find the install
(the installer already records the directory in the CLI).

## Uninstall

```bash
sudo cobble uninstall               # removes everything, including the data
sudo cobble uninstall --keep-data   # keeps /opt/cobble/.env and the Docker volumes
```

Docker itself is not removed.

## Troubleshooting

Start with `sudo cobble doctor`. Typical failures:

- **A container is `exited` or `unhealthy`**: `cobble logs <service>`, then
  `sudo systemctl restart cobble`.
- **No answer on the web address**: check that `caddy` is healthy and that no firewall
  blocks port 80 (cloud providers have their own firewall).
- **Wrong address in the activation link**: edit `COBBLE_PUBLIC_URL` in `/opt/cobble/.env`
  (the installer never rewrites an existing `.env`), then `sudo systemctl restart cobble`.
- **No activation link at the end**: the admin already exists. Run `sudo cobble reset-admin`.
- **The install stops at a check**: the message names the missing prerequisite. `--skip-checks`
  bypasses the resource checks for testing only.

## Known limitations of v0.1

- Plain HTTP only. HTTPS (Let's Encrypt or an internal CA) comes later; do not expose the
  port directly to the Internet, put it behind your own reverse proxy or VPN.
- No GPU modules yet: the GPU is detected and recorded in `state.json`; NVIDIA Container
  Toolkit setup is attempted when a driver is present, and never blocks the install.
- amd64 only.
- No `backup` / `restore` yet. Copy `/opt/cobble/.env` and dump the database yourself.
- Release files carry a SHA-256 checksum, not a signature yet: the check protects against a
  corrupt or swapped download, and relies on GitHub and TLS for who published it.
