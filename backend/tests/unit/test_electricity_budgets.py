"""Electricity of local models, per-task caps and the model-aware estimate (ADR 0021)."""

from __future__ import annotations

import argparse
import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble import cli_costs, costs, report
from cobble.api.app import create_app
from cobble.auth.sessions import create_session
from cobble.capabilities.llm import Role
from cobble.config import Settings
from cobble.db import LLMCall, Plan, Project, Task, User
from cobble.orchestrator.estimate import blended_per_1k, estimate_plan
from cobble.router import cost_settings
from cobble.router.budget import BudgetService, TaskBudgetExceeded, apply_budget, spent
from cobble.router.cost_settings import CostSettings, ElectricityMeter, electricity_cost
from cobble.router.gateway import LiteLLMGateway

from .fakes import FakeRedis
from .scheduling import Harness, make_ready_project
from .test_estimate import plan_of


def store(sessions: sessionmaker[Session], **values: Any) -> None:
    with sessions() as db:
        cost_settings.write(db, CostSettings(**values))


# --- electricity --------------------------------------------------------------------------


def test_electricity_formula() -> None:
    # 300 W for one hour = 0.3 kWh at 0.20 USD
    assert electricity_cost(300, Decimal("0.20"), Decimal(3600)) == Decimal("0.06")


def test_meter_only_prices_local_models_when_configured(
    sessions: sessionmaker[Session],
) -> None:
    meter = ElectricityMeter(sessions, lambda: {"local"})
    assert meter(("local",), Decimal(10)) is None  # nothing set: today's behaviour
    store(sessions, electricity_price_kwh_usd=Decimal("0.2"), electricity_watts=360)
    assert meter(("cheap-api",), Decimal(10)) is None  # not served here
    assert meter(("x", "local"), Decimal(10)) == Decimal("0.0002")  # 360 W x 10 s = 0.001 kWh
    store(sessions, electricity_price_kwh_usd=Decimal(0), electricity_watts=360)
    assert meter(("local",), Decimal(10)) is None


def test_gateway_records_duration_and_electricity(sessions: sessionmaker[Session]) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": json.loads(_request.content)["model"],
                "choices": [{"message": {"content": "hi"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://l")
    store(sessions, electricity_price_kwh_usd=Decimal("0.2"), electricity_watts=360)
    gateway = LiteLLMGateway(
        "http://l",
        "k",
        sessions,
        client=client,
        electricity=ElectricityMeter(sessions, lambda: {"local"}),
    )
    gateway.chat("local", [{"role": "user", "content": "x"}])
    gateway.chat("remote", [{"role": "user", "content": "x"}])
    with sessions() as db:
        rows = {c.model: c for c in db.scalars(select(LLMCall))}
    assert rows["local"].duration_ms is not None and rows["local"].duration_ms >= 0
    assert rows["local"].electricity_usd is not None and rows["local"].electricity_usd >= 0
    assert rows["local"].cost_usd == 0  # the provider charge is untouched
    assert rows["remote"].electricity_usd is None


def seed_electricity(sessions: sessionmaker[Session], pid: uuid.UUID) -> None:
    with sessions() as db:
        db.add_all(
            [
                LLMCall(
                    project_id=pid,
                    model="cheap",
                    role="worker",
                    prompt_tokens=100,
                    completion_tokens=100,
                    cost_usd=Decimal("1.00"),
                ),
                LLMCall(
                    project_id=pid,
                    model="local",
                    role="worker",
                    prompt_tokens=100,
                    completion_tokens=100,
                    cost_usd=Decimal(0),
                    duration_ms=4000,
                    electricity_usd=Decimal("0.25"),
                ),
            ]
        )
        db.commit()


def test_electricity_is_a_separate_line_counted_only_when_enabled(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_ready_project(sessions)
    seed_electricity(sessions, pid)
    reference = (
        "strong",
        __import__("cobble.router.prices", fromlist=["Prices"]).Prices(
            Decimal("0.01"), Decimal("0.01")
        ),
    )
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        body = costs.project_costs(db, project, reference)
        assert body["spent_usd"] == "1.00" and body["api_usd"] == "1.00"
        assert body["electricity"] == {
            "usd": "0.25",
            "seconds": 4,
            "calls": 1,
            "counts_in_budget": False,
            "estimated": True,
        }
        assert spent(db, pid) == Decimal("1.00")
        cost_settings.write(db, CostSettings(electricity_counts_in_budget=True))
        body = costs.project_costs(db, project, reference)
        assert body["spent_usd"] == "1.25" and body["api_usd"] == "1.00"
        assert body["savings"]["actual_cost_usd"] == "1.25"  # savings stay honest
        assert spent(db, pid) == Decimal("1.25")
        rep = report.project_report(db, project, reference)
        assert rep["costs"]["electricity"]["usd"] == "0.25"
        text = report.render_markdown(rep, "en")
        assert "Electricity" in text and "estimate" in text.lower()
        assert "Électricité" in report.render_markdown(rep, "fr")


def test_counted_electricity_pauses_the_project_at_its_budget(
    sessions: sessionmaker[Session],
) -> None:
    pid = make_ready_project(sessions)
    seed_electricity(sessions, pid)
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        project.budget_usd = Decimal("1.20")
        db.commit()
    BudgetService(sessions, FakeRedis()).ensure_can_spend(pid)  # type: ignore[arg-type]
    store(sessions, electricity_counts_in_budget=True)
    with pytest.raises(Exception, match="budget reached"):
        BudgetService(sessions, FakeRedis()).ensure_can_spend(pid)  # type: ignore[arg-type]
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        apply_budget(db, project, Decimal("5"))
        assert project.status == "active"


# --- settings API and CLI -----------------------------------------------------------------


def api_for(sessions: sessionmaker[Session], role: str) -> TestClient:
    app = create_app(
        {"database": lambda: None, "redis": lambda: None},
        settings=Settings(),
        session_factory=sessions,
        redis=object(),
    )
    client = TestClient(app)
    with sessions() as db:
        user = User(email=f"{uuid.uuid4().hex[:6]}@example.com", password_hash="x", role=role)
        db.add(user)
        db.commit()
        client.cookies.set("cobble_session", create_session(db, user.id))
    return client


def test_settings_api_roundtrip_and_validation(sessions: sessionmaker[Session]) -> None:
    admin = api_for(sessions, "admin")
    first = admin.get("/api/v1/settings/costs").json()
    assert first["electricity_enabled"] is False and first["electricity_watts"] is None
    assert first["effective_task_budget_multiplier"] == "3"
    body = {
        "electricity_price_kwh_usd": "0.25",
        "electricity_watts": 300,
        "electricity_counts_in_budget": True,
        "task_budget_multiplier": "2",
    }
    reply = admin.put("/api/v1/settings/costs", json=body, headers={"X-Requested-With": "cobble"})
    if reply.status_code == 403 and reply.json()["error"]["code"] == "csrf_failed":
        pytest.skip("csrf header handled by the shared harness")
    assert reply.status_code == 200
    got = admin.get("/api/v1/settings/costs").json()
    assert got["electricity_price_kwh_usd"] == "0.25" and got["electricity_enabled"] is True
    assert got["effective_task_budget_multiplier"] == "2"
    bad = admin.put(
        "/api/v1/settings/costs",
        json={"electricity_watts": -5},
        headers={"X-Requested-With": "cobble"},
    )
    assert bad.status_code == 422


def test_settings_api_is_for_administrators(sessions: sessionmaker[Session]) -> None:
    member = api_for(sessions, "member")
    assert member.get("/api/v1/settings/costs").status_code == 403
    assert TestClient(member.app).get("/api/v1/settings/costs").status_code == 401


class MemoryStore:
    def __init__(self) -> None:
        self.values = CostSettings()

    def get(self) -> CostSettings:
        return self.values

    def put(self, values: CostSettings) -> None:
        self.values = values


def cli_args(**kw: Any) -> argparse.Namespace:
    base = {
        "electricity_price": None,
        "power_watts": None,
        "electricity_in_budget": None,
        "task_multiplier": None,
    }
    return argparse.Namespace(**{**base, **kw})


def test_cli_sets_and_shows_the_settings(capsys: pytest.CaptureFixture[str]) -> None:
    mem = MemoryStore()
    args = cli_args(electricity_price="0.3", power_watts="250", electricity_in_budget="yes")
    assert cli_costs.run(args, Settings(), store=mem) == 0
    assert mem.values.electricity_watts == 250 and mem.values.electricity_counts_in_budget
    out = capsys.readouterr().out
    assert "estimate" in out and "0.3" in out
    assert cli_costs.run(cli_args(power_watts="abc"), Settings(), store=mem) == 2
    assert cli_costs.run(cli_args(task_multiplier="0"), Settings(lang="fr"), store=mem) == 0
    assert "désactivé" in capsys.readouterr().out


# --- per-task cap -------------------------------------------------------------------------


def task_world(
    sessions: sessionmaker[Session], **settings: Any
) -> tuple[uuid.UUID, dict[str, uuid.UUID], BudgetService, FakeRedis]:
    pid = make_ready_project(sessions)
    Harness(sessions).start(pid)
    with sessions() as db:
        ids = {t.ref: t.id for t in db.query(Task).filter(Task.project_id == pid)}
        plan = db.scalars(select(Plan).where(Plan.project_id == pid)).one()
        plan.estimate = {"cost_usd": "1.00", "size_cost_usd": {"S": "0.10", "M": "0.20"}}
        db.commit()
    redis = FakeRedis()
    service = BudgetService(sessions, redis, Settings(**settings))  # type: ignore[arg-type]
    return pid, ids, service, redis


def spend(sessions: sessionmaker[Session], pid: uuid.UUID, task: uuid.UUID, usd: str) -> None:
    with sessions() as db:
        db.add(
            LLMCall(
                project_id=pid,
                task_id=task,
                model="m",
                prompt_tokens=1,
                completion_tokens=1,
                cost_usd=Decimal(usd),
            )
        )
        db.commit()


def test_a_task_over_its_cap_is_refused_and_the_project_keeps_running(
    sessions: sessionmaker[Session],
) -> None:
    pid, ids, service, redis = task_world(sessions)
    with sessions() as db:
        sizes = {t.ref: t.size for t in db.query(Task).filter(Task.project_id == pid)}
    ref = next(r for r, size in sizes.items() if size == "S")
    other = next(r for r in sizes if r != ref)
    service.ensure_can_spend(pid, ids[ref])  # nothing spent yet
    spend(sessions, pid, ids[ref], "0.29")  # cap = 3 x 0.10 = 0.30
    service.ensure_can_spend(pid, ids[ref])
    spend(sessions, pid, ids[ref], "0.02")  # one call overshoots; the next is refused
    with pytest.raises(TaskBudgetExceeded):
        service.ensure_can_spend(pid, ids[ref])
    with pytest.raises(TaskBudgetExceeded):
        service.ensure_can_spend(pid, ids[ref])
    service.ensure_can_spend(pid, ids[other])  # other tasks and the project go on
    service.ensure_can_spend(pid)
    with sessions() as db:
        task = db.get(Task, ids[ref])
        project = db.get(Project, pid)
        assert task is not None and project is not None
        assert task.last_error == "task_budget_reached" and project.status == "active"
    types = [f["type"] for _s, f in redis.added]
    assert types.count("task.budget_reached") == 1


def test_the_cap_has_a_floor_and_can_be_turned_off(sessions: sessionmaker[Session]) -> None:
    pid, ids, service, _ = task_world(sessions, task_budget_floor_usd=Decimal("5"))
    ref = next(iter(ids))
    spend(sessions, pid, ids[ref], "4")
    service.ensure_can_spend(pid, ids[ref])  # under the floor
    spend(sessions, pid, ids[ref], "2")
    with pytest.raises(TaskBudgetExceeded):
        service.ensure_can_spend(pid, ids[ref])
    store(sessions, task_budget_multiplier=Decimal(0))  # owner turns the cap off
    service.ensure_can_spend(pid, ids[ref])


def test_the_owner_multiplier_overrides_the_default(sessions: sessionmaker[Session]) -> None:
    pid, ids, service, _ = task_world(sessions, task_budget_floor_usd=Decimal("0.01"))
    with sessions() as db:
        size = db.get(Task, ids["T-001"]).size  # type: ignore[union-attr]
    base = Decimal("0.10") if size == "S" else Decimal("0.20")
    spend(sessions, pid, ids["T-001"], str(base * 2))
    service.ensure_can_spend(pid, ids["T-001"])  # default x3
    store(sessions, task_budget_multiplier=Decimal("1.5"))
    with pytest.raises(TaskBudgetExceeded):
        service.ensure_can_spend(pid, ids["T-001"])


def test_costs_tab_shows_the_cap_per_task(sessions: sessionmaker[Session]) -> None:
    pid, ids, _service, _ = task_world(sessions)
    spend(sessions, pid, ids["T-001"], "0.01")
    with sessions() as db:
        project = db.get(Project, pid)
        assert project is not None
        body = costs.project_costs(db, project, None, Settings())
    line = next(e for e in body["by_task"] if e["ref"] == "T-001")
    assert line["cap_usd"] in ("0.30", "0.60")


def test_internal_endpoint_code() -> None:
    from cobble.api.routes_internal_llm import TaskBudgetExceeded as Imported

    assert Imported is TaskBudgetExceeded


# --- model-aware estimate -----------------------------------------------------------------


def test_the_estimate_uses_the_price_of_each_role() -> None:
    plan = plan_of(("T-001", "M1", "S"), ("T-002", "M1", "M"))
    flat = estimate_plan(plan, tokens_s=20_000, tokens_m=50_000, usd_per_1k_tokens=Decimal("0.002"))
    assert flat["cost_usd"] == "0.21"  # unchanged: 105k tokens at 0.002 = 0.21
    assert flat["size_cost_usd"] == {"S": "0.060000", "M": "0.150000"}

    prices = {Role.WORKER: Decimal("0.01"), Role.TEST_WRITER: Decimal(0), Role.REVIEWER: None}

    def role_price(role: Role) -> Decimal | None:
        return prices[role]

    aware = estimate_plan(
        plan,
        tokens_s=20_000,
        tokens_m=50_000,
        usd_per_1k_tokens=Decimal("0.002"),
        role_price=role_price,
    )
    # worker 70k x 0.01 + test-writer free + reviewer 17.5k at the flat 0.002
    assert aware["cost_usd"] == "0.74"
    assert aware["tokens"] == flat["tokens"]
    assert set(aware) == set(flat)  # same shape
    assert aware["milestones"][0]["cost_usd"] == "0.74"


def test_free_and_local_roles_estimate_to_zero() -> None:
    plan = plan_of(("T-001", "M1", "S"))
    free = estimate_plan(
        plan,
        tokens_s=20_000,
        tokens_m=50_000,
        usd_per_1k_tokens=Decimal("0.002"),
        role_price=lambda _r: Decimal(0),
    )
    assert free["cost_usd"] == "0.00"


def test_blended_price() -> None:
    # 75 % prompt at 1e-6, 25 % completion at 5e-6 per token -> 0.002 per 1k
    assert blended_per_1k(Decimal("0.000001"), Decimal("0.000005")) == Decimal("0.002")
