from __future__ import annotations

from cobble.scheduler import rules
from cobble.scheduler.rules import TaskView, blocked_refs, runnable


def view(ref: str, state: str = "todo", deps: tuple[str, ...] = (), *files: str) -> TaskView:
    return TaskView(ref, state, deps, files or (f"{ref}.py",))


def test_only_tasks_without_pending_dependencies_run() -> None:
    tasks = [
        view("T-001"),
        view("T-002", "todo", ("T-001",)),
        view("T-003", "todo", ("T-001", "T-002")),
    ]
    assert runnable(tasks, 5) == ["T-001"]
    tasks[0] = view("T-001", "merged")
    assert runnable(tasks, 5) == ["T-002"]
    tasks[1] = view("T-002", "ci")
    assert runnable(tasks, 5) == []  # T-003 waits for T-002 to be merged, not just open
    tasks[1] = view("T-002", "merged")
    assert runnable(tasks, 5) == ["T-003"]


def test_unknown_dependency_never_runs() -> None:
    assert runnable([view("T-001", "todo", ("T-999",))], 5) == []


def test_files_of_active_tasks_are_taken() -> None:
    tasks = [
        view("T-001", "implementing", (), "app/a.py", "tests/a.py"),
        view("T-002", "todo", (), "app/a.py"),
        view("T-003", "todo", (), "app/c.py"),
    ]
    assert runnable(tasks, 5) == ["T-003"]


def test_every_active_state_holds_its_files() -> None:
    for state in ("writing_tests", "implementing", "ci"):
        tasks = [view("T-001", state, (), "x.py"), view("T-002", "todo", (), "x.py")]
        assert runnable(tasks, 5) == []
    for state in ("merged", "failed", "blocked"):
        tasks = [view("T-001", state, (), "x.py"), view("T-002", "todo", (), "x.py")]
        assert runnable(tasks, 5) == ["T-002"]


def test_candidates_do_not_overlap_each_other() -> None:
    tasks = [view("T-001", "todo", (), "x.py"), view("T-002", "todo", (), "./x.py", "y.py")]
    assert runnable(tasks, 5) == ["T-001"]


def test_parallel_cap_counts_running_agents_only() -> None:
    tasks = [view(f"T-00{i}") for i in range(1, 6)]
    assert runnable(tasks, 2) == ["T-001", "T-002"]
    tasks[0] = view("T-001", "implementing")
    assert runnable(tasks, 2) == ["T-002"]
    tasks[1] = view("T-002", "writing_tests")
    assert runnable(tasks, 2) == []
    tasks[1] = view("T-002", "ci")  # waiting for CI uses no agent
    assert runnable(tasks, 2) == ["T-003"]
    assert runnable(tasks, 0) == []


def test_order_is_numeric_and_paused_tasks_go_first() -> None:
    tasks = [view("T-10"), view("T-2"), view("T-5", "paused")]
    assert runnable(tasks, 3) == ["T-5", "T-2", "T-10"]


def test_paused_task_keeps_its_files_when_it_cannot_start() -> None:
    tasks = [
        view("T-001", "implementing", (), "a.py"),
        view("T-002", "paused", (), "a.py", "b.py"),
        view("T-003", "todo", (), "b.py"),
    ]
    assert runnable(tasks, 5) == []  # T-002 is waiting for a.py; nobody takes b.py meanwhile


def test_blocked_propagation_is_transitive() -> None:
    tasks = [
        view("T-001", "failed"),
        view("T-002", "todo", ("T-001",)),
        view("T-003", "todo", ("T-002",)),
        view("T-004", "todo", ("T-003",)),
        view("T-005", "todo"),
        view("T-006", "merged", ("T-001",)),
    ]
    assert blocked_refs(tasks) == ["T-002", "T-003", "T-004"]
    assert runnable(tasks, 5) == ["T-005"]


def test_blocked_dependency_blocks_too_and_nothing_else_does() -> None:
    tasks = [view("T-001", "blocked"), view("T-002", "todo", ("T-001",)), view("T-003", "stopped")]
    assert blocked_refs(tasks) == ["T-002"]
    assert blocked_refs([view("T-001", "implementing"), view("T-002", "todo", ("T-001",))]) == []


def test_completion() -> None:
    assert not rules.all_merged([])
    assert rules.all_merged([view("T-001", "merged"), view("T-002", "merged")])
    assert not rules.all_merged([view("T-001", "merged"), view("T-002", "failed")])


def test_states_are_the_documented_ones() -> None:
    assert set(rules.TASK_STATES) == {
        "todo",
        "writing_tests",
        "implementing",
        "ci",
        "merged",
        "failed",
        "blocked",
        "paused",
        "stopped",
    }
