from __future__ import annotations

from decimal import Decimal

from cobble.config import Settings
from cobble.orchestrator.estimate import estimate_from_settings, estimate_plan
from cobble.orchestrator.plan_schema import Plan, validate_plan


def plan_of(*tasks: tuple[str, str, str]) -> Plan:
    """Tasks as (id, milestone, size)."""
    return validate_plan(
        {
            "milestones": [
                {"id": "M1", "title": "a"},
                {"id": "M2", "title": "b"},
                {"id": "M3", "title": "c"},
            ],
            "tasks": [
                {
                    "id": tid,
                    "title": "t",
                    "milestone": milestone,
                    "files": ["a.py"],
                    "acceptance": ["works"],
                    "tests": "t.py",
                    "size": size,
                    "role": "backend",
                }
                for tid, milestone, size in tasks
            ],
        }
    )


def test_tokens_use_the_size_and_the_review_multiplier() -> None:
    plan = plan_of(("T-001", "M1", "S"), ("T-002", "M1", "M"))
    result = estimate_plan(
        plan, tokens_s=20_000, tokens_m=50_000, usd_per_1k_tokens=Decimal("0.002")
    )
    # S: 20000 x 1.5 = 30000, M: 50000 x 1.5 = 75000
    assert result["tokens"] == 105_000
    assert result["cost_usd"] == "0.21"
    assert result["milestones"][0] == {"id": "M1", "tokens": 105_000, "cost_usd": "0.21"}


def test_milestones_are_split_and_empty_ones_cost_nothing() -> None:
    plan = plan_of(("T-001", "M1", "S"), ("T-002", "M2", "S"), ("T-003", "M2", "M"))
    result = estimate_plan(
        plan, tokens_s=20_000, tokens_m=50_000, usd_per_1k_tokens=Decimal("0.002")
    )
    assert result["milestones"] == [
        {"id": "M1", "tokens": 30_000, "cost_usd": "0.06"},
        {"id": "M2", "tokens": 105_000, "cost_usd": "0.21"},
        {"id": "M3", "tokens": 0, "cost_usd": "0.00"},
    ]
    assert result["tokens"] == sum(m["tokens"] for m in result["milestones"])


def test_cost_is_a_two_decimal_string_rounded_half_up() -> None:
    plan = plan_of(("T-001", "M1", "S"))
    # 30000 tokens x 0.0175 / 1000 = 0.525 -> 0.53
    result = estimate_plan(plan, tokens_s=20_000, tokens_m=1, usd_per_1k_tokens=Decimal("0.0175"))
    assert result["cost_usd"] == "0.53"
    assert isinstance(result["cost_usd"], str)


def test_settings_drive_the_estimate() -> None:
    plan = plan_of(("T-001", "M1", "S"), ("T-002", "M1", "M"))
    settings = Settings(
        estimate_tokens_s=1000, estimate_tokens_m=2000, estimate_usd_per_1k_tokens=Decimal("1")
    )
    result = estimate_from_settings(plan, settings)
    assert result["tokens"] == 1500 + 3000
    assert result["cost_usd"] == "4.50"


def test_defaults_match_the_adr() -> None:
    settings = Settings()
    assert settings.estimate_tokens_s == 20_000
    assert settings.estimate_tokens_m == 50_000
    assert settings.estimate_usd_per_1k_tokens == Decimal("0.002")


def test_settings_read_the_environment(monkeypatch: object) -> None:
    import pytest

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    monkeypatch.setenv("COBBLE_ESTIMATE_TOKENS_S", "10")
    monkeypatch.setenv("COBBLE_ESTIMATE_TOKENS_M", "20")
    monkeypatch.setenv("COBBLE_ESTIMATE_USD_PER_1K_TOKENS", "0.5")
    settings = Settings()
    assert (settings.estimate_tokens_s, settings.estimate_tokens_m) == (10, 20)
    assert settings.estimate_usd_per_1k_tokens == Decimal("0.5")
