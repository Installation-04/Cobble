"""Running the benchmark for a list of models: shared by `cobble models benchmark` and the
background job started from Settings (ADR 0019).

`BenchRig` is what the benchmark needs from the outside (asking a model, running code in the
sandbox, the stored results); `LiveBench` is the real one. `run_models` drives the runner for
several models and reports progress; it stops at the first failure that is not the model's fault
(sandbox down, model unreachable) and stores nothing for the model that was being measured.
`BenchmarkStatus` is the single shared state in Redis: one run at a time, its progress, its last
error. The status never holds a secret, only model names and stable error codes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from cobble.config import Settings
from cobble.providers.module_manager import ModuleManagerRejected, ModuleManagerUnavailable

from .runner import BenchmarkResult, run_benchmark
from .tasks import TASKS

log = logging.getLogger(__name__)

STATUS_KEY = "cobble:benchmark:status"
LOCK_KEY = "cobble:benchmark:lock"
# A run that stops reporting for this long is considered dead (the worker crashed): the lock
# expires by itself and the status reads as interrupted. Every finished task renews it.
LOCK_TTL_S = 30 * 60

SANDBOX_CODES = frozenset(
    {"sandbox_unavailable", "docker_unavailable", "sandbox_busy", "sandbox_error"}
)


class BenchRig(Protocol):
    """What the benchmark needs from the outside: asking a model, running code, the results."""

    def chat(self, model: str) -> Callable[[list[dict[str, str]]], Any]: ...
    def run_code(self, program: str, timeout_s: float) -> dict[str, Any]: ...
    def store(self, result: Any) -> None: ...
    def latest(self) -> list[Any]: ...


class LiveBench:
    """The real thing: the gateway for the model, the module-manager's sandbox for the code."""

    def __init__(self, settings: Settings, api: Any) -> None:
        from cobble.db import make_engine, make_session_factory
        from cobble.router.gateway import LiteLLMGateway

        self._sessions = make_session_factory(make_engine(settings.database_url))
        self._gateway = LiteLLMGateway(settings.litellm_url, settings.litellm_key, self._sessions)
        self._api = api

    def chat(self, model: str) -> Callable[[list[dict[str, str]]], Any]:
        def ask(messages: list[dict[str, str]]) -> Any:
            return self._gateway.chat(model, list(messages), role="benchmark")

        return ask

    def run_code(self, program: str, timeout_s: float) -> dict[str, Any]:
        result: dict[str, Any] = self._api.sandbox_run(program, timeout_s)
        return result

    def store(self, result: Any) -> None:
        from .service import store

        store(self._sessions, result)

    def latest(self) -> list[Any]:
        from .service import latest
        from .tasks import VERSION

        return latest(self._sessions, VERSION)


def run_models(
    names: list[str],
    rig: BenchRig,
    *,
    on_start: Callable[[str, int], None] | None = None,
    on_task: Callable[[str, int, int, int], None] | None = None,
    on_result: Callable[[BenchmarkResult], None] | None = None,
) -> str | None:
    """Measure and store each model in turn. Returns None, or the code of the failure that
    stopped the run: a sandbox code, `module_manager_unavailable`, or `model_error`.
    `on_task(model, model_index, done, total)` is called as the tasks of a model go by."""
    for index, name in enumerate(names):
        if on_start is not None:
            on_start(name, index)
        failure: dict[str, str] = {}

        def run_code(program: str, timeout_s: float, _failure: dict[str, str] = failure) -> Any:
            try:
                return rig.run_code(program, timeout_s)
            except ModuleManagerRejected as exc:
                _failure["code"] = exc.code if exc.code in SANDBOX_CODES else "sandbox_error"
                raise
            except ModuleManagerUnavailable:
                _failure["code"] = "module_manager_unavailable"
                raise
            except Exception:
                _failure["code"] = "sandbox_error"
                raise

        def progress(done: int, total: int, _name: str = name, _index: int = index) -> None:
            if on_task is not None:
                on_task(_name, _index, done, total)

        try:
            result = run_benchmark(name, rig.chat(name), run_code, progress=progress)
        except Exception as exc:  # the model could not answer: say so, do not crash the worker
            log.warning("benchmark of %s stopped: %s", name, type(exc).__name__)
            return "model_error"
        if "code" in failure or any(o.error == "sandbox_error" for o in result.outcomes):
            return failure.get("code", "sandbox_error")
        rig.store(result)
        if on_result is not None:
            on_result(result)
    return None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _idle() -> dict[str, Any]:
    return {
        "state": "idle",
        "models": [],
        "model": None,
        "model_index": 0,
        "task": 0,
        "tasks": len(TASKS),
        "started_at": None,
        "finished_at": None,
        "error": None,
    }


class BenchmarkStatus:
    """The benchmark's shared state in Redis: at most one run at a time (a lock that expires),
    which model is being measured, how far it got, and how the last run ended."""

    def __init__(self, redis: Any) -> None:
        self._redis = redis

    def start(self, models: list[str]) -> bool:
        """Take the lock and publish the run as started. False when a run is already going."""
        if not self._redis.set(LOCK_KEY, "1", nx=True, ex=LOCK_TTL_S):
            return False
        self._write(
            {
                **_idle(),
                "state": "running",
                "models": models,
                "model": models[0] if models else None,
                "started_at": _now(),
            }
        )
        return True

    def cancel_start(self) -> None:
        """Undo `start` when the job could not be queued."""
        self._redis.delete(LOCK_KEY)
        self._redis.delete(STATUS_KEY)

    def progress(self, model: str, model_index: int, task: int, tasks: int) -> None:
        self._redis.set(LOCK_KEY, "1", ex=LOCK_TTL_S)  # still alive
        self._write(
            {
                **self._read(),
                "state": "running",
                "model": model,
                "model_index": model_index,
                "task": task,
                "tasks": tasks,
            }
        )

    def finish(self, error: str | None) -> None:
        self._write({**self._read(), "state": "idle", "finished_at": _now(), "error": error})
        self._redis.delete(LOCK_KEY)

    def read(self) -> dict[str, Any]:
        status = self._read()
        if status.get("state") == "running" and not self._redis.get(LOCK_KEY):
            # The worker stopped reporting: nobody is running it any more.
            return {**status, "state": "idle", "finished_at": _now(), "error": "interrupted"}
        return status

    def _read(self) -> dict[str, Any]:
        raw = self._redis.get(STATUS_KEY)
        if not raw:
            return _idle()
        loaded: dict[str, Any] = json.loads(raw)
        return loaded

    def _write(self, status: dict[str, Any]) -> None:
        self._redis.set(STATUS_KEY, json.dumps(status))


def run_job(names: list[str], rig: BenchRig, status: BenchmarkStatus) -> str | None:
    """The background job: measure the models, keep the status up to date, end with the outcome."""
    try:
        error = run_models(
            list(names),
            rig,
            on_task=lambda model, index, done, total: status.progress(model, index, done, total),
        )
    except Exception:  # a bug: record it, never leave the lock behind
        log.exception("benchmark job crashed")
        error = "internal_error"
    status.finish(error)
    return error
