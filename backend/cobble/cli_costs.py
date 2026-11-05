"""`cobble costs`: show or change the electricity and per-task budget settings (ADR 0021)."""

from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from cobble.config import Settings
from cobble.i18n import t
from cobble.router import task_budget
from cobble.router.cost_settings import (
    MAX_MULTIPLIER,
    MAX_PRICE_KWH_USD,
    MAX_WATTS,
    CostSettings,
)


class CostSettingsStore(Protocol):
    def get(self) -> CostSettings: ...
    def put(self, values: CostSettings) -> None: ...


class DbCostSettings:
    """The settings as the core stores them (`platform_state`)."""

    def __init__(self, settings: Settings) -> None:
        from cobble.db import make_engine, make_session_factory

        self._sessions = make_session_factory(make_engine(settings.database_url))

    def get(self) -> CostSettings:
        from cobble.router import cost_settings

        with self._sessions() as session:
            return cost_settings.read(session)

    def put(self, values: CostSettings) -> None:
        from cobble.router import cost_settings

        with self._sessions() as session:
            cost_settings.write(session, values)


def add_parser(sub: Any) -> None:
    costs = sub.add_parser("costs", help="electricity of local models and the per-task cap")
    costs.add_argument("--electricity-price", help="USD per kWh (0 or empty: off)")
    costs.add_argument("--power-watts", help="the machine's draw while a local model generates")
    costs.add_argument(
        "--electricity-in-budget",
        choices=("yes", "no"),
        help="count the estimated electricity in the project's spend and budget",
    )
    costs.add_argument(
        "--task-multiplier", help="a task may spend this multiple of its estimate (0: no cap)"
    )


def _parse(text: str, low: Decimal, high: Decimal) -> Decimal | None:
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() and low <= value <= high else None


def _show(values: CostSettings, settings: Settings, lang: str, say: Any) -> None:
    price = values.electricity_price_kwh_usd
    watts = values.electricity_watts
    if values.electricity_enabled:
        say(t("cli.costs.electricity", lang, price=price, watts=watts))
        say(
            t(
                "cli.costs.counted" if values.electricity_counts_in_budget else "cli.costs.apart",
                lang,
            )
        )
        say(t("cli.costs.estimate", lang))
    else:
        say(t("cli.costs.electricity_off", lang))
    factor = task_budget.multiplier(values, settings)
    if factor > 0:
        say(
            t(
                "cli.costs.task_cap",
                lang,
                factor=factor.normalize(),
                floor=settings.task_budget_floor_usd,
            )
        )
    else:
        say(t("cli.costs.task_cap_off", lang))


def run(
    args: argparse.Namespace, settings: Settings, *, store: CostSettingsStore | None = None
) -> int:
    lang = settings.lang
    store = store or DbCostSettings(settings)
    values = store.get()
    changes: dict[str, Any] = {}
    if args.electricity_price is not None:
        price = _parse(args.electricity_price or "0", Decimal(0), MAX_PRICE_KWH_USD)
        if price is None:
            print(t("cli.costs.invalid", lang, name="--electricity-price"))
            return 2
        changes["electricity_price_kwh_usd"] = price
    if args.power_watts is not None:
        watts = _parse(args.power_watts or "0", Decimal(0), Decimal(MAX_WATTS))
        if watts is None or watts != watts.to_integral_value():
            print(t("cli.costs.invalid", lang, name="--power-watts"))
            return 2
        changes["electricity_watts"] = int(watts)
    if args.electricity_in_budget is not None:
        changes["electricity_counts_in_budget"] = args.electricity_in_budget == "yes"
    if args.task_multiplier is not None:
        factor = _parse(args.task_multiplier, Decimal(0), MAX_MULTIPLIER)
        if factor is None:
            print(t("cli.costs.invalid", lang, name="--task-multiplier"))
            return 2
        changes["task_budget_multiplier"] = factor
    if changes:
        values = CostSettings(**{**values.__dict__, **changes})
        store.put(values)
    _show(values, settings, lang, print)
    return 0
