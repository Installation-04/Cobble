# Démos de jalon

À la fin de chaque jalon du plan, Cobble construit une démo de l'application; vous l'essayez, puis
vous la validez, vous la commentez ou vous revenez en arrière. Cette page décrit le déroulement, les
composants et la sécurité des aperçus. Le contrat est l'ADR 0007 (`docs/decisions/0007-demo-agents-costs.md`).

## Déroulement

1. Chaque jalon reçoit une tâche synthétique `DEMO-M1`, `DEMO-M2`... Elle dépend de toutes les tâches de
   son jalon et réécrit `app/seed.py` pour que la démo s'ouvre sur des données réalistes (noms, dates et
   quantités plausibles; jamais d'écran vide). Pas d'étape de rédaction de tests pour elle; toute la suite
   de tests existante doit rester verte.
2. Quand la tâche `DEMO-Mx` est fusionnée, le jalon est **construit** (`built`): Cobble pose une étiquette
   sur la branche par défaut (`milestone-M1`; les constructions suivantes du même jalon sont
   `milestone-M1-r2`, `-r3`...), demande au service d'aperçu de déployer cette étiquette et enregistre
   l'adresse de la démo `/demo/<projet>/<jalon>/`. L'événement `milestone.updated {ref, status,
   preview_state}` prévient l'interface.
3. Vous **validez** le jalon (`POST .../milestones/M1/validate`). Quand tous les jalons sont validés, le
   projet est **terminé** (`done`); jusque-là il reste en construction (`building`).
4. Vous pouvez **commenter** (`POST .../comments`, 1 à 2000 caractères). Le commentaire devient une tâche
   `C-001`, `C-002`... du jalon, écrite tests d'abord comme toute tâche. Le jalon repasse en attente
   (`pending`) et un projet `done` repasse en `building`. Une fois le commentaire fusionné, le jalon est
   reconstruit (nouvelle étiquette, nouvelle démo).
5. Vous pouvez **revenir en arrière** (`POST .../revert`, réponse `202`, exécuté par le worker). Cobble
   restaure l'étiquette du jalon précédent (le premier commit du gabarit pour `M1`) par une demande de
   fusion comme les autres, donc la CI et les protections s'appliquent toujours. Le jalon et les suivants
   repassent en attente et leurs tâches sont remises à `todo`; elles attendent la fusion de la
   restauration (`R-001`...).

Les erreurs sont des codes seulement: `404 not_found`, `409 wrong_state` (valider exige `built`; commenter
et revenir exigent `built` ou `validated`; revenir sur `M2` exige aussi `M1` construit ou validé),
`422 validation_error`, `503 queue_unavailable`.

Sans service d'aperçu (pas de `COBBLE_PREVIEW_SERVICE_TOKEN`) le déroulement des démos est désactivé et le
projet est `done` dès que toutes les tâches sont fusionnées, comme avant.

## Composants

| Composant | Rôle |
|---|---|
| `scheduler/demo.py` | règles des jalons: valider, commenter, revenir, fin du projet |
| `capabilities/preview.py` | `PreviewProvider` (`deploy`, `status`, `remove`) |
| `providers/preview_service.py` | client HTTP du service d'aperçu |
| `services/preview-service/` | construit l'étiquette, la lance, relaie `/demo/...`, arrête les démos inactives |
| `catalog/preview/` | le module: le service, son réseau interne `cobble-preview-previews`, sa route `/demo` |
| `templates/fastapi-react/Dockerfile` | image de l'application générée |

### Installation et réglages

```
cobble modules install preview      # le serveur Git dont il a besoin est ajouté avec lui
```

Le module prend l'adresse et le jeton du serveur Git auprès du module qui fournit `git`, génère son
jeton de service et publie lui-même `/demo/*` sur le proxy inverse (la route du module, avant celle de
l'API): rien à copier ni à configurer. Le noyau le trouve par le gestionnaire de modules. Sans le
module, `/demo/*` va à l'API, qui ne répond que dans le mode pack factice, et le projet est `done`
dès que toutes les tâches sont fusionnées.

Réglages du service (environnement du fichier compose du module): `COBBLE_PREVIEW_SERVICE_TOKEN`,
`COBBLE_PACK_FORGEJO_URL|TOKEN|OWNER`, `COBBLE_PREVIEW_NETWORK` (la plateforme le nomme
`cobble-preview-previews`), `COBBLE_PREVIEW_MEMORY_MB` (512), `COBBLE_PREVIEW_CPUS` (1),
`COBBLE_PREVIEW_PIDS` (256), `COBBLE_PREVIEW_IDLE_TTL_S` (1800), `COBBLE_PREVIEW_MAX_RUNNING` (6),
`COBBLE_PREVIEW_BUILD_ARGS` (objet JSON d'arguments de build Docker, par exemple un proxy),
`COBBLE_PREVIEW_SANDBOX` (1). Désinstaller le module supprime les conteneurs et images de démo.

## Sécurité des aperçus

- La démo est du code écrit par un agent. Elle tourne dans son propre conteneur: utilisateur non-root (10001,
  quel que soit le Dockerfile), système de fichiers racine en lecture seule (tmpfs de 64 Mo sur `/tmp`), toutes
  les capacités retirées, `no-new-privileges`, limites mémoire, CPU et PID, aucun port publié, pas de socket
  Docker, aucun secret dans l'environnement. Elle vit sur le réseau `cobble_previews`, qui est `internal`: pas
  de route vers Internet, l'hôte ou le reste de Cobble. Seul le service d'aperçu l'atteint.
- Le service d'aperçu est le second composant (avec agent-service) à détenir le socket Docker. Il n'exécute
  jamais le code généré lui-même; `docker build` exécute le Dockerfile généré dans le démon, avec accès
  réseau pour les gestionnaires de paquets. Considérez le Dockerfile d'un dépôt comme du code validé par la CI,
  pas comme digne de confiance.
- Le jeton du dépôt n'atteint `git` que par `GIT_ASKPASS`; `.git` ne fait jamais partie du contexte de build;
  les identifiants n'apparaissent dans aucune erreur renvoyée au noyau.
- `/demo/...` est public (pas de connexion Cobble): l'identifiant du projet dans l'adresse est le secret. Les
  cookies et l'en-tête `Authorization` ne sont jamais transmis à la démo et son `Set-Cookie` est supprimé.
- La démo est servie depuis le même hôte que Cobble; par défaut chaque réponse porte donc
  `Content-Security-Policy: sandbox allow-scripts allow-forms ...` (sans `allow-same-origin`): la page a une
  origine opaque et ne peut ni lire les cookies de Cobble ni appeler son API à votre place. Le relais répond
  lui-même au CORS pour que la démo puisse appeler sa propre API. Contrepartie: `localStorage` et les cookies
  sont indisponibles pour la démo. `COBBLE_PREVIEW_SANDBOX=0` supprime cette protection (instance mono-utilisateur
  de confiance seulement).
- Les démos inactives s'arrêtent après `COBBLE_PREVIEW_IDLE_TTL_S` secondes (l'image est conservée) et se
  réveillent à la requête suivante; au plus `COBBLE_PREVIEW_MAX_RUNNING` tournent en même temps (la moins
  récemment utilisée s'arrête).

Limites de la v0.1: l'étiquette est posée sur la tête de la branche par défaut quand la tâche `DEMO` a été
fusionnée puis remarquée (la fusion d'un jalon suivant entre-temps serait incluse); un redéploiement dont la
construction échoue remplace la démo qui marchait par une page d'erreur; une seule construction à la fois.

## Mode pack factice (développement et tests seulement)

`COBBLE_PACK_MODE=fake` remplace git, la CI, le lanceur d'agents et le service d'aperçu par des faux en mémoire:
un projet démarré joue toute la boucle en quelques secondes sans Docker, serveur git ni modèle, et l'API sert
elle-même une petite page de démo (liste de tâches) à `/demo/<projet>/<jalon>/` (vos commentaires y
apparaissent). Réglages: `COBBLE_FAKE_STEP_S` (0,3, durée d'une étape d'agent simulée) et
`COBBLE_SCHEDULER_INTERVAL_S` (0,5 en mode factice sauf réglage explicite). Les faux ne gardent aucun état: les
conteneurs `api` et `worker` s'accordent donc sur les journaux et les différences. `GET /api/v1/health` indique
`pack_mode`.

**Ne l'utilisez jamais pour de vrais projets**: rien n'est construit, testé ni relu. L'application refuse de
démarrer avec `COBBLE_ENV=production` et le worker écrit un avertissement au démarrage.
