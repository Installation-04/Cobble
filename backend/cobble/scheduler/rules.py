"""Pure scheduling rules: which tasks may start, which are blocked, when the project is done.

No I/O here, so the rules are tested without a database (ADR 0006).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

TODO = "todo"
WRITING_TESTS = "writing_tests"
IMPLEMENTING = "implementing"
CI = "ci"
MERGED = "merged"
FAILED = "failed"
BLOCKED = "blocked"
PAUSED = "paused"
STOPPED = "stopped"

TASK_STATES = (
    TODO,
    WRITING_TESTS,
    IMPLEMENTING,
    CI,
    MERGED,
    FAILED,
    BLOCKED,
    PAUSED,
    STOPPED,
)
# States in which a task works on its branch: its files are taken.
ACTIVE = frozenset({WRITING_TESTS, IMPLEMENTING, CI})
# States in which an agent container runs (what `max_parallel` limits).
RUNNING = frozenset({WRITING_TESTS, IMPLEMENTING})
# A dead end: tasks that depend on one of these can never start.
DEAD = frozenset({FAILED, BLOCKED})


@dataclass(frozen=True)
class TaskView:
    ref: str
    state: str
    depends_on: tuple[str, ...] = ()
    files: tuple[str, ...] = ()


# A task whose files contain this may touch anything: it never runs beside another active task.
ANY_FILE = "*"
_KIND_OFFSETS = (("DEMO-", 300_000), ("C-", 100_000), ("R-", 200_000))


def ref_key(ref: str) -> tuple[int, str]:
    """Sort key putting T-2 before T-10, then comments (C-), restores (R-) and demos (DEMO-)."""
    digits = "".join(ch for ch in ref if ch.isdigit())
    offset = next((o for prefix, o in _KIND_OFFSETS if ref.startswith(prefix)), 0)
    return (offset + (int(digits) if digits else 0), ref)


def _norm(path: str) -> str:
    return path.strip().replace("\\", "/").removeprefix("./")


def overlap(a: Iterable[str], b: Iterable[str]) -> bool:
    first = {_norm(p) for p in a}
    second = {_norm(p) for p in b}
    if (ANY_FILE in first and second) or (ANY_FILE in second and first):
        return True
    return bool(first & second)


def runnable(tasks: Iterable[TaskView], max_parallel: int) -> list[str]:
    """Refs to (re)start now, in start order.

    A `todo` task needs every dependency merged. A `paused` task (waiting for a slot or for the
    budget) has them already and goes first. Neither may share a file with a task that is
    active, nor with a candidate chosen before it; at most `max_parallel` agents run at once.
    """
    views = {t.ref: t for t in tasks}
    running = sum(1 for t in views.values() if t.state in RUNNING)
    taken = {_norm(f) for t in views.values() if t.state in ACTIVE for f in t.files}
    candidates = sorted(
        (t for t in views.values() if t.state in (PAUSED, TODO)),
        key=lambda t: (t.state != PAUSED, ref_key(t.ref)),
    )
    chosen: list[str] = []
    for task in candidates:
        files = {_norm(f) for f in task.files}
        if running + len(chosen) >= max_parallel:
            break
        waiting = task.state == TODO and not all(
            dep in views and views[dep].state == MERGED for dep in task.depends_on
        )
        if waiting or overlap(files, taken):
            if task.state == PAUSED:
                taken |= files  # keep its files for it: nobody else may jump in
            continue
        chosen.append(task.ref)
        taken |= files
    return chosen


def blocked_refs(tasks: Iterable[TaskView]) -> list[str]:
    """`todo`/`paused` tasks that depend, directly or not, on a failed or blocked task."""
    views = {t.ref: t for t in tasks}
    dead = {ref for ref, t in views.items() if t.state in DEAD}
    newly: set[str] = set()
    changed = True
    while changed:
        changed = False
        for ref, task in views.items():
            if ref in dead or task.state not in (TODO, PAUSED):
                continue
            if any(dep in dead for dep in task.depends_on):
                dead.add(ref)
                newly.add(ref)
                changed = True
    return sorted(newly, key=ref_key)


def all_merged(tasks: Iterable[TaskView]) -> bool:
    views = list(tasks)
    return bool(views) and all(t.state == MERGED for t in views)
