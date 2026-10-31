# Essai de bout en bout de la chaîne complète (`make e2e-full`)

`make e2e` pilote le navigateur sur des simulacres en mémoire. Ce harnais manuel exécute la **vraie
chaîne** sur le projet de référence « liste de tâches », sans modèle ni clé d'API: Forgejo,
Woodpecker, agent-service avec le runner Aider et preview-service, le faux LLM rejouant des cassettes.

```bash
make e2e-full                        # scripts/e2e_full.sh; ajouter ARGS, ex. --keep --comment
scripts/e2e_full.sh --keep --timeout 5400 --lang fr
```

Options: `--keep` (laisse la pile active), `--timeout SECONDES` (durée de construction, 3600 par défaut),
`--lang en|fr`, `--comment` (après `done`, commente la dernière démo et suit la tâche `C-001`), `--force`
(remplace les secrets du pack déjà présents dans `packs/v01`). `E2E_PORT` fixe le port hôte (18080).

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
