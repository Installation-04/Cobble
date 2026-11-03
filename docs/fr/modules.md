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

Les packs de départ (`catalog/packs/`) les regroupent: `local-gpu`, `local-cpu` et `api-only`.

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
