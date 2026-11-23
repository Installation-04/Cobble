# Les modules officiels

Le noyau de Cobble ne nomme jamais un produit: il parle aux capacités `GitProvider`, `CIProvider`,
`AgentRunner`, `PreviewProvider` et `LLMClient`. Les modules officiels de `catalog/` les
implémentent; le gestionnaire de modules les installe, les relie et les retire
([ADR 0008](../decisions/0008-module-manager.md)). Installation depuis l'onglet Magasin, ou
`cobble modules install <id>` / `cobble modules install --pack <id>`.

| Module | Fournit | Demande | Ce qu'il fait tourner |
|---|---|---|---|
| `forgejo` | `git` | | Forgejo, le serveur Git (SQLite, HTTP seulement, dépôts privés), sous `/git` |
| `woodpecker` | `ci` | `git` | Serveur et agent Woodpecker (SQLite), sous `/ci`; connecté à Forgejo par OAuth |
| `ollama` | `llm-backend` | | Ollama, en variante CPU, NVIDIA ou AMD choisie selon la machine; ses modèles sont ajoutés à la passerelle |
| `aider` | `agent-runner` | `git` | agent-service, le proxy de sortie et l'image du runner Aider: [agents](agents.md) |
| `preview` | `preview` | `git` | preview-service, qui construit et sert les démos de jalon sous `/demo`: [démos](demo.md) |

| `verdaccio` | `package-cache`, `npm-cache` | | Verdaccio, un cache du registre npm; aucune page web, personne ne peut publier |
| `devpi` | `package-cache`, `pypi-cache` | | devpi, un miroir de PyPI; joignable seulement sur le réseau de la plateforme |

Les packs de départ (`catalog/packs/`) les regroupent: `local-gpu`, `local-cpu` et `api-only`. Les
deux caches de paquets ne sont dans aucun pack: ils sont facultatifs, à installer depuis le Magasin.

## Cache local des paquets (facultatif)

`verdaccio` et `devpi` gardent une copie de chaque paquet qu'ils ont servi: l'installation suivante est
rapide, fonctionne encore hors ligne pour ce qui a déjà été téléchargé, et consomme moins de bande
passante. Ils ne tournent que sur le réseau de la plateforme (`web_ui.public: false`, aucun port sur
l'hôte, aucune route sur le proxy inverse), gardent leurs données dans un volume (inclus dans les
sauvegardes) et sont limités à 512 Mo / 1 CPU (Verdaccio) et 768 Mo / 1 CPU (devpi). Les autres
modules les joignent à `http://cobble-verdaccio-verdaccio:4873` et `http://cobble-devpi-devpi:3141`
(l'index Python est `/root/pypi/+simple/`). Chacun fournit la capacité commune `package-cache` et
une capacité propre à son écosystème (`npm-cache`, `pypi-cache`): un consommateur doit demander la
capacité précise, car un module relié à une capacité ne voit qu'un seul fournisseur.

**Branchés aux agents automatiquement, jamais obligatoires** ([ADR 0027](../decisions/0027-package-cache-wiring.md)).
Le manifeste de `aider` dit `wants: [npm-cache, pypi-cache]`: une dépendance facultative, « à
utiliser si elle est installée ». Elle n'installe rien et ne bloque rien; quel que soit l'ordre (cache
d'abord, agents d'abord, ou les deux en une fois) et aussi quand un cache est retiré plus tard, le
gestionnaire de modules donne l'adresse du cache aux agents et ne redémarre que les services des
agents dont la configuration a changé. Au rendu du fichier compose des agents, celui-ci reçoit
`COBBLE_WANT_NPM_CACHE_URL`, `COBBLE_WANT_PYPI_CACHE_URL` (et `..._HOST`, `..._PORT`, `..._MODULE`),
qu'il transforme en:

- liste d'autorisation du proxy des agents: exactement les noms d'hôte des caches sont ajoutés, rien
  d'autre ne s'élargit; le réseau des agents reste interne et chaque requête passe toujours par le proxy;
- `npm_config_registry`, `PIP_INDEX_URL` + `PIP_TRUSTED_HOST` et `UV_DEFAULT_INDEX` dans chaque
  conteneur d'agent (`COBBLE_NPM_REGISTRY` / `COBBLE_PYPI_INDEX` portent les mêmes adresses), pour que
  `npm`, `pnpm`, `pip` et `uv` installent via le cache.

En cas d'absence dans le cache, c'est le cache lui-même qui récupère le paquet sur le registre
public (son amont) et le garde. **Si un cache est arrêté, les installations échouent** avec l'erreur
réseau de l'outil (connexion refusée ou 502 du proxy): les agents ne se rabattent pas sur le
registre public et le réseau restreint n'est jamais contourné. Relancez le cache (`cobble modules
status`) ou désinstallez-le: les agents sont rebranchés sur les registres publics en quelques
secondes. Brancher ou débrancher redémarre `agent-service` et le proxy: faites-le quand aucun agent
ne travaille. Un fichier de verrouillage qui note des URL de téléchargement absolues (par exemple
`uv.lock`) pointe toujours vers le registre public, qui reste autorisé: cela fonctionne mais le
cache n'est pas utilisé pour ces fichiers.

Les modules peuvent utiliser le même mécanisme: `wants: [<capacité>]` dans le manifeste (validé par
`cobble-sdk lint`), l'`endpoint` d'un fournisseur pour le chemin sous son adresse, et les variables
`COBBLE_WANT_<CAPACITÉ>_*` dans le fichier compose (à lire avec une valeur par défaut vide,
`${COBBLE_WANT_X_URL:-}`, car elles sont absentes quand personne ne fournit la capacité).

## Ce que suit chaque module

- **Images épinglées par empreinte**, jamais `:latest`. Les images de `aider` et `preview` sont
  construites depuis ce dépôt par le workflow « Module images » (`.github/workflows/images.yml`),
  publiées vers `ghcr.io/<propriétaire>/cobble-*` et épinglées avec `scripts/pin_images.py`. Les paquets
  GHCR doivent être publics pour une installation sans connexion au registre.
- **Aucun port publié sur l'hôte**: le gestionnaire de modules les retire; le proxy inverse n'expose une
  adresse web que pour les modules qui en déclarent une (`web_ui`, publique sauf `public: false`).
- **Noms, réseaux et limites sont ceux de la plateforme**: tout est renommé `cobble-<id>-…`, seuls les
  services déclarés rejoignent le réseau partagé, des limites CPU/mémoire/processus par défaut
  s'appliquent.
- **Secrets**: générés ou produits par des crochets, stockés chiffrés; le noyau ne lit que les
  `core_secrets` d'un module, un module qui demande une capacité ne lit que les `link_secrets` du
  fournisseur.
- **Le socket Docker** est monté par exactement trois modules, qui déclarent chacun `host_access:
  [docker_socket]`: `woodpecker` (son agent démarre les conteneurs de pipeline), `aider` (démarre les
  conteneurs d'agents) et `preview` (construit et démarre les conteneurs de démo). Chacun tourne sous un
  utilisateur sans privilège qui rejoint le groupe du socket; aucun n'exécute le code qu'il démarre.

## En écrire un

`cobble-sdk init`, `lint` et `test` (voir `sdk/README.md`) créent, vérifient et essaient un module.

## Si vous veniez du pack v0.1

Le pack v0.1 (`packs/v01`, installé à la main) a disparu. Si vous l'aviez installé, retirez ses
conteneurs et volumes (projets compose `cobble-pack`, `cobble-pack-agents`, `cobble-pack-preview`) puis
installez les modules: les dépôts et l'historique de CI de l'ancien Forgejo et Woodpecker ne sont pas
migrés.
