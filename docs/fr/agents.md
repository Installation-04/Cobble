# Agents de code: runner, agent-service et proxy de sortie

Les agents écrivent le code des projets générés. Ils tournent dans des conteneurs isolés démarrés par
**agent-service**, un service du pack (`packs/v01/agent-service/`). Le noyau ne lui parle que par la
capacité `AgentRunner` (HTTP, [ADR 0006](../decisions/0006-agent-runner-and-scheduler.md)); il ignore
quel outil tourne dedans (v0.1: Aider).

```
 backend / worker ──HTTP+jeton──▶ agent-service ──socket Docker──▶ conteneur d'agent (image runner)
                                      │  clone / push (le jeton Forgejo reste ici)       │
                                      ▼                                                  │ HTTP(S)_PROXY
                                   Forgejo                                               ▼
                       API Cobble  ◀──── agent-proxy (liste blanche) ◀───── réseau cobble_agents (internal)
                 /internal/llm/v1                        └──▶ pypi.org, files.pythonhosted.org, registry.npmjs.org
```

| Pièce | Où | Rôle |
|---|---|---|
| Image runner | `runners/aider/` | Python 3.12, Aider 0.86.2 (verrouillé avec empreintes dans `uv.lock`), git, uv, Node 22 + pnpm 10.28 (corepack). Utilisateur uid 10001. |
| agent-service | `packs/v01/agent-service/` | Application FastAPI: crée le worktree, démarre et surveille le conteneur, pousse le résultat. |
| agent-proxy | `packs/v01/agent-proxy/` | tinyproxy (GPL-2.0 ou ultérieure, non modifié, conteneur séparé) en refus par défaut. |
| Compose | `packs/v01/compose.agents.yml` | projet `cobble-pack-agents`; aucun port publié. |

## Ce que fait une exécution

1. `POST /v1/runs`: agent-service valide la requête, répond `202 {run_id}` et continue en arrière-plan.
2. Il clone le dépôt dans un dépôt nu qu'il garde pour lui (`repo.git`) avec le jeton du compte de
   service Forgejo, puis crée le worktree `runs/<id>/work` (branche de tâche créée depuis la branche de
   base, ou reprise si elle existe déjà sur le serveur) et écrit `.cobble/instructions.md`.
3. Il démarre le conteneur runner avec le worktree monté sur `/work` et rien d'autre.
4. L'entrypoint du runner (`cobble-agent`) place le marqueur en tête des instructions et lance `aider`
   sans interface (`--yes-always --no-stream --edit-format whole --test-cmd ... --auto-test`, modèle
   `openai/<alias>`, point d'accès = l'API Cobble). Aider commite localement.
5. La sortie est écrite dans `runs/<id>/agent.log` (servie par `GET .../logs?offset=N`, prochain
   décalage dans `X-Next-Offset`). La détection de boucle lit le même flux.
6. À la fin du conteneur, agent-service **récupère** (fetch) la branche dans son propre dépôt, vérifie que
   l'historique n'a pas été réécrit, compte les commits et pousse lui-même la branche. L'état `done`
   exige le code de sortie 0 et au moins un commit; sinon `failed` (`reason`: `agent_failed`,
   `no_commits`, `history_rewritten`, `push_failed`, `max_iterations`...), ou `timeout`,
   `loop_detected`, `stopped`.
7. Le conteneur est supprimé. Le dossier de l'exécution (worktree, journal, métadonnées) est conservé
   `COBBLE_AGENT_RETENTION_HOURS` (24 h) puis supprimé.

Les itérations sont des exécutions de tests: le runner enveloppe la commande de test (`cobble-test`) et
écrit `[cobble:test-run N]`, `[cobble:test-fail <empreinte>]`, `[cobble:test-pass]`. Le code de sortie du
runner est le résultat de la dernière exécution locale des tests (0 seulement si les tests passent).
Aider réfléchit au plus 3 fois par message; `max_iterations` est un plafond strict appliqué par
agent-service (le conteneur est tué quand l'exécution de tests numéro `max_iterations + 1` démarre).

Détection de boucle (`COBBLE_LOOP_THRESHOLD`, 8 par défaut): la même ligne (codes ANSI, horodatages et
adresses retirés; nombres conservés) répétée autant de fois de suite, ou la même empreinte d'échec de
test sur deux exécutions consécutives, termine l'exécution avec `loop_detected`.

### API HTTP

Exactement l'ADR 0006 (`Authorization: Bearer <COBBLE_AGENT_SERVICE_TOKEN>`, comparaison en temps
constant; `/healthz` est ouvert). Les erreurs ont la forme `{"error": {"code", "params"}}`: `401
unauthorized`, `404 run_not_found`, `422 invalid_request`, `400 repo_url_not_allowed`, `429
too_many_runs`. Le corps d'état ajoute des champs facultatifs à `state`, `iterations`, `exit_code`,
`head_sha`, `log_tail`: `run_id`, `reason`, `commits`, `diff_stat`, `pushed`, `started_at`,
`finished_at`. Les limites supérieures aux plafonds du service sont abaissées, pas rejetées.

## Modèle de sécurité

**Le conteneur d'agent peut**: lire et écrire son worktree et `/tmp` (tmpfs, `COBBLE_AGENT_TMP_MB`),
lancer des processus dans ses limites de CPU, mémoire (swap désactivé), PID et durée, appeler le point
d'accès LLM interne de l'API Cobble avec son jeton d'exécution, et télécharger des paquets depuis les
registres autorisés.

**Il ne peut pas**: voir le socket Docker; tourner en root (uid 10001, `no-new-privileges`); garder une
capacité (`cap_drop ALL`); écrire dans le système de fichiers racine (lecture seule); voir les worktrees
des autres exécutions (il ne reçoit que le sous-chemin de la sienne); lire un identifiant git (le jeton
Forgejo n'existe que dans l'environnement d'agent-service et dans celui des processus `git clone`/`push`,
via `GIT_ASKPASS`; il n'est ni dans une URL, ni dans une configuration git, ni dans un fichier, ni dans
l'environnement du conteneur, et des tests le vérifient); pousser (aucun identifiant, aucune route vers
Forgejo); joindre LiteLLM, Redis, Postgres ou Internet; résoudre des noms autrement que par le proxy. Son
seul secret est le jeton d'exécution: valable le temps de l'exécution, lié à une tâche et un rôle, et
accepté seulement par le point d'accès LLM interne, qui applique le budget et enregistre le coût.

**agent-service** est le seul composant qui a le socket Docker (règle 5; le noyau n'y touche jamais).
Accéder au socket équivaut à être root sur l'hôte; il est donc gardé petit: uid 10001 (rejoint le groupe
du socket par `group_add: [DOCKER_GID]`), système de fichiers racine en lecture seule, aucune capacité,
aucun port publié, jeton sur chaque route, et il ne crée des conteneurs qu'à partir de son modèle fixe
(la requête ne peut choisir ni l'image, ni les montages, ni le réseau, ni l'utilisateur, ni les
capacités). Il refuse aussi de démarrer une exécution si le réseau des agents n'est pas `internal`.

**Le worktree n'est pas digne de confiance.** L'agent peut écrire `.git/config` et des hooks.
agent-service n'exécute donc jamais git dans un worktree: il récupère la branche du worktree dans son
propre dépôt nu propre (un fetch depuis un chemin n'exécute aucun code du dépôt) et inspecte et pousse
depuis là, toujours vers la branche de tâche, jamais en force.

**Les URL de clone** doivent commencer par `COBBLE_PACK_FORGEJO_URL` (après la réécriture facultative
`COBBLE_AGENT_GIT_REWRITE=préfixe-public=préfixe-interne`): un appelant ne peut pas faire envoyer le jeton
à un autre hôte.

### Liste blanche de sortie

Le réseau `cobble_agents` est `internal: true`: aucune route vers l'extérieur. Le seul conteneur
rattaché à lui et au réseau du noyau est `agent-proxy`; `HTTP(S)_PROXY` de l'agent y pointe. La liste par
défaut est `api,pypi.org,files.pythonhosted.org,registry.npmjs.org`; modifiable avec `AGENT_PROXY_ALLOW`
(noms d'hôtes séparés par des virgules, `*.exemple.org` permis; une entrée invalide interrompt le
démarrage; une liste vide refuse de démarrer). Le proxy filtre sur l'hôte de destination, refus par
défaut, et les tunnels CONNECT sont limités au port 443. `api` doit correspondre à l'hôte de
`COBBLE_INTERNAL_API_URL`.

### Limites connues (v0.1)

- Quiconque a le socket Docker possède l'hôte: agent-service est du code de confiance. gVisor/Sysbox sont
  des modules futurs (PLAN section 11).
- Le worktree n'a pas de quota disque (seul `/tmp` a une taille limite); le journal est plafonné à 50 Mio.
- Les conteneurs d'agents peuvent se joindre sur `cobble_agents` (jetons différents, aucun autre secret).
- Les requêtes HTTP en clair via le proxy sont filtrées par hôte, pas par port: ne pas mettre dans la
  liste un hôte qui expose d'autres services HTTP.
- Les fichiers écrits par l'agent, comme la définition de la CI, sont poussés tels quels; la demande de
  fusion et la CI font office de barrière (les pipelines ne sont jamais « de confiance »).
- Docker 26 ou plus récent requis (montages avec sous-chemin de volume, API 1.45).

## Installation

```
packs/v01/hooks/install.sh                 # d'abord Forgejo / Woodpecker (écrit .env.pack)
docker compose -f packs/v01/compose.agents.yml --profile build build   # proxy, service, runner
packs/v01/agent-service/gen-env.sh         # écrit .env.agents et .env.agents.core (mode 600)
docker compose -f packs/v01/compose.agents.yml up -d
```

Derrière un proxy qui inspecte TLS, ajouter un secret de build `ca` (les trois Dockerfile acceptent un
secret facultatif `ca`).

agent-service lit (générés par `gen-env.sh`, jamais en clair dans le dépôt): `COBBLE_AGENT_SERVICE_TOKEN`,
`COBBLE_INTERNAL_API_URL` (par défaut `http://api:8000/internal/llm/v1`), `COBBLE_PACK_FORGEJO_URL`,
`COBBLE_PACK_FORGEJO_TOKEN`, `COBBLE_PACK_FORGEJO_OWNER` (nom d'utilisateur git), et facultativement
`COBBLE_AGENT_GIT_REWRITE`. Fixés par compose: `COBBLE_AGENT_DATA_VOLUME` (ou
`COBBLE_AGENT_DATA_HOST_DIR`), `COBBLE_AGENT_NETWORK`, `COBBLE_AGENT_RUNNER_IMAGE`,
`COBBLE_AGENT_PROXY_URL`. Facultatifs: `COBBLE_LOOP_THRESHOLD`, `COBBLE_AGENT_MAX_RUNS` (8),
`COBBLE_AGENT_RETENTION_HOURS` (24), `COBBLE_AGENT_MAX_CPU` / `_MEMORY_MB` / `_PIDS` / `_SECONDS`
(plafonds). `COBBLE_AGENT_CMD` est un crochet de test: il remplace Aider dans le runner par une commande
shell; ne jamais le définir en production.

Le noyau lit `.env.agents.core` (`COBBLE_AGENT_SERVICE_URL=http://agent-service:8090`,
`COBBLE_AGENT_SERVICE_TOKEN`). Après un redémarrage, agent-service reprend la surveillance des
conteneurs en cours (retrouvés par étiquette), termine ceux qui ont fini, marque `failed`
(`container_lost`) ceux dont le conteneur a disparu et supprime les conteneurs étiquetés qu'il ne
connaît pas.

## Dépendances

agent-service utilise `fastapi`, `uvicorn`, `httpx` (déjà dans le backend; BSD/MIT) et parle à l'API
Docker Engine par le socket unix avec httpx, au lieu d'ajouter le SDK Docker. Le runner ajoute Aider
(Apache-2.0) et ses dépendances verrouillées; tinyproxy est GPL-2.0 ou ultérieure et ne tourne que
comme programme séparé.

## Tests

```
cd packs/v01/agent-service
uv sync && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy
cd backend && uv run pytest tests/unit/test_agent_invariants.py   # vérifications statiques des images et de compose
```

Les tests unitaires utilisent un faux moteur Docker et de vrais dépôts git dans un dossier temporaire:
cycle de vie, authentification, validation, détection de boucle, délai, arrêt, reprise après
redémarrage, fuite de secrets, configuration `.git` hostile. Les tests d'agents n'appellent jamais un
vrai modèle; pour des essais de bout en bout, utiliser le faux LLM avec une cassette marqueur
(`providers/fake-llm/README.md`).
