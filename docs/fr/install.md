# Installer Cobble

Cobble s'installe sur une machine Ubuntu ou Debian toute neuve avec une seule commande.
L'installateur est idempotent : le relancer répare ou complète l'installation et ne supprime
jamais vos données.

## Installation rapide

```bash
curl -fsSL https://<votre-domaine>/install.sh | sudo bash
```

> `<votre-domaine>` est un espace réservé : l'adresse officielle de téléchargement n'est pas
> encore publiée. D'ici là, installez depuis une copie du dépôt (voir « Depuis un dépôt »).

À la fin, l'installateur affiche l'adresse de votre Cobble et un **lien d'activation à usage
unique**. Ouvrez-le dans un navigateur pour créer le compte admin.

## La voie prudente

Télécharger, vérifier, lire, puis exécuter :

```bash
curl -fsSLO https://<votre-domaine>/install.sh
curl -fsSLO https://<votre-domaine>/install.sh.sha256
sha256sum -c install.sh.sha256      # doit afficher : install.sh: OK
less install.sh                     # le lire
sudo bash install.sh
```

## Depuis un dépôt

```bash
git clone <url-du-depot> cobble && cd cobble
sudo installer/install.sh
```

Sans `--source`, l'installateur copie le dépôt d'où il est lancé : aucune URL de
téléchargement n'est nécessaire.

## Prérequis

| | Minimum |
|---|---|
| Système | Ubuntu Server 24.04 ou 26.04, Debian 12 ou 13 |
| Architecture | amd64 (arm64 pas encore supporté) |
| Ressources | 2 vCPU, 4 Go de RAM, 40 Go de disque libre (sans modèles locaux) |
| Réseau | accès Internet; ports 80 (utilisé) et 443 (réservé) libres |
| Droits | root ou `sudo` |

Une VM est recommandée. Dans un LXC Proxmox, le conteneur doit être privilégié avec
`nesting=1` et `keyctl=1`; l'installateur détecte LXC et avertit.

## Options

| Option | Rôle |
|---|---|
| `--dir <chemin>` | répertoire d'installation (défaut `/opt/cobble`) |
| `--source <src>` | sources : dossier, archive (fichier ou URL) ou URL git. Défaut : le dépôt d'où le script est lancé, sinon `$COBBLE_TARBALL_URL` |
| `--lang fr\|en` | langue de l'installateur, de la CLI et de l'application (défaut : selon `$LANG`) |
| `--gpu auto\|nvidia\|amd\|none` | gestion du GPU (défaut `auto`). En v0.1 le GPU est seulement détecté et noté |
| `--yes`, `-y` | aucune confirmation (mode non interactif) |
| `--skip-checks` | ignorer les vérifications CPU/RAM/disque/ports/Internet (CI, tests) |
| `--help` | afficher l'aide |

Exemple : `sudo bash install.sh --yes --lang fr --dir /opt/cobble`.

## Ce qui est installé

| Chemin | Contenu |
|---|---|
| `/opt/cobble/src` | copie des sources; les images sont construites depuis elle |
| `/opt/cobble/.env` | secrets et réglages, mode 0600, générés une fois et **jamais écrasés** |
| `/opt/cobble/compose.install.yml` | surcharge générée qui donne à l'API son URL publique |
| `/opt/cobble/state.json` | version installée, date, système, GPU, langue |
| `/etc/systemd/system/cobble.service` | démarre Cobble au boot (`docker compose up -d --wait`) |
| `/usr/local/bin/cobble` | la CLI |
| `/var/log/cobble-install.log` | journal d'installation (complété à chaque exécution) |
| Volumes Docker `cobble_*` | base de données, Redis, données de Caddy |

Docker Engine vient du dépôt apt officiel de Docker (jamais du paquet de la distribution).
Un Docker existant est réutilisé si `docker compose` fonctionne et que le serveur est en
version 24 ou plus. Si `ufw` est actif, les ports 80 et 443 sont ouverts; SSH n'est pas touché.

## La commande `cobble`

| Commande | Rôle |
|---|---|
| `cobble status` | conteneurs et santé web |
| `cobble logs [service]` | suivre les journaux |
| `cobble update [--source S]` | sauvegarde `.env`, puis reconstruit et redémarre (ou installe la source `S`) |
| `cobble doctor` | vérifie Docker, conteneurs, santé HTTP, disque, port, mode de `.env`, unité systemd, GPU; chaque échec est accompagné d'un correctif; code de sortie 1 si une vérification échoue |
| `cobble reset-admin [--yes]` | déconnecte l'admin et affiche un lien à usage unique pour définir un nouveau courriel et mot de passe (projets et données conservés) |
| `cobble modules list` / `status <id>` | le catalogue avec l'état de chaque module et s'il convient à cette machine; le détail d'un module (quels secrets sont définis, jamais leurs valeurs) |
| `cobble modules packs` | les packs de départ (un ensemble de modules prêt à l'emploi), si chacun convient à cette machine, et lequel est recommandé |
| `cobble modules install --pack <id>` | installe un pack de départ : tous ses modules d'un coup |
| `cobble modules install <id>... [--yes] [--choose capacité=module] [--replace]` | installe des modules; ce dont ils ont besoin est ajouté automatiquement, le plan vous est montré et on vous demande d'abord |
| `cobble modules uninstall <id>... [--yes]` | retire des modules; si d'autres modules en dépendent, on vous interroge aussi à leur sujet |
| `cobble uninstall [--keep-data] [--yes]` | arrête et retire Cobble. `--keep-data` garde `.env` et les volumes de données |
| `cobble version` | versions |
| `cobble backup`, `cobble restore` | pas encore disponibles |

### Modules

Depuis la v0.2, l'installateur démarre aussi le **gestionnaire de modules**, la seule partie de
Cobble qui parle à Docker pour installer d'autres logiciels (serveur Git, CI, serveur de modèles...).
Il se configure dans `.env` : `MODULE_MANAGER_TOKEN` (généré, un secret), `COBBLE_CATALOG_DIR`
(le catalogue livré dans `<dir>/src/catalog`), `DOCKER_GID` (le groupe du socket Docker) et
`COMPOSE_PROFILES=modules`. Rien n'est installé tant que vous ne le demandez pas : essayez
`cobble modules list`, puis par exemple `cobble modules install woodpecker` (le serveur Git dont il a
besoin est ajouté avec lui).

La même chose est disponible dans le navigateur : l'entrée **Magasin** du menu latéral (réservée aux
administrateurs) commence par les **packs de départ** (un ensemble de modules prêt à l'emploi; celui qui est recommandé
pour cette machine est signalé) et liste les modules avec leur état et s'ils conviennent à cette machine (un module qui
demande plus de mémoire ou un GPU que vous n'avez pas est grisé, avec la raison), et son panneau
installe ou retire un module : vous voyez d'abord ce qui va se passer, vous choisissez quand plusieurs
modules peuvent fournir la même chose, vous confirmez quand retirer un module en emporte d'autres, et
vous suivez les étapes en direct.

Le gestionnaire garde les secrets des modules dans un coffre chiffré dont la clé vit dans le volume
Docker `cobble-module-keys`. `cobble uninstall --keep-data` conserve ce volume; sans cette option, la
clé et les secrets des modules sont supprimés ensemble. Si la clé est perdue alors que les modules
restent, leurs secrets enregistrés ne peuvent plus être lus : retirez puis réinstallez les modules.

Si vous avez installé **le pack v0.1 à la main** (`packs/v01/hooks/install.sh`), il continue de
fonctionner mais n'est pas géré par `cobble modules`. L'installateur le signale; retirez le pack
(`packs/v01/hooks/uninstall.sh`) et installez les modules à la place. Rien n'est converti ni supprimé
à votre place.

## Désinstaller

```bash
sudo cobble uninstall               # supprime tout, données comprises
sudo cobble uninstall --keep-data   # garde /opt/cobble/.env et les volumes Docker
```

Docker lui-même n'est pas retiré.

## Dépannage

Commencez par `sudo cobble doctor`. Échecs typiques :

- **Un conteneur est `exited` ou `unhealthy`** : `cobble logs <service>`, puis
  `sudo systemctl restart cobble`.
- **Aucune réponse à l'adresse web** : vérifiez que `caddy` est sain et qu'aucun pare-feu
  ne bloque le port 80 (les hébergeurs ont leur propre pare-feu).
- **Mauvaise adresse dans le lien d'activation** : modifiez `COBBLE_PUBLIC_URL` dans
  `/opt/cobble/.env` (l'installateur ne réécrit jamais un `.env` existant), puis
  `sudo systemctl restart cobble`.
- **Pas de lien d'activation à la fin** : le compte admin existe déjà. Lancez
  `sudo cobble reset-admin`.
- **L'installation s'arrête sur une vérification** : le message nomme le prérequis manquant.
  `--skip-checks` ignore les vérifications de ressources, pour les tests seulement.

## Limites connues de la v0.1

- HTTP seulement. HTTPS (Let's Encrypt ou autorité interne) viendra plus tard; n'exposez pas
  le port directement sur Internet, placez-le derrière votre propre proxy inverse ou un VPN.
- Pas encore de modules GPU : le GPU est détecté et noté dans `state.json`; la
  configuration du NVIDIA Container Toolkit est tentée si un pilote est présent, sans jamais
  bloquer l'installation.
- amd64 seulement.
- Pas encore de `backup` / `restore`. Copiez `/opt/cobble/.env` et exportez la base vous-même.
- L'URL de téléchargement, les sommes de contrôle et les signatures des fichiers de version
  sont des espaces réservés jusqu'à la première version.
