# Banc d'essai des agents: l'exécuter et publier les résultats

Le banc mesure, sur cinq projets de référence figés, la fréquence à laquelle les agents livrent une application qui réussit des tests d'acceptation cachés, et ce que cela coûte ([ADR 0020](../decisions/0020-reference-benchmark.md), en anglais). C'est le critère d'acceptation de la v0.3.

| Projet | Ce qu'il mesure |
|---|---|
| `todo` | la boucle complète sur une application minuscule |
| `blog` | slugs, brouillons, filtre par étiquette, suppression en cascade |
| `invoicing` | argent exact (Decimal), arrondi, numérotation, machine à états |
| `dashboard` | agrégation, fuseaux horaires, plages de dates semi-ouvertes |
| `bot` | textes de réponse exacts, priorités des règles, analyseur d'expressions sans `eval` |

## Sans rien dépenser

```bash
make bench-check     # tests cachés contre les solutions de référence et leurs mutations (aucun modèle)
make bench-dry-run   # tout l'exécuteur contre un simulateur en mémoire; les rapports commencent par dry-
```

Le simulateur invente ses chiffres: ne publiez jamais un rapport `dry-`.

## L'exécution réelle (dépense de l'argent)

Il faut une instance qui tourne (`make dev` ne suffit pas: son modèle est le faux), avec une vraie connexion à un modèle dans les Paramètres, un compte administrateur et un accès en lecture aux dépôts générés.

```bash
export COBBLE_BENCH_URL=http://localhost:8080
export COBBLE_BENCH_EMAIL=admin@example.com COBBLE_BENCH_PASSWORD=...
export COBBLE_BENCH_GIT_URL='http://<serveur git>/<propriétaire>/{repo}.git'   # {repo} est remplacé
export COBBLE_BENCH_GIT_TOKEN=...
make bench ARGS="--yes-real-models --preset balanced --slot cheap=<modèle> --slot strong=<modèle> --total-budget 8 --label v0.3"
```

Sans `--yes-real-models` (ou `COBBLE_BENCH_REAL_MODELS=yes`), sans identifiants, sans source du code, ou si un rôle utilise encore le modèle `fake`, la commande explique pourquoi, en français et en anglais, et se termine avec le statut 2 avant de rien créer. Autres options: `--projects todo,bot`, `--cap USD` (plafond par projet, 1 à 2 USD chacun par défaut), `--total-budget USD` (8 par défaut), `--timeout-scale`, `--lang fr|en`, `--code-dir DIR` (code déjà sur disque sous `DIR/<projet>/`), `--python` (interpréteur des tests cachés; par défaut `uv run --project {code} python`, c'est-à-dire le fichier de verrouillage du projet généré). Ne jamais l'exécuter en CI.

Chaque projet reçoit un plafond de budget sur la plateforme (le routeur de coûts le met en pause à 100 %); l'exécuteur cesse d'attendre si la dépense dépasse le plafond et l'enregistre. Le statut de sortie est 1 si un projet ou le total a fini au-dessus de son budget.

## Résultats

`reference-projects/results/<id>/` reçoit `report.json`, `report.fr.md` et `report.en.md` (ignorés par le contrôle de version). Chiffres: taux de réussite (projet `done` et tous les tests cachés réussis), coût moyen par projet et par projet réussi, jetons, durée, tâches escaladées, appels de repli, et « aucun projet n'a dépassé son budget ».

Pour publier: reportez les chiffres dans `reference-projects/results/SUMMARY.template.fr.md` / `.en.md` (les deux langues), joignez les rapports Markdown et indiquez les modèles et le préréglage. Ne publiez que des exécutions réelles.

## Ajouter ou modifier un projet

Une spécification publiée reste figée. Modifier une spécification ou les tests cachés change ce qui est mesuré: notez-le dans le journal des changements et ne comparez pas les exécutions de part et d'autre. Après une modification, lancez `make bench-check`.

Les tests cachés doivent rester hors d'atteinte des agents: ils ne vivent que sous `reference-projects/`, qu'aucun module, gabarit ou exécuteur ne monte.
