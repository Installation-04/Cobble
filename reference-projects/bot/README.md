# Reference project: Simple chat bot

Part of the agent bench (PLAN.md section 15, [docs](../../docs/en/bench.md)).

- What it measures: Exact text and priorities: commands, keyword rules (whole word, first wins), an expression parser without eval, reply formats to the letter.
- `spec.md` / `spec.fr.md`: the frozen specification (English / French), sent to the planner as the interview.
- `hidden/`: the hidden acceptance tests. The bench runner runs them on the generated code AFTER the build, from a temporary directory outside the generated repository. They are never copied into a project and no agent mount reaches `reference-projects/`.
- `solution/tree/`: a reference solution laid over `templates/fastapi-react`, proving the tests are satisfiable. Not visible to agents.
- `mutations.json`: 17 deliberate breakages of the solution; `make bench-check` verifies that each one fails a hidden test.
- Budget cap: $1.50, time limit 4500 s (see `project.json`).

## Résumé (français)

Texte exact et priorités: commandes, règles de mots-clés (mot entier, premier gagnant), analyseur d'expressions sans eval, formats de réponse à la lettre. Les tests d'acceptation sont cachés (`hidden/`) et exécutés après la construction, hors du dépôt généré; `solution/tree/` prouve qu'ils sont satisfiables et `mutations.json` (17 cas) qu'ils discriminent (`make bench-check`). Plafond de budget: 1.50 $.
