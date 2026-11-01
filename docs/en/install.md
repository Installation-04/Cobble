# Installing Cobble

Cobble installs on a fresh Ubuntu or Debian machine with one command. The installer is
idempotent: running it again repairs or completes the install and never deletes your data.

## Quick install

```bash
curl -fsSL https://<your-domain>/install.sh | sudo bash
```

> `<your-domain>` is a placeholder: the official download address is not published yet.
> Until then, install from a checkout of the repository (see "From a checkout" below).

At the end the installer prints the address of your Cobble and a **one-use activation
link**. Open it in a browser to create the admin account.

## The cautious way

Download, verify, read, then run:

```bash
curl -fsSLO https://<your-domain>/install.sh
curl -fsSLO https://<your-domain>/install.sh.sha256
sha256sum -c install.sh.sha256      # must print: install.sh: OK
less install.sh                     # read it
sudo bash install.sh
```

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
| `--source <src>` | source tree: directory, tarball (file or URL) or git URL. Default: the checkout the script runs from, otherwise `$COBBLE_TARBALL_URL` |
| `--lang fr\|en` | language of the installer, the CLI and the app (default: from `$LANG`) |
| `--gpu auto\|nvidia\|amd\|none` | GPU handling (default `auto`). In v0.1 the GPU is only detected and recorded |
| `--yes`, `-y` | no confirmation prompt (non-interactive) |
| `--skip-checks` | skip the CPU/RAM/disk/port/Internet checks (CI, tests) |
| `--help` | show the help |

Example: `sudo bash install.sh --yes --lang en --dir /opt/cobble`.

## What gets installed

| Path | Content |
|---|---|
| `/opt/cobble/src` | copy of the source tree; images are built from it |
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
| `cobble update [--source S]` | back up `.env`, then rebuild and restart (or install the source `S`) |
| `cobble doctor` | check Docker, containers, HTTP health, disk, port, `.env` mode, systemd unit, GPU; each failure comes with a fix; exit code 1 if any check fails |
| `cobble reset-admin [--yes]` | sign the admin out and print a one-use link to set a new email and password (projects and data are kept) |
| `cobble modules list` / `status <id>` | the catalogue with each module's state and whether it fits this machine; the details of one module (which secrets are set, never their values) |
| `cobble modules packs` | the starter packs (a ready-made set of modules), whether each fits this machine, and which one is recommended |
| `cobble modules install --pack <id>` | install a starter pack: all its modules in one go |
| `cobble modules install <id>... [--yes] [--choose capability=module] [--replace]` | install modules; what they need is added automatically, you are shown the plan and asked first |
| `cobble modules uninstall <id>... [--yes]` | remove modules; if other modules depend on them you are asked about those too |
| `cobble uninstall [--keep-data] [--yes]` | stop and remove Cobble. `--keep-data` keeps `.env` and the data volumes |
| `cobble version` | versions |
| `cobble backup`, `cobble restore` | not available yet |

### Modules

From v0.2 the installer also starts the **module-manager**, the only part of Cobble that talks to
Docker to install other software (Git server, CI, model server...). It is configured in `.env`:
`MODULE_MANAGER_TOKEN` (generated, a secret), `COBBLE_CATALOG_DIR` (the catalogue shipped in
`<dir>/src/catalog`), `DOCKER_GID` (the group of the Docker socket) and `COMPOSE_PROFILES=modules`.
The same thing is available in the browser: the **Store** entry in the sidebar (administrators only)
lists the modules with their state and whether they fit this machine (a module that needs more memory
or a GPU you do not have is greyed, with the reason), and its drawer installs or removes a module:
you see what will happen first, you choose when several modules can provide something, you confirm
when removing a module takes others with it, and you follow the steps live.
Nothing is installed until you ask: try `cobble modules list`, then for example
`cobble modules install woodpecker` (the Git server it needs is added with it).

The module-manager keeps the secrets of the modules in an encrypted vault whose key lives in the
Docker volume `cobble-module-keys`. `cobble uninstall --keep-data` keeps that volume; without it, the
key and the modules' secrets are deleted together. If the key is lost while the modules remain, their
stored secrets cannot be read any more: remove and reinstall the modules.

If you installed the **v0.1 pack by hand** (`packs/v01/hooks/install.sh`), it keeps running but is
not managed by `cobble modules`. The installer says so; remove the pack
(`packs/v01/hooks/uninstall.sh`) and install the modules instead. Nothing is converted or deleted
for you.

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
- The download URL, checksums and signatures of release files are placeholders until the
  first release.
