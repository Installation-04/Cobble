"""Hidden acceptance tests: metrics dashboard. They only use the public HTTP API of the spec."""

from __future__ import annotations

from fastapi.testclient import TestClient


def event(client: TestClient, name: str, value: float, timestamp: str | None = None, **extra) -> dict:  # type: ignore[no-untyped-def]
    body = {"name": name, "value": value, **extra}
    if timestamp:
        body["timestamp"] = timestamp
    response = client.post("/api/events", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200


def test_an_event_is_stored_with_defaults(client: TestClient) -> None:
    created = event(client, "page.views", 3, "2026-03-05T10:15:00Z")
    assert created["name"] == "page.views"
    assert created["value"] == 3
    assert created["source"] == "default"
    assert created["timestamp"] == "2026-03-05T10:15:00Z"
    assert "id" in created


def test_the_timestamp_defaults_to_now(client: TestClient) -> None:
    created = event(client, "cpu", 1.5)
    assert created["timestamp"].endswith("Z") and len(created["timestamp"]) == 20


def test_timestamps_are_normalised_to_utc(client: TestClient) -> None:
    created = event(client, "m", 1, "2026-03-05T12:15:00+02:00")
    assert created["timestamp"] == "2026-03-05T10:15:00Z"


def test_event_validation(client: TestClient) -> None:
    def post(**fields) -> int:  # type: ignore[no-untyped-def]
        return client.post("/api/events", json=fields).status_code

    assert post(name="ok", value=1) == 201
    assert post(value=1) == 422
    assert post(name="ok") == 422
    assert post(name="", value=1) == 422
    assert post(name="Has Space", value=1) == 422
    assert post(name="x" * 51, value=1) == 422
    assert post(name="ok", value="abc") == 422
    assert post(name="ok", value=1, timestamp="yesterday") == 422
    assert post(name="ok", value=1, source="") == 422


def test_metric_names_with_counts(client: TestClient) -> None:
    event(client, "b.metric", 1)
    event(client, "a.metric", 1)
    event(client, "a.metric", 2)
    assert client.get("/api/metrics").json() == [
        {"name": "a.metric", "count": 2},
        {"name": "b.metric", "count": 1},
    ]


def test_summary(client: TestClient) -> None:
    for value in (10, 20, 25):
        event(client, "latency", value, "2026-03-05T10:00:00Z")
    body = client.get("/api/metrics/latency/summary").json()
    assert body["name"] == "latency"
    assert body["count"] == 3
    assert body["sum"] == 55
    assert body["min"] == 10
    assert body["max"] == 25
    assert body["avg"] == 18.33


def test_summary_of_an_unknown_metric_is_404(client: TestClient) -> None:
    assert client.get("/api/metrics/nothing/summary").status_code == 404
    assert client.get("/api/metrics/nothing/series").status_code == 404
    assert client.get("/api/metrics/nothing/top-sources").status_code == 404


def test_summary_date_range_is_from_inclusive_to_exclusive(client: TestClient) -> None:
    event(client, "m", 1, "2026-03-05T00:00:00Z")
    event(client, "m", 2, "2026-03-05T12:00:00Z")
    event(client, "m", 4, "2026-03-06T00:00:00Z")
    url = "/api/metrics/m/summary?from=2026-03-05T00:00:00Z&to=2026-03-06T00:00:00Z"
    body = client.get(url).json()
    assert (body["count"], body["sum"]) == (2, 3)
    only_from = client.get("/api/metrics/m/summary?from=2026-03-05T12:00:00Z").json()
    assert (only_from["count"], only_from["sum"]) == (2, 6)


def test_an_empty_range_is_not_an_error(client: TestClient) -> None:
    event(client, "m", 1, "2026-03-05T00:00:00Z")
    body = client.get("/api/metrics/m/summary?from=2027-01-01T00:00:00Z").json()
    assert body["count"] == 0 and body["sum"] == 0
    assert body["min"] is None and body["max"] is None and body["avg"] is None


def test_a_bad_range_is_422(client: TestClient) -> None:
    event(client, "m", 1, "2026-03-05T00:00:00Z")
    assert client.get("/api/metrics/m/summary?from=soon").status_code == 422


def test_series_by_day(client: TestClient) -> None:
    event(client, "sales", 10, "2026-03-05T09:00:00Z")
    event(client, "sales", 20, "2026-03-05T18:00:00Z")
    event(client, "sales", 5, "2026-03-07T08:00:00Z")
    body = client.get("/api/metrics/sales/series?bucket=day").json()
    assert body == [
        {"start": "2026-03-05T00:00:00Z", "count": 2, "sum": 30, "avg": 15},
        {"start": "2026-03-07T00:00:00Z", "count": 1, "sum": 5, "avg": 5},
    ]


def test_series_defaults_to_days_and_supports_hours(client: TestClient) -> None:
    event(client, "t", 1, "2026-03-05T09:05:00Z")
    event(client, "t", 3, "2026-03-05T09:55:00Z")
    event(client, "t", 5, "2026-03-05T11:00:00Z")
    assert len(client.get("/api/metrics/t/series").json()) == 1
    hours = client.get("/api/metrics/t/series?bucket=hour").json()
    assert [(b["start"], b["count"], b["sum"]) for b in hours] == [
        ("2026-03-05T09:00:00Z", 2, 4),
        ("2026-03-05T11:00:00Z", 1, 5),
    ]
    assert client.get("/api/metrics/t/series?bucket=week").status_code == 422


def test_series_buckets_follow_utc(client: TestClient) -> None:
    event(client, "tz", 1, "2026-03-05T23:30:00-05:00")  # 2026-03-06 04:30 UTC
    body = client.get("/api/metrics/tz/series?bucket=day").json()
    assert [b["start"] for b in body] == ["2026-03-06T00:00:00Z"]


def test_series_respects_the_range(client: TestClient) -> None:
    for day in (5, 6, 7):
        event(client, "r", day, f"2026-03-0{day}T12:00:00Z")
    body = client.get("/api/metrics/r/series?from=2026-03-06T00:00:00Z&to=2026-03-07T00:00:00Z").json()
    assert [b["sum"] for b in body] == [6]


def test_top_sources(client: TestClient) -> None:
    for source, value in (("web", 5), ("app", 9), ("web", 6), ("api", 1), ("cli", 2)):
        event(client, "hits", value, source=source)
    top = client.get("/api/metrics/hits/top-sources").json()
    assert top == [
        {"source": "web", "sum": 11},
        {"source": "app", "sum": 9},
        {"source": "cli", "sum": 2},
    ]
    assert len(client.get("/api/metrics/hits/top-sources?limit=1").json()) == 1
    assert client.get("/api/metrics/hits/top-sources?limit=0").status_code == 422


def test_other_metrics_do_not_leak(client: TestClient) -> None:
    event(client, "a", 100, source="x")
    event(client, "b", 1, source="y")
    assert client.get("/api/metrics/b/summary").json()["sum"] == 1
    assert client.get("/api/metrics/b/top-sources").json() == [{"source": "y", "sum": 1}]


def test_delete_events_of_a_metric(client: TestClient) -> None:
    event(client, "gone", 1)
    event(client, "gone", 2)
    event(client, "kept", 3)
    assert client.delete("/api/events?name=gone").json() == {"deleted": 2}
    assert [m["name"] for m in client.get("/api/metrics").json()] == ["kept"]
    assert client.delete("/api/events?name=gone").json() == {"deleted": 0}


def test_data_survives_a_restart(launcher) -> None:  # type: ignore[no-untyped-def]
    first = launcher.start()
    event(first, "kept", 4, "2026-03-05T10:00:00Z", source="web")
    event(first, "kept", 6, "2026-03-05T11:00:00Z", source="web")
    launcher.stop()
    second = launcher.start()
    body = second.get("/api/metrics/kept/summary").json()
    assert (body["count"], body["sum"], body["avg"]) == (2, 10, 5)
