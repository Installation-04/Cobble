# ADR 0014 — End-of-project report

Status: **proposed** (implemented in v0.3, waiting for the owner to accept it).

## Context
PLAN.md §17 ("Compteur d'économies"): the savings counter is shown in the Costs tab and in the
end-of-project report. The report did not exist.

## Decision
- `GET /projects/{id}/report` (`cobble/report.py`, route in `routes_costs.py`) builds the report
  on demand; nothing is stored and there is no schema change. It reuses `costs.project_costs`
  (spend, tokens, estimate, savings, per model/role, fallbacks, with the same reference model
  logic) and adds two grouped queries over `tasks` and `milestones` (done/failed/escalated, per
  milestone). The number of queries does not depend on the number of tasks or calls (tested).
- Time span: start is the project's creation; end is the last activity (latest task update or
  milestone validation). It is not a "finished at" date, because no such column exists; the
  report says whether the project is finished (`phase == done`) and works at any time.
- `?format=md` renders the same body as Markdown, localised with the backend locale files
  (`locales/{fr,en}/report.json`) in the language of the authenticated user. Served as an
  attachment. Table cells escape `|`.
- UI: a "Report" tab in the project page with a plain same-origin download link (the session
  cookie authenticates it). The savings card is the one of the Costs tab.
- Money is displayed as sent by the API (strings, USD); a loss against the reference model is
  written as "no saving", never hidden, as in the Costs tab.

## Consequences
- No PDF and no sharing/publishing of the report: out of scope for v0.3.
- `ended_at` can move after the project is finished (a later comment task); acceptable.
