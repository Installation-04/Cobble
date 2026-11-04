"""Stores benchmark results and says which model looks best for the `worker` role."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cobble.db import ModelBenchmark

from .runner import BenchmarkResult

# Below this share of cases passed, a model is not proposed for the worker role at all.
MIN_QUALITY = Decimal("0.5")
# Models within this much quality of the best are "as good": the faster one wins.
QUALITY_MARGIN = Decimal("0.05")


def store(sessions: sessionmaker[Session], result: BenchmarkResult) -> None:
    with sessions() as session:
        session.add(
            ModelBenchmark(
                id=uuid.uuid4(),
                model=result.model,
                version=result.version,
                quality=Decimal(str(round(result.quality, 4))),
                seconds=Decimal(str(round(result.seconds, 2))),
                tokens_per_second=(
                    Decimal(str(round(result.tokens_per_second, 2)))
                    if result.tokens_per_second is not None
                    else None
                ),
                outcomes=[
                    {
                        "task": o.task,
                        "passed": o.passed,
                        "total": o.total,
                        "error": o.error,
                        "seconds": round(o.seconds, 2),
                    }
                    for o in result.outcomes
                ],
            )
        )
        session.commit()


def latest(sessions: sessionmaker[Session], version: int | None = None) -> list[ModelBenchmark]:
    """The most recent run of each model (of task-set `version` when given), best first."""
    with sessions() as session:
        rows = list(
            session.scalars(select(ModelBenchmark).order_by(ModelBenchmark.created_at.desc()))
        )
    seen: dict[str, ModelBenchmark] = {}
    for row in rows:
        if version is not None and row.version != version:
            continue
        seen.setdefault(row.model, row)
    return sorted(
        seen.values(),
        key=lambda r: (-r.quality, -(r.tokens_per_second or Decimal(0)), r.model),
    )


def best_worker(results: list[ModelBenchmark]) -> str | None:
    """The model to propose for `worker`: among those within a small margin of the best
    quality, the fastest. None when nothing reaches the minimum quality."""
    good = [r for r in results if r.quality >= MIN_QUALITY]
    if not good:
        return None
    top = max(r.quality for r in good)
    close = [r for r in good if top - r.quality <= QUALITY_MARGIN]
    return max(close, key=lambda r: (r.tokens_per_second or Decimal(0), r.quality, r.model)).model
