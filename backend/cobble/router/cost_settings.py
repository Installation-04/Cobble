"""Owner settings of the cost router: electricity of local models and the per-task cap (ADR 0021).

Stored in the single `platform_state` row, like the model routes. Nothing here is a secret.
Electricity is an *estimate*: watts x seconds of the call / 3.6e6 x price per kWh. It is not
measured: the machine's real draw varies with the model, the load and the hardware.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from cobble.db.models import PlatformState

log = logging.getLogger(__name__)

JOULES_PER_KWH = Decimal("3600000")
MAX_WATTS = 5000  # a whole workstation under load; anything above is a typo
MAX_PRICE_KWH_USD = Decimal("10")
MAX_MULTIPLIER = Decimal("1000")


@dataclass(frozen=True)
class CostSettings:
    electricity_price_kwh_usd: Decimal | None = None
    electricity_watts: int | None = None
    electricity_counts_in_budget: bool = False
    task_budget_multiplier: Decimal | None = None  # None: the configured default

    @property
    def electricity_enabled(self) -> bool:
        return bool(
            self.electricity_watts
            and self.electricity_price_kwh_usd
            and self.electricity_price_kwh_usd > 0
        )


def electricity_cost(watts: int, price_kwh_usd: Decimal, seconds: Decimal) -> Decimal:
    """USD for `watts` drawn during `seconds` at `price_kwh_usd` per kWh."""
    return Decimal(watts) * seconds / JOULES_PER_KWH * price_kwh_usd


def read(session: Session) -> CostSettings:
    state = session.get(PlatformState, 1)
    if state is None:
        return CostSettings()
    return CostSettings(
        electricity_price_kwh_usd=(
            Decimal(state.electricity_price_kwh_usd)
            if state.electricity_price_kwh_usd is not None
            else None
        ),
        electricity_watts=state.electricity_watts,
        electricity_counts_in_budget=bool(state.electricity_counts_in_budget),
        task_budget_multiplier=(
            Decimal(state.task_budget_multiplier)
            if state.task_budget_multiplier is not None
            else None
        ),
    )


def write(session: Session, values: CostSettings) -> None:
    state = session.get(PlatformState, 1)
    if state is None:
        state = PlatformState(id=1)
        session.add(state)
    state.electricity_price_kwh_usd = values.electricity_price_kwh_usd
    state.electricity_watts = values.electricity_watts
    state.electricity_counts_in_budget = values.electricity_counts_in_budget
    state.task_budget_multiplier = values.task_budget_multiplier
    session.commit()


class ElectricityMeter:
    """Estimates the electricity of one call to a model served on this machine.

    Read at each call (so a change applies at once); a database hiccup means "no electricity",
    never a failed call."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        local_models: Callable[[], set[str]] | None,
    ) -> None:
        self._sessions = sessions
        self._local_models = local_models

    def __call__(self, models: tuple[str, ...], seconds: Decimal) -> Decimal | None:
        """The estimate for a call that took `seconds`, or None (not local, or not configured)."""
        if self._local_models is None:
            return None
        try:
            with self._sessions() as session:
                values = read(session)
        except SQLAlchemyError:
            log.warning("cannot read the electricity settings", exc_info=True)
            return None
        watts, price = values.electricity_watts, values.electricity_price_kwh_usd
        if not values.electricity_enabled or not watts or price is None:
            return None
        if not any(m in self._local_models() for m in models):
            return None
        return electricity_cost(watts, price, seconds)
