"""Run install/uninstall operations one at a time, in the background, and report on them."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from cobble_sdk import Plan, ResolveError

from .manager import ModuleManager, ModuleOperationFailed

KEEP_OPERATIONS = 50
Publish = Callable[[str, dict[str, Any]], None]
Spawn = Callable[[Callable[[], None]], None]


class Busy(Exception):
    """Another operation is running: the manager does one at a time."""


@dataclass(frozen=True)
class OperationRequest:
    action: Literal["install", "uninstall"]
    modules: Sequence[str]
    choices: Mapping[str, str] = field(default_factory=dict)
    replace: bool = False
    confirm_cascade: bool = False


@dataclass
class Operation:
    id: str
    action: str
    modules: list[str]
    state: Literal["running", "done", "failed"] = "running"
    plan: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    started_at: float = 0.0
    finished_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "modules": self.modules,
            "state": self.state,
            "plan": self.plan,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def plan_to_json(plan: Plan) -> dict[str, Any]:
    def links(items: Any) -> list[dict[str, str]]:
        return [
            {"consumer": link.consumer, "provider": link.provider, "capability": link.capability}
            for link in sorted(items, key=lambda i: (i.provider, i.consumer, i.capability))
        ]

    return {
        "steps": [{"action": s.action, "module": s.module} for s in plan.steps],
        "explicit": sorted(plan.explicit),
        "installed": sorted(plan.installed),
        "auto_added": list(plan.auto_added),
        "cascade": list(plan.cascade),
        "replaced": list(plan.replaced),
        "auto_removed": list(plan.auto_removed),
        "links_added": links(plan.links_added),
        "links_removed": links(plan.links_removed),
    }


def _thread_spawn(job: Callable[[], None]) -> None:
    threading.Thread(target=job, name="module-operation", daemon=False).start()


class OperationController:
    def __init__(self, publish: Publish, spawn: Spawn = _thread_spawn) -> None:
        self._publish = publish
        self._spawn = spawn
        self._manager: ModuleManager | None = None
        self._guard = threading.Lock()  # held while an operation runs
        self._operations: OrderedDict[str, Operation] = OrderedDict()
        self._current: str | None = None

    def bind(self, manager: ModuleManager) -> None:
        self._manager = manager

    @property
    def manager(self) -> ModuleManager:
        if self._manager is None:
            raise RuntimeError("the controller is not bound to a manager")
        return self._manager

    def preview(self, request: OperationRequest) -> Plan:
        """The plan, or a `ResolveError` saying why there is none. Changes nothing."""
        if request.action == "install":
            return self.manager.plan_install(
                request.modules, request.choices, replace=request.replace
            )
        return self.manager.plan_uninstall(request.modules, confirm_cascade=request.confirm_cascade)

    def on_step(self, event: dict[str, Any]) -> None:
        """Progress from the manager, tagged with the running operation."""
        self._publish("module.step", {"operation_id": self._current, **event})

    def get(self, operation_id: str) -> Operation | None:
        return self._operations.get(operation_id)

    def submit(self, request: OperationRequest) -> Operation:
        if not self._guard.acquire(blocking=False):
            raise Busy
        try:
            plan = self.preview(request)  # refuse early, before anything is started
            operation = Operation(
                id=uuid.uuid4().hex,
                action=request.action,
                modules=list(request.modules),
                plan=plan_to_json(plan),
                started_at=time.time(),
            )
            self._operations[operation.id] = operation
            while len(self._operations) > KEEP_OPERATIONS:
                self._operations.popitem(last=False)
            self._current = operation.id
        except BaseException:
            self._guard.release()
            raise
        self._publish("module.operation", {"operation_id": operation.id, "state": "running"})
        self._spawn(lambda: self._run(operation, request))
        return operation

    def _run(self, operation: Operation, request: OperationRequest) -> None:
        try:
            if request.action == "install":
                self.manager.install(request.modules, request.choices, replace=request.replace)
            else:
                self.manager.uninstall(request.modules, confirm_cascade=request.confirm_cascade)
            operation.state = "done"
        except ModuleOperationFailed as exc:
            operation.state = "failed"
            operation.error = {
                "module": exc.module,
                "step": exc.step,
                "code": exc.code,
                "rolled_back": list(exc.rolled_back),
                "partial": exc.partial,
            }
        except ResolveError as exc:  # the situation changed between the preview and the run
            operation.state = "failed"
            operation.error = {"module": None, "step": "plan", "code": type(exc).__name__}
        except Exception:
            operation.state = "failed"
            operation.error = {"module": None, "step": "unknown", "code": "internal_error"}
        finally:
            operation.finished_at = time.time()
            self._current = None
            self._guard.release()
            self._publish(
                "module.operation",
                {"operation_id": operation.id, "state": operation.state, "error": operation.error},
            )
