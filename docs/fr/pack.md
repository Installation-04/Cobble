# Le pack v0.1: serveur git et CI

Le noyau de Cobble ne nomme jamais un produit: il parle aux capacités `GitProvider` et `CIProvider`.
Le pack fixe de la v0.1 (`packs/v01/`) les implémente avec **Forgejo** (git) et **Woodpecker** (CI).

| Service | Image (épinglée par digest) | Rôle |
|---|---|---|
| `forgejo` | `codeberg.org/forgejo/forgejo:15.0.11-rootless@sha256:3cd6bc2b...` | serveur git (SQLite, HTTP seulement, dépôts privés) |
| `woodpecker-server` | `quay.io/woodpeckerci/woodpecker-server:v3.20.1@sha256:0f31560e...` | serveur CI (SQLite) |
| `woodpecker-agent` | `quay.io/woodpeckerci/woodpecker-agent:v3.20.1@sha256:a7d7299a...` | exécute les étapes des pipelines dans des conteneurs |
| `pack-gateway` | `caddy:2-alpine@sha256:e70b164d...` | permet aux conteneurs de pipeline de joindre l'URL publique du git |

Projet compose `cobble-pack`, réseaux et volumes propres (`cobble-pack-*`). **Aucun port n'est publié**:
le Caddy du noyau expose les interfaces web.

## Installation et branchement

```
make dev                               # le noyau d'abord: le pack rejoint son réseau `cobble_core`
COBBLE_PACK_PUBLIC_URL=http://192.168.1.20 packs/v01/hooks/install.sh
```

L'URL publique doit être joignable **depuis l'intérieur d'un conteneur** (les étapes de CI y clonent): un nom ou l'adresse LAN de la machine, pas `localhost`.

`install.sh` est idempotent (une relance conserve les secrets; `--rotate` les régénère). Sans aucune
intervention humaine, il:

1. génère les secrets dans `packs/v01/.env` (mode 600, ignoré par git);
2. démarre Forgejo, crée le compte de service (`forgejo admin user create`) et son jeton d'API;
3. crée l'application OAuth de Woodpecker dans Forgejo (`/api/v1/user/applications/oauth2`) et remet son
   identifiant/secret à `woodpecker-server`;
4. démarre Woodpecker, puis **connecte le compte de service sans navigateur** (`hooks/wp_login.py`,
   exécuté dans un conteneur jetable sur le réseau privé: il joue le rôle du navigateur à travers les
   redirections OAuth et accepte l'écran de consentement) et obtient son jeton d'API Woodpecker. Le compte
   de service est l'administrateur de Woodpecker (`WOODPECKER_ADMIN`);
5. écrit `packs/v01/.env.pack` (`hooks/register-core.sh`).

Pour chaque dépôt, `WoodpeckerCI.activate` l'enregistre dans Woodpecker, qui crée lui-même le webhook dans
Forgejo, et applique des réglages sûrs (jamais « trusted », délai de 30 minutes).

Autres scripts: `register-core.sh` (réécrit `.env.pack`), `unlink.sh` (le supprime), `uninstall.sh [--purge]`
(arrête le pack; `--purge` supprime aussi données et secrets), `test-flow.sh` (voir plus bas).

## Comment le noyau l'utilise

Charger `packs/v01/.env.pack` dans les services `api` et `worker` (`env_file`) et les rattacher au réseau
partagé avec le pack (le pack déclare `cobble_core` comme externe). Il définit:

```
COBBLE_PACK_FORGEJO_URL=http://forgejo:3000
COBBLE_PACK_FORGEJO_TOKEN=...
COBBLE_PACK_FORGEJO_OWNER=cobble-bot
COBBLE_PACK_WOODPECKER_URL=http://woodpecker-server:8000/ci
COBBLE_PACK_WOODPECKER_TOKEN=...
```

Facultatif: `COBBLE_PACK_DEFAULT_BRANCH` (main), `COBBLE_PACK_MERGE_STYLE` (squash), `COBBLE_PACK_REQUIRED_CHECK`
(`ci/woodpecker/pr/*`), `COBBLE_PACK_CI_POLL_INTERVAL_S` (5). Dans le code:
`from cobble.providers import ForgejoGit, WoodpeckerCI, load_settings`, puis
`ForgejoGit(settings, ci=WoodpeckerCI(settings))`.

Interfaces web: importer `packs/v01/caddy/pack.caddy` dans le bloc de site du Caddy du noyau: `/git/*` va vers
Forgejo (préfixe retiré, `ROOT_URL=<url publique>/git/`) et `/ci/*` vers Woodpecker
(`WOODPECKER_HOST=<url publique>/ci`).

## « Vert ou pas de fusion », imposé deux fois

* `ForgejoGit.merge` lève `MergeRefused` sauf si le pipeline du commit de tête **actuel** de la demande de
  fusion est vert (vérifié via le fournisseur de CI; sans lui, via les statuts de commit de Forgejo).
* À la création d'un dépôt, la branche par défaut est protégée dans Forgejo: aucun push direct, statut requis
  `ci/woodpecker/pr/*`, règle valable aussi pour les administrateurs. Une fusion qui contourne notre code est
  refusée par le serveur.

Les dépôts sont créés à partir d'un dossier gabarit. `{{project_name}}` est remplacé par le nom du dépôt dans
tous les fichiers texte. Le gabarit `templates/fastapi-react` fournit un pipeline avec lint, tests backend et
frontend, Semgrep, Trivy et Gitleaks (images épinglées, échec sur les trouvailles de haute sévérité).

## Notes de sécurité

* `woodpecker-agent` est le **seul** conteneur qui monte le socket Docker (la règle 5 de CLAUDE.md l'autorise
  pour un service de pack). Qui contrôle un pipeline contrôle le Docker de l'hôte. Mesures: aucun port
  publié, aucune capacité, utilisateur non privilégié (accès au socket par le groupe Docker), dépôts jamais
  « trusted » (pas d'étape privilégiée ni de volume de l'hôte), limites mémoire/CPU des étapes
  (`PACK_STEP_MEM_BYTES`, `PACK_STEP_CPU_QUOTA`), seuls les dépôts créés par Cobble sont activés. Ne donnez pas
  d'accès en écriture à Forgejo à des personnes non fiables.
* Les identifiants git n'atteignent les pipelines que par l'étape de clonage de Woodpecker. Le jeton du compte
  de service n'est jamais donné aux pipelines. Les jetons sont dans des fichiers en mode 600; `ForgejoGit`
  passe les identifiants à `git` par l'environnement, jamais en ligne de commande ni dans `.git/config`.
* Le réseau privé `pack` est `internal`. Forgejo et les étapes de pipeline partagent le réseau `ci`, qui a
  accès à Internet (registres de paquets).

## Limites de la v0.1

* La connexion web à Woodpecker (OAuth dans le navigateur) n'est pas disponible: le serveur CI parle à Forgejo
  par le réseau privé. Les résultats se lisent par l'API; l'interface git est sur `/git/`.
* Si l'URL publique est une adresse IP, les conteneurs de pipeline doivent pouvoir l'atteindre (pare-feu de
  l'hôte); avec un nom d'hôte, `pack-gateway` répond à ce nom sur le réseau `ci`.
* Les scanners ont besoin du réseau (base Trivy, règles Semgrep, PyPI/npm). Sans Internet, définir
  `COBBLE_PACK_SKIP_STEPS=trivy,semgrep` à l'installation: réglage d'opérateur, pas de dépôt. Derrière un proxy
  qui inspecte TLS, définir `COBBLE_PACK_STEP_CA=/chemin/ca.pem`.
* SQLite pour les deux services. Le rebase d'une branche en retard n'est pas automatisé ici.

## Tests

* `make test-backend` exécute `test_pack_providers.py` (HTTP simulé) et `test_pack_invariants.py`.
* `packs/v01/hooks/test-flow.sh` démarre un pack jetable (projet propre, UN port sur `127.0.0.1:18081`),
  exécute `backend/tests/integration/test_pack_flow.py` (demande verte fusionnée, rouge refusée, fusion et push
  directs refusés par le serveur) puis supprime tout. Il faut le réseau du noyau et `uv`.
