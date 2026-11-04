"""End-of-project report (ADR 0014): what was built, how long it took and what it cost.

Everything comes from grouped queries (one for the tasks, one for the milestones, plus the
three of `costs.project_costs` and the plan estimate); no loop over tasks or calls issues a
query.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from cobble import costs
from cobble.db import Milestone, Project, Task
from cobble.i18n import t
from cobble.router.prices import Prices
from cobble.scheduler.rules import ref_key

DONE = "merged"
FAILED = "failed"


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _percent(part: Decimal, whole: Decimal) -> int | None:
    if whole <= 0:
        return None
    return int((part / whole * 100).to_integral_value())


def project_report(
    session: Session, project: Project, reference: tuple[str, Prices] | None = None
) -> dict[str, Any]:
    """The `GET /projects/{id}/report` body."""
    spend = costs.project_costs(session, project, reference)

    task_rows = session.execute(
        select(
            Task.milestone,
            Task.state,
            func.count(Task.id),
            func.coalesce(func.sum(case((Task.escalated.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(Task.attempts), 0),
            func.max(Task.updated_at),
        )
        .where(Task.project_id == project.id)
        .group_by(Task.milestone, Task.state)
    ).all()
    milestone_rows = session.scalars(
        select(Milestone).where(Milestone.project_id == project.id)
    ).all()

    per_milestone: dict[str, dict[str, int]] = {}
    totals = {"total": 0, "done": 0, "failed": 0, "escalated": 0, "attempts": 0}
    last: datetime | None = None
    for milestone, state, count, escalated, attempts, updated in task_rows:
        bucket = per_milestone.setdefault(milestone, {"total": 0, "done": 0, "failed": 0})
        bucket["total"] += int(count)
        totals["total"] += int(count)
        totals["escalated"] += int(escalated)
        totals["attempts"] += int(attempts)
        if state == DONE:
            bucket["done"] += int(count)
            totals["done"] += int(count)
        elif state == FAILED:
            bucket["failed"] += int(count)
            totals["failed"] += int(count)
        updated_u = _utc(updated)
        if updated_u is not None and (last is None or updated_u > last):
            last = updated_u

    milestones = []
    for m in sorted(milestone_rows, key=lambda m: ref_key(m.ref)):
        found = per_milestone.get(m.ref, {"total": 0, "done": 0, "failed": 0})
        validated = _utc(m.validated_at)
        if validated is not None and (last is None or validated > last):
            last = validated
        milestones.append(
            {
                "ref": m.ref,
                "title": m.title,
                "status": m.status,
                "validated_at": _iso(validated),
                "tasks_total": found["total"],
                "tasks_done": found["done"],
                "tasks_failed": found["failed"],
                "explanation": m.explanation,  # explain mode (ADR 0017), else null
            }
        )

    started = _utc(project.created_at)
    duration = (
        int((last - started).total_seconds()) if started and last and last >= started else None
    )

    spent = Decimal(spend["spent_usd"])
    budget = Decimal(spend["budget_usd"]) if spend["budget_usd"] is not None else None
    estimate = Decimal(spend["estimate_usd"]) if spend["estimate_usd"] is not None else None
    return {
        "project": {
            "id": str(project.id),
            "name": project.name,
            "phase": project.phase,
            "status": project.status,
            "finished": project.phase == "done",
        },
        "span": {
            "started_at": _iso(started),
            "ended_at": _iso(last),
            "duration_seconds": duration,
        },
        "build": {
            "milestones": milestones,
            "milestones_validated": sum(1 for m in milestones if m["status"] == "validated"),
            "tasks": totals,
        },
        "costs": {
            "spent_usd": spend["spent_usd"],
            "budget_usd": spend["budget_usd"],
            "estimate_usd": spend["estimate_usd"],
            "budget_used_percent": _percent(spent, budget) if budget is not None else None,
            "estimate_delta_percent": (
                _percent(spent - estimate, estimate) if estimate is not None else None
            ),
            "tokens": spend["tokens"],
            "savings": spend["savings"],
            "by_model": spend["by_model"],
            "by_role": spend["by_role"],
            "fallbacks": spend["fallbacks"],
        },
    }


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _duration(seconds: int | None, lang: str) -> str:
    if seconds is None:
        return t("report.na", lang)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return t("report.duration.days", lang, days=days, hours=hours)
    if hours:
        return t("report.duration.hours", lang, hours=hours, minutes=minutes)
    return t("report.duration.minutes", lang, minutes=minutes)


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return out


def _spend_table(first: str, rows: list[dict[str, Any]], key: str, lang: str) -> list[str]:
    return _table(
        [
            first,
            t("report.col.calls", lang),
            t("report.col.tokens_in", lang),
            t("report.col.tokens_out", lang),
            t("report.col.cost", lang),
        ],
        [
            [
                r[key] or t("report.unknown", lang),
                r["calls"],
                r["prompt_tokens"],
                r["completion_tokens"],
                f"${r['cost_usd']}",
            ]
            for r in rows
        ],
    )


def render_markdown(report: dict[str, Any], lang: str) -> str:
    """The report as a Markdown document in `lang` (fr or en; anything else falls back to en)."""
    na = t("report.na", lang)
    project, span, build, spend = (
        report["project"],
        report["span"],
        report["build"],
        report["costs"],
    )
    tasks = build["tasks"]
    state = "report.state.finished" if project["finished"] else "report.state.ongoing"
    out = [f"# {t('report.title', lang, name=project['name'])}", "", t(state, lang)]

    out += ["", f"## {t('report.built.title', lang)}", ""]
    out.append(
        t(
            "report.built.summary",
            lang,
            validated=build["milestones_validated"],
            milestones=len(build["milestones"]),
            done=tasks["done"],
            total=tasks["total"],
            failed=tasks["failed"],
            escalated=tasks["escalated"],
        )
    )
    if build["milestones"]:
        out.append("")
        out += _table(
            [
                t("report.col.milestone", lang),
                t("report.col.status", lang),
                t("report.col.tasks", lang),
                t("report.col.failed", lang),
            ],
            [
                [
                    f"{m['ref']} {m['title']}",
                    t(f"report.milestone_status.{m['status']}", lang),
                    f"{m['tasks_done']}/{m['tasks_total']}",
                    m["tasks_failed"],
                ]
                for m in build["milestones"]
            ],
        )

    explained = [m for m in build["milestones"] if m["explanation"]]
    if explained:
        out += ["", f"## {t('report.explain.title', lang)}", ""]
        for m in explained:
            out += [f"### {m['ref']} {m['title']}", "", m["explanation"], ""]
        out.pop()

    out += ["", f"## {t('report.time.title', lang)}", ""]
    out.append(f"- {t('report.time.started', lang)}: {span['started_at'] or na}")
    out.append(f"- {t('report.time.ended', lang)}: {span['ended_at'] or na}")
    out.append(f"- {t('report.time.duration', lang)}: {_duration(span['duration_seconds'], lang)}")

    out += ["", f"## {t('report.costs.title', lang)}", ""]
    out.append(f"- {t('report.costs.spent', lang)}: ${spend['spent_usd']}")
    budget = (
        f"${spend['budget_usd']}"
        if spend["budget_usd"] is not None
        else t("report.costs.no_budget", lang)
    )
    if spend["budget_used_percent"] is not None:
        budget += f" ({spend['budget_used_percent']} %)"
    out.append(f"- {t('report.costs.budget', lang)}: {budget}")
    estimate = f"${spend['estimate_usd']}" if spend["estimate_usd"] is not None else na
    if spend["estimate_delta_percent"] is not None:
        estimate += f" ({spend['estimate_delta_percent']:+d} %)"
    out.append(f"- {t('report.costs.estimate', lang)}: {estimate}")
    tokens = spend["tokens"]
    split = t(
        "report.costs.tokens_split", lang, prompt=tokens["prompt"], completion=tokens["completion"]
    )
    out.append(f"- {t('report.costs.tokens', lang)}: {split}")

    out += ["", f"## {t('report.savings.title', lang)}", ""]
    saving = spend["savings"]
    if saving is None:
        out.append(t("report.savings.unavailable", lang))
    else:
        lost = saving["saved_usd"].startswith("-")
        out.append(
            t(
                "report.savings.none" if lost else "report.savings.saved",
                lang,
                amount=f"${saving['saved_usd']}",
                percent=saving["saved_percent"],
                model=saving["reference_model"],
            )
        )
        out.append("")
        out.append(
            t(
                "report.savings.detail",
                lang,
                model=saving["reference_model"],
                reference=f"${saving['reference_cost_usd']}",
                actual=f"${saving['actual_cost_usd']}",
            )
        )

    out += ["", f"## {t('report.by_model.title', lang)}", ""]
    out += _spend_table(t("report.col.model", lang), spend["by_model"], "model", lang)
    out += ["", f"## {t('report.by_role.title', lang)}", ""]
    out += _spend_table(t("report.col.role", lang), spend["by_role"], "role", lang)

    out += ["", f"## {t('report.fallbacks.title', lang)}", ""]
    fb = spend["fallbacks"]
    out.append(t("report.fallbacks.summary", lang, calls=fb["calls"], total=fb["total_calls"]))
    if fb["by_model"]:
        out.append("")
        out += _table(
            [
                t("report.col.answered_by", lang),
                t("report.col.instead_of", lang),
                t("report.col.calls", lang),
                t("report.col.cost", lang),
            ],
            [
                [
                    r["model"],
                    r["fallback_from"] or t("report.unknown", lang),
                    r["calls"],
                    f"${r['cost_usd']}",
                ]
                for r in fb["by_model"]
            ],
        )
    return "\n".join(out) + "\n"


def filename(project_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-") or "project"
    return f"cobble-report-{slug[:60]}.md"
