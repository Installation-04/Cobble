# Metrics dashboard

Small services send measurements ("events") to this application. A person looks at totals, averages and the evolution over time. No accounts and no login.

## Features
- Record an event: `name` (1 to 50 characters, only lowercase letters, digits, `_` and `.`), `value` (a number), `source` (1 to 50 characters, `"default"` when missing) and `timestamp` (ISO 8601 date and time; now when missing). The timestamp is **converted to UTC** and returned as `YYYY-MM-DDTHH:MM:SSZ` (`2026-03-05T12:15:00+02:00` becomes `2026-03-05T10:15:00Z`). A timestamp that is not a valid ISO 8601 date is refused.
- List the metrics (distinct event names) with their number of events, sorted by name.
- **Summary** of a metric: `count`, `sum`, `min`, `max` and `avg` (the average rounded to two decimals). Optional range `from` and `to` (ISO 8601): `from` is included, `to` is excluded. An empty range gives `count` 0, `sum` 0 and `null` for `min`, `max` and `avg`. An unknown metric (no event at all) is a 404; an invalid range is a 422.
- **Series** of a metric: the events grouped in buckets of one `hour` or one `day` (default `day`), in UTC, in ascending order, with the same `from`/`to` range. Only buckets that have events appear. Each bucket gives its `start` (`2026-03-05T00:00:00Z`), `count`, `sum` and `avg`.
- **Top sources** of a metric: the sources with the biggest sums, biggest first (ties by source name), at most `limit` of them (default 3, from 1 to 20).
- Delete all the events of a metric.

## Screens
- A dashboard page: the list of metrics, and for the chosen metric its summary, a simple chart of the series and its top sources.

## Data model
- Event: id, name, value, source, timestamp.

## Constraints
- FastAPI backend, data kept on disk (it survives a restart).
- Usable on a phone screen.

## Out of scope
- Alerts, authentication, several dashboards, exports.

## Acceptance criteria
- `GET /api/health` answers 200.
- `POST /api/events` answers 201 with the event (422 for invalid fields). `DELETE /api/events?name=x` answers `{"deleted": n}`.
- `GET /api/metrics` lists `[{"name", "count"}]`.
- `GET /api/metrics/{name}/summary?from=&to=`, `GET /api/metrics/{name}/series?bucket=&from=&to=`, `GET /api/metrics/{name}/top-sources?limit=`.
