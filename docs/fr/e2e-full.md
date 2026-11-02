# Essai de bout en bout de la chaîne complète (`make e2e-full`)

`make e2e` pilote le navigateur sur des simulacres en mémoire. Ce harnais manuel exécute la **vraie
chaîne** sur le projet de référence « liste de tâches », sans modèle ni clé d'API: Forgejo,
Woodpecker, agent-service avec le runner Aider et preview-service, le faux LLM rejouant des cassettes.

```bash
make e2e-full                        # scripts/e2e_full.sh; ajouter ARGS, ex. --keep --comment
scripts/e2e_full.sh --keep --timeout 5400 --lang fr
```

Options: `--keep` (laisse la pile active), `--timeout SECONDES` (durée de construction, 3600 par défaut),
`--lang en|fr`, `--comment` (après `done`, commente la dernière démo et suit la tâche `C-001`). `E2E_PORT` fixe le port hôte (18080). `E2E_HOST` est l'adresse que les conteneurs de CI utilisent
pour joindre la pile (par défaut: la première adresse de cette machine; `localhost` ne marcherait pas
depuis un conteneur). `E2E_BUILD_CA` est un paquet de CA pour les machines derrière un proxy qui
inspecte TLS: il est passé aux constructions d'images du noyau et monté dans les conteneurs d'étapes de CI
(non défini par défaut). Les images d'agents et d'aperçus sont téléchargées depuis `ghcr.io` (publiées par
le workflow « Module images », épinglées dans `catalog/`): les paquets doivent être publics, ou
`docker login ghcr.io` fait au préalable.

## Déroulement

1. Génère des secrets dans un dossier temporaire, démarre le noyau (projet compose `cobble`), installe le
   pack, construit et démarre agent-service et preview-service. Refuse de tourner à côté d'une pile de
   dev nommée `cobble` et démonte avec `down -v` (tout est effacé) sauf avec `--keep`.
2. Active l'administrateur par l'API, crée le projet « Todo list ».
3. Rejoue l'entrevue scriptée (`USER_MESSAGES` dans `providers/fake-llm/scripts/make_todo_cassettes.py`),
   génère et approuve la spécification et le plan.
4. `POST /projects/{id}/start`, puis interroge `GET /projects/{id}/tasks` et la `phase` du projet. Valide
   chaque démo de jalon dès qu'elle est `built` (la phase n'atteint `done` que lorsque tous les jalons sont
   validés) et s'arrête tôt si une tâche échoue ou est bloquée.
5. Affiche le tableau final des tâches, les jetons et le coût (`GET /projects/{id}/costs`, sinon la table
   `llm_calls` via `psql`) et la durée. Code de sortie 0 seulement si la phase est `done`.

Les points d'entrée qui répondent 404 (pas encore livrés) sont signalés `SKIPPED` sans faire échouer l'essai.

## Les cassettes d'agents

Les agents sont rejoués par des cassettes à marqueur `providers/fake-llm/cassettes/agent-todo-<ref>-<rôle>-<tentative>.json`,
générées depuis la solution de référence `reference-projects/todo/solution/` (un dossier par tâche du plan,
contenu exact des fichiers, tests d'abord):

```bash
python3 scripts/make_agent_cassettes.py            # réécrit cassettes et solution/tree
python3 scripts/make_agent_cassettes.py --check    # échoue si périmé
python3 scripts/make_agent_cassettes.py --table    # tâches, fichiers, dépendances
python3 scripts/verify_solution.py --orders 2      # rejoue les tâches contre la CI du gabarit
```

Après un changement du plan dans `make_todo_cassettes.py` ou d'un fichier de la solution, relancer la
première commande (et le générateur todo). Les tâches qui partagent un fichier doivent être ordonnées par
`depends_on`: le script échoue sinon. `C-001` (« afficher une échéance ») répond au premier commentaire;
`X-LOOP` est une tâche fictive dont la réponse du worker est volontairement fausse, pour tester la
détection de boucle (`loop_detected`).

## Résultat vérifié

Exécuté sur un bac à sable de développement avec le faux LLM (cela prouve la **plomberie**, pas la
qualité d'un modèle ni le coût réel): 2026-10-31, `PASS` en 12 min 39 s. Les 11 tâches du plan et les
3 tâches de démo sont passées à `merged` dès la première tentative, chacune via la CI Woodpecker
(lint, tests, gitleaks, semgrep, trivy) et une fusion « squash » Forgejo; les 3 démos de jalon ont
été construites et validées; la phase a atteint `done`. Mesuré par le routeur de coûts: 59 251 jetons
d'entrée et 13 754 de sortie, 0,087 $ (le plan estimait 420 000 jetons, 0,84 $, pour un vrai modèle).


Un second essai avec `--comment` a aussi réussi (13 min 43 s, 75 385 jetons d'entrée et 20 518 de
sortie, 0,116 $): le commentaire sur la dernière démo a créé `C-001`, qui a passé tests, CI et fusion
à la première tentative, puis la démo du jalon a été validée de nouveau.

Les premiers essais ont trouvé et fait corriger sept défauts, invisibles aux tests unitaires et
navigateur: les scripts `gen-env.sh` (remplacés depuis par les modules) qui échouaient au premier lancement, `git` absent de l'image du
backend, l'accès aux registres des agents (l'image du runner embarque désormais un cache uv et un
magasin pnpm préchauffés), l'environnement uv d'Aider qui fuyait dans les tests du projet, les tests
frontend lancés avant `pnpm install`, une fusion refusée un instant par Forgejo juste après une autre
fusion, et un magasin pnpm resté vide sans erreur.

Un essai ultérieur a révélé un huitième défaut: Forgejo peut signaler une demande de fusion comme
non fusionnable pendant quelques secondes après qu'une autre fusion a déplacé la branche de base;
l'étape de fusion laisse donc l'indicateur se stabiliser (trois lectures) avant de parler de conflit.

Non couvert: un vrai modèle, l'installation sur VM vierge (étape 11), HTTPS.
