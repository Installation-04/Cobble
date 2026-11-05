# Reference project: Metrics dashboard

Part of the agent bench (PLAN.md section 15, [docs](../../docs/en/bench.md)).

- What it measures: Aggregation and dates: time zones, half-open ranges, grouping by hour and by day, rounding, empty cases.
- `spec.md` / `spec.fr.md`: the frozen specification (English / French), sent to the planner as the interview.
- `hidden/`: the hidden acceptance tests. The bench runner runs them on the generated code AFTER the build, from a temporary directory outside the generated repository. They are never copied into a project and no agent mount reaches `reference-projects/`.
- `solution/tree/`: a reference solution laid over `templates/fastapi-react`, proving the tests are satisfiable. Not visible to agents.
- `mutations.json`: 15 deliberate breakages of the solution; `make bench-check` verifies that each one fails a hidden test.
- Budget cap: $2.00, time limit 5400 s (see `project.json`).

## Résumé (français)

Agrégation et dates: fuseaux horaires, intervalles semi-ouverts, regroupement par heure et par jour, arrondis, cas vides. Les tests d'acceptation sont cachés (`hidden/`) et exécutés après la construction, hors du dépôt généré; `solution/tree/` prouve qu'ils sont satisfiables et `mutations.json` (15 cas) qu'ils discriminent (`make bench-check`). Plafond de budget: 2.00 $.
