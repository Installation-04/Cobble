# Reference project: Invoicing API

Part of the agent bench (PLAN.md section 15, [docs](../../docs/en/bench.md)).

- What it measures: Correctness: money in Decimal, rounding, numbering, state machine and immutability rules. Models that compute in floating point fail.
- `spec.md` / `spec.fr.md`: the frozen specification (English / French), sent to the planner as the interview.
- `hidden/`: the hidden acceptance tests. The bench runner runs them on the generated code AFTER the build, from a temporary directory outside the generated repository. They are never copied into a project and no agent mount reaches `reference-projects/`.
- `solution/tree/`: a reference solution laid over `templates/fastapi-react`, proving the tests are satisfiable. Not visible to agents.
- `mutations.json`: 14 deliberate breakages of the solution; `make bench-check` verifies that each one fails a hidden test.
- Budget cap: $2.00, time limit 5400 s (see `project.json`).

## Résumé (français)

Exactitude: argent en Decimal, arrondi, numérotation, machine à états et règles d'immuabilité. Les modèles qui calculent en virgule flottante échouent. Les tests d'acceptation sont cachés (`hidden/`) et exécutés après la construction, hors du dépôt généré; `solution/tree/` prouve qu'ils sont satisfiables et `mutations.json` (14 cas) qu'ils discriminent (`make bench-check`). Plafond de budget: 2.00 $.
