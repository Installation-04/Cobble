# Installation

**Français** · [English](#english)

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

---

## English

**Requirements**: Ubuntu Server 24.04/26.04 or Debian 12/13 (**amd64**), 2 vCPU, 4 GB RAM, 40 GB disk, Internet access, port 80 free.

```bash
curl -fsSL <install.sh URL> | sudo bash
```

The script checks the machine, installs Docker from the official repository, installs the core in `/opt/cobble` (generated secrets, pinned images), creates the `cobble` systemd service, opens 80/443 if `ufw` is active, installs the `cobble` CLI, and prints a **one-use activation link** to create the admin account. It is **idempotent**: re-running repairs without overwriting anything. Log: `/var/log/cobble-install.log`.

CLI: `cobble status | logs | update | doctor | reset-admin | uninstall [--keep-data]` (`reset-admin` prints a new link to change the email and password **without losing projects**). `backup`/`restore` are not available in v0.1. Known limits: plain HTTP for now, no GPU/Ollama in the starter pack, amd64 only.
