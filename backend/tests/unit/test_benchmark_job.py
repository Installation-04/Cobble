"""The benchmark as a background job: admin API, one run at a time, progress, errors (ADR 0019)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from cobble.benchmark.job import LOCK_KEY, BenchmarkStatus, run_job, run_models
from cobble.events import JOBS_STREAM
from cobble.providers.module_manager import ModuleManagerRejected, ModuleManagerUnavailable
from cobble.worker import consume_jobs_once, ensure_jobs_group, make_job_handler

from .fakes import FakeStreamRedis
from .test_cli_models import Rig
from .test_models_api import API, Built, H, with_local_model

RUN = f"{API}/benchmarks/run"
STATUS = f"{API}/benchmarks/status"


@pytest.fixture
def built(sessions: sessionmaker[Session]) -> Built:
    return Built(sessions)


def worker(built: Built, rig: Rig) -> int:
    """What the worker does with the queued job, against the same Redis as the API."""
    redis: Any = built.stack.redis
    ensure_jobs_group(redis)
    handler = make_job_handler(
        None,  # type: ignore[arg-type]  # no planner job in these tests
        benchmark=lambda names: run_job(names, rig, BenchmarkStatus(redis)),
    )
    return consume_jobs_once(redis, "w1", handler, block_ms=1)


# --- the API ----------------------------------------------------------------------------------


def test_the_benchmark_is_for_administrators_only(built: Built) -> None:
    built.stack.login(built.api, role="member")
    assert built.api.post(RUN, json={}, headers=H).status_code == 403
    assert built.api.get(STATUS).status_code == 403
    built.api.cookies.clear()
    assert built.api.post(RUN, json={}, headers=H).status_code == 401
    assert built.api.get(STATUS).status_code == 401


def test_when_nothing_ran_the_status_is_idle(built: Built) -> None:
    body = built.api.get(STATUS).json()
    assert body["state"] == "idle" and body["error"] is None and body["tasks"] == 8


def test_a_run_is_queued_without_blocking_and_reads_as_running(built: Built) -> None:
    name = with_local_model(built)
    reply = built.api.post(RUN, json={}, headers=H)
    assert reply.status_code == 202
    assert reply.json()["state"] == "running" and reply.json()["models"] == [name]
    assert built.stack.redis.entries(JOBS_STREAM)[-1]["job"].count(name) == 1
    assert built.api.get(STATUS).json()["model"] == name


def test_only_one_run_at_a_time(built: Built) -> None:
    with_local_model(built)
    assert built.api.post(RUN, json={}, headers=H).status_code == 202
    again = built.api.post(RUN, json={}, headers=H)
    assert again.status_code == 409 and again.json()["error"]["code"] == "benchmark_running"
    assert len(built.stack.redis.entries(JOBS_STREAM)) == 1


def test_no_local_model_and_nothing_chosen_is_refused(built: Built) -> None:
    reply = built.api.post(RUN, json={}, headers=H)
    assert reply.status_code == 422 and reply.json()["error"]["code"] == "benchmark_nothing"
    assert built.api.get(STATUS).json()["state"] == "idle"


def test_unknown_models_are_refused(built: Built) -> None:
    with_local_model(built)
    reply = built.api.post(RUN, json={"models": ["ghost"]}, headers=H)
    assert reply.status_code == 422 and reply.json()["error"]["code"] == "model_unknown"


def test_paid_models_need_an_explicit_confirmation(built: Built) -> None:
    with_local_model(built)
    built.api.put(
        f"{API}/cheap",
        json={"provider": "openai", "model": "gpt-4.1-mini", "api_key": "sk-x" * 8},
        headers=H,
    )
    refused = built.api.post(RUN, json={"models": ["cheap"]}, headers=H)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "benchmark_paid"
    assert refused.json()["error"]["params"]["names"] == ["cheap"]
    assert built.stack.redis.entries(JOBS_STREAM) == []
    accepted = built.api.post(RUN, json={"models": ["cheap"], "allow_paid": True}, headers=H)
    assert accepted.status_code == 202 and accepted.json()["models"] == ["cheap"]


def test_a_queue_that_is_down_frees_the_lock(built: Built) -> None:
    with_local_model(built)
    real = built.stack.redis.xadd

    def broken(*_a: Any, **_k: Any) -> Any:
        from redis.exceptions import RedisError

        raise RedisError("down")

    built.stack.redis.xadd = broken  # type: ignore[method-assign]
    reply = built.api.post(RUN, json={}, headers=H)
    assert reply.status_code == 503 and reply.json()["error"]["code"] == "queue_unavailable"
    built.stack.redis.xadd = real  # type: ignore[method-assign]
    assert built.api.post(RUN, json={}, headers=H).status_code == 202


# --- the worker -------------------------------------------------------------------------------


def test_the_worker_runs_the_job_reports_progress_and_stores_the_results(built: Built) -> None:
    name = with_local_model(built)
    built.api.post(RUN, json={}, headers=H)
    rig = Rig()
    assert worker(built, rig) == 1
    status = built.api.get(STATUS).json()
    assert status["state"] == "idle" and status["error"] is None
    assert status["task"] == 8 and status["model"] == name and status["finished_at"]
    assert [r.model for r in rig.stored] == [name] and rig.asked.count(name) == 8
    assert built.stack.redis.values.get(LOCK_KEY) is None
    # and a new run may start
    assert built.api.post(RUN, json={}, headers=H).status_code == 202


def test_a_sandbox_that_is_down_is_the_reported_error_not_a_bad_score(built: Built) -> None:
    with_local_model(built)
    built.api.post(RUN, json={}, headers=H)
    rig = Rig()

    def down(_program: str, _timeout: float) -> dict[str, Any]:
        raise ModuleManagerRejected(503, "sandbox_unavailable", {})

    rig.run_code = down  # type: ignore[method-assign]
    worker(built, rig)
    status = built.api.get(STATUS).json()
    assert status["state"] == "idle" and status["error"] == "sandbox_unavailable"
    assert rig.stored == []


def test_progress_is_visible_while_the_job_runs(built: Built) -> None:
    name = with_local_model(built)
    built.api.post(RUN, json={}, headers=H)
    seen: list[tuple[str, int]] = []
    rig = Rig()
    real = rig.run_code

    def spy(program: str, timeout_s: float) -> dict[str, Any]:
        body = built.api.get(STATUS).json()
        seen.append((body["state"], body["task"]))
        return real(program, timeout_s)

    rig.run_code = spy  # type: ignore[method-assign]
    worker(built, rig)
    assert [s for s, _ in seen] == ["running"] * 8
    assert [n for _, n in seen] == list(range(8))  # tasks done so far, as each one runs
    assert built.api.get(STATUS).json()["model"] == name


def test_a_dead_worker_does_not_block_benchmarks_forever(built: Built) -> None:
    with_local_model(built)
    built.api.post(RUN, json={}, headers=H)
    assert built.stack.redis.ttl[LOCK_KEY] > 0  # the lock expires on its own
    built.stack.redis.delete(LOCK_KEY)  # ...which is what its expiry does
    body = built.api.get(STATUS).json()
    assert body["state"] == "idle" and body["error"] == "interrupted"
    assert built.api.post(RUN, json={}, headers=H).status_code == 202


def test_a_job_without_a_runner_is_dropped_not_crashed() -> None:
    redis = FakeStreamRedis()
    ensure_jobs_group(redis)  # type: ignore[arg-type]
    from cobble.events import enqueue_benchmark

    enqueue_benchmark(redis, ["a"])  # type: ignore[arg-type]
    handler = make_job_handler(None)  # type: ignore[arg-type]
    assert consume_jobs_once(redis, "w", handler, block_ms=1) == 1  # type: ignore[arg-type]


# --- the shared runner ------------------------------------------------------------------------


def test_the_failure_codes_of_the_sandbox_are_kept() -> None:
    rig = Rig()
    for error, code in [
        (ModuleManagerRejected(503, "docker_unavailable", {}), "docker_unavailable"),
        (ModuleManagerRejected(500, "something_new", {}), "sandbox_error"),
        (ModuleManagerUnavailable(), "module_manager_unavailable"),
        (RuntimeError("x"), "sandbox_error"),
    ]:

        def fail(_p: str, _t: float, _e: Exception = error) -> dict[str, Any]:
            raise _e

        rig.run_code = fail  # type: ignore[method-assign]
        assert run_models(["m"], rig) == code
    assert rig.stored == []


def test_a_model_that_cannot_answer_stops_the_run_with_a_code() -> None:
    rig = Rig()

    def chat(_model: str) -> Any:
        def ask(_messages: Any) -> Any:
            raise RuntimeError("gateway down")

        return ask

    rig.chat = chat  # type: ignore[method-assign]
    assert run_models(["m"], rig) == "model_error"
    assert rig.stored == []
