# Installation

**English** · [Français](#français)

## Requirements

Ubuntu Server 24.04 or 26.04, or Debian 12 or 13, on **amd64**. At least 2 vCPU, 4 GB of RAM and 40 GB of disk. Internet access (to download Docker and images). Port 80 must be free.

## One command

```bash
curl -fsSL <install.sh URL> | sudo bash
```

If you prefer, download the script, read it, then run it (`sudo bash install.sh`). Options: `--dir`, `--lang en|fr`, `--yes` (non-interactive), `--gpu auto|nvidia|amd|none`, `--source`.

The script checks the machine, installs Docker from the official repository, installs the core in `/opt/cobble` (generated secrets, pinned images), creates the `cobble` systemd service, opens ports 80/443 if `ufw` is active, installs the `cobble` CLI, and prints a **one-use activation link** to create the admin account. It is **idempotent**: re-running it repairs things without overwriting anything. Log: `/var/log/cobble-install.log`.

## The `cobble` CLI

| Command | Purpose |
|---|---|
| `cobble status` | service state and health |
| `cobble logs [service]` | follow the logs |
| `cobble update` | update (backs up `.env` first) |
| `cobble doctor` | checks Docker, services, disk, ports and permissions, and suggests a fix for each failure |
| `cobble reset-admin` | prints a new link to change the email and password **without losing projects** |
| `cobble uninstall [--keep-data]` | uninstall |

`backup` and `restore` are not available in v0.1.

## Known limits

Plain HTTP for now (no automatic HTTPS), no GPU or Ollama in the starter pack, amd64 only.

---

## Français

## Prérequis

Ubuntu Server 24.04 ou 26.04, ou Debian 12 ou 13, **amd64**. Minimum 2 vCPU, 4 Go de RAM, 40 Go de disque. Accès Internet (pour télécharger Docker et les images). Le port 80 doit être libre.

## Une commande

```bash
curl -fsSL <URL de install.sh> | sudo bash
```

Pour les prudents: télécharger le script, le lire, puis l'exécuter (`sudo bash install.sh`). Options: `--dir`, `--lang fr|en`, `--yes` (non interactif), `--gpu auto|nvidia|amd|none`, `--source`.

Le script: vérifie la machine, installe Docker depuis le dépôt officiel, installe le noyau dans `/opt/cobble` (secrets générés, images épinglées), crée le service systemd `cobble`, ouvre 80/443 si `ufw` est actif, installe la CLI `cobble`, puis **affiche un lien d'activation à usage unique** pour créer le compte admin. Il est **idempotent**: le relancer répare sans rien écraser. Journal: `/var/log/cobble-install.log`.

## La CLI `cobble`

| Commande | Rôle |
|---|---|
| `cobble status` | état des services et santé |
| `cobble logs [service]` | journaux en continu |
| `cobble update` | met à jour (sauvegarde de `.env` avant) |
| `cobble doctor` | vérifie Docker, services, disque, ports, permissions; propose des correctifs |
| `cobble reset-admin` | nouveau lien pour changer le courriel et le mot de passe **sans perdre les projets** |
| `cobble uninstall [--keep-data]` | désinstalle |

`backup` et `restore` ne sont pas disponibles en v0.1.

## Limites connues

HTTP seulement pour l'instant (pas de HTTPS automatique); pas de GPU ni Ollama dans le pack de départ; amd64 seulement.
