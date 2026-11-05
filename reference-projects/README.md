# Reference projects

Five frozen specifications with hidden acceptance tests for the agent bench (`make bench`). See `docs/en/bench.md` and `docs/fr/bench.md`.

| Project | Measures |
|---|---|
| `todo` | the whole loop on a tiny app (floor) |
| `blog` | fine print: slugs, drafts, tag filter, delete cascade |
| `invoicing` | exact money, rounding, numbering, state machine |
| `dashboard` | aggregation, time zones, half-open ranges |
| `bot` | exact texts, priorities, expression parser |

`_common/conftest.py` is the shared pytest fixture file. `results/` holds local run results (ignored by version control) and the publishable summary templates.
