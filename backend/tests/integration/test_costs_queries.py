"""The cost aggregation and the task controls on real Postgres (numeric sums, GROUP BY on a
NULL ref, the outer join to tasks). Needs COBBLE_TEST_DATABASE_URL."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from cobble import costs
from cobble.db import LLMCall, Plan, Project, Task, TaskRun, User, make_engine, make_session_factory
from cobble.scheduler import control, rules

pytestmark = pytest.mark.integration


def test_costs_and_controls_on_postgres(migrated_database: str) -> None:
    engine = make_engine(migrated_database)
    sessions = make_session_factory(engine)
    try:
        with sessions() as db:
            user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
            db.add(user)
            db.flush()
            project = Project(owner_id=user.id, name="Costs", budget_usd=Decimal("3"))
            db.add(project)
            db.flush()
            db.add(
                Plan(
                    project_id=project.id,
                    version=1,
                    plan={},
                    estimate={"cost_usd": "1.25"},
                    status="approved",
                )
            )
            tasks = [
                Task(
                    project_id=project.id,
                    ref=f"T-00{n}",
                    title="t",
                    milestone="M1",
                    tests="tests/x.py",
                    size="S",
                    role="backend",
                )
                for n in (1, 2)
            ]
            db.add_all(tasks)
            db.flush()
            cheap, strong = "cheap", "strong"
            rows = [
                (None, "planner", strong, "0.10000000", 1000, 500),
                (None, "planner", strong, "0.05000000", 200, 100),
                (tasks[0].id, "worker", cheap, "0.00000001", 1, 1),
                (tasks[0].id, "test-writer", cheap, "0.00000002", 2, 2),
                (tasks[1].id, "worker", strong, "0.20000000", 300, 30),
            ]
            for task_id, role, model, cost, prompt, completion in rows:
                db.add(
                    LLMCall(
                        project_id=project.id,
                        task_id=task_id,
                        role=role,
                        model=model,
                        cost_usd=Decimal(cost),
                        prompt_tokens=prompt,
                        completion_tokens=completion,
                    )
                )
            db.commit()

            body = costs.project_costs(db, project)
            assert body["spent_usd"] == "0.35000003"  # exact: no float drift
            assert body["budget_usd"] == "3.00"
            assert body["estimate_usd"] == "1.25"
            assert body["tokens"] == {"prompt": 1503, "completion": 633}
            assert [r["ref"] for r in body["by_task"]] == ["T-001", "T-002", None]
            assert [r["cost_usd"] for r in body["by_task"]] == ["0.00000003", "0.20", "0.15"]
            assert [r["model"] for r in body["by_model"]] == ["strong", "cheap"]
            assert {r["role"]: r["calls"] for r in body["by_role"]} == {
                "planner": 2,
                "worker": 2,
                "test-writer": 1,
            }
            overview = costs.global_costs(db, user.id)
            assert [(r["project_id"], r["spent_usd"]) for r in overview] == [
                (str(project.id), "0.35000003")
            ]

            # The controls on real rows: stop closes the run, retry retires and resets.
            task = tasks[0]
            task.state = rules.IMPLEMENTING
            db.add(TaskRun(task_id=task.id, kind="worker", attempt=1, model="m", state="failed"))
            db.commit()
            control.apply(db, task, control.Action.PAUSE)
            assert control.is_held(task.state, task.last_error)
            control.apply(db, task, control.Action.STOP)
            assert task.state == rules.STOPPED
            control.apply(db, task, control.Action.RETRY)
            db.refresh(task)
            assert (task.state, task.attempts, task.last_error) == ("todo", 0, None)
            run = db.scalars(select(TaskRun).where(TaskRun.task_id == task.id)).one()
            assert run.state == "retired"
    finally:
        engine.dispose()
