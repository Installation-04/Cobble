# Reference project: Personal blog

Part of the agent bench (PLAN.md section 15, [docs](../../docs/en/bench.md)).

- What it measures: Fine print followed to the letter: slug generation (accents, duplicates), drafts versus published posts, tag filter, delete cascade.
- `spec.md` / `spec.fr.md`: the frozen specification (English / French), sent to the planner as the interview.
- `hidden/`: the hidden acceptance tests. The bench runner runs them on the generated code AFTER the build, from a temporary directory outside the generated repository. They are never copied into a project and no agent mount reaches `reference-projects/`.
- `solution/tree/`: a reference solution laid over `templates/fastapi-react`, proving the tests are satisfiable. Not visible to agents.
- `mutations.json`: 11 deliberate breakages of the solution; `make bench-check` verifies that each one fails a hidden test.
- Budget cap: $1.50, time limit 4500 s (see `project.json`).

## Résumé (français)

Règles de détail à respecter à la lettre: génération de slugs (accents, doublons), brouillons contre articles publiés, filtre par étiquette, cascade de suppression. Les tests d'acceptation sont cachés (`hidden/`) et exécutés après la construction, hors du dépôt généré; `solution/tree/` prouve qu'ils sont satisfiables et `mutations.json` (11 cas) qu'ils discriminent (`make bench-check`). Plafond de budget: 1.50 $.
