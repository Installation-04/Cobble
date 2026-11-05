"""Aggregate the results of a bench run and write the JSON and Markdown (FR/EN) reports.

The v0.3 criterion is read straight from the summary: `success_rate` and `avg_cost_usd` are the
two published figures, `budget.respected` is "no agent exceeds its budget".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from .runner import SKIPPED, ProjectResult

SCHEMA_VERSION = 1
LANGS = ("fr", "en")

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "title": "Agent bench report",
        "dry": "DRY RUN: the numbers below are invented by a simulator. This is not a measurement and must not be published.",
        "run": "Run",
        "mode": "Mode",
        "mode_real": "real models",
        "mode_dry": "dry run (no model, no cost)",
        "when": "Started",
        "preset": "Preset",
        "routes": "Models by role",
        "label": "Label",
        "summary": "Summary",
        "success": "Success rate",
        "avg_cost": "Average cost per project",
        "avg_cost_ok": "Average cost per successful project",
        "total_cost": "Total cost",
        "tokens": "Tokens (prompt / completion)",
        "duration": "Average duration",
        "escalations": "Escalated tasks",
        "fallbacks": "Fallback calls",
        "budget": "Budget",
        "budget_ok": "No project exceeded its budget",
        "budget_ko": "BUDGET EXCEEDED by: {names}",
        "budget_ko_total": "BUDGET EXCEEDED: the total spent is above the total budget",
        "budget_total": "Total spent {spent} of {total}",
        "projects": "Projects",
        "col_project": "Project",
        "col_outcome": "Outcome",
        "col_tests": "Hidden tests",
        "col_cost": "Cost / cap",
        "col_tokens": "Tokens in / out",
        "col_duration": "Duration",
        "col_esc": "Escal.",
        "col_fb": "Fallb.",
        "details": "Details",
        "none": "none",
        "na": "n/a",
        "min": "min",
        "outcome.success": "success",
        "outcome.tests_failed": "hidden tests failed",
        "outcome.build_failed": "build failed",
        "outcome.budget_paused": "stopped by budget",
        "outcome.timeout": "timeout",
        "outcome.error": "error",
        "outcome.skipped": "skipped",
        "failed_tests": "Hidden tests that failed",
    },
    "fr": {
        "title": "Rapport du banc d'essai des agents",
        "dry": "SIMULATION: les chiffres ci-dessous sont inventés par un simulateur. Ce n'est pas une mesure et il ne faut pas la publier.",
        "run": "Exécution",
        "mode": "Mode",
        "mode_real": "vrais modèles",
        "mode_dry": "simulation (aucun modèle, aucun coût)",
        "when": "Début",
        "preset": "Préréglage",
        "routes": "Modèles par rôle",
        "label": "Étiquette",
        "summary": "Synthèse",
        "success": "Taux de réussite",
        "avg_cost": "Coût moyen par projet",
        "avg_cost_ok": "Coût moyen par projet réussi",
        "total_cost": "Coût total",
        "tokens": "Jetons (entrée / sortie)",
        "duration": "Durée moyenne",
        "escalations": "Tâches escaladées",
        "fallbacks": "Appels de repli",
        "budget": "Budget",
        "budget_ok": "Aucun projet n'a dépassé son budget",
        "budget_ko": "BUDGET DÉPASSÉ par: {names}",
        "budget_ko_total": "BUDGET DÉPASSÉ: le total dépensé dépasse le budget total",
        "budget_total": "Total dépensé {spent} sur {total}",
        "projects": "Projets",
        "col_project": "Projet",
        "col_outcome": "Résultat",
        "col_tests": "Tests cachés",
        "col_cost": "Coût / plafond",
        "col_tokens": "Jetons ent. / sort.",
        "col_duration": "Durée",
        "col_esc": "Escal.",
        "col_fb": "Repli",
        "details": "Détails",
        "none": "aucun",
        "na": "s. o.",
        "min": "min",
        "outcome.success": "réussi",
        "outcome.tests_failed": "tests cachés en échec",
        "outcome.build_failed": "construction en échec",
        "outcome.budget_paused": "arrêté par le budget",
        "outcome.timeout": "délai dépassé",
        "outcome.error": "erreur",
        "outcome.skipped": "ignoré",
        "failed_tests": "Tests cachés en échec",
    },
}


@dataclass
class Summary:
    attempted: int
    successes: int
    success_rate: float
    avg_cost_usd: Decimal
    avg_cost_success_usd: Decimal | None
    total_cost_usd: Decimal
    prompt_tokens: int
    completion_tokens: int
    avg_duration_s: float
    escalated_tasks: int
    fallback_calls: int
    over_budget: list[str]
    total_budget_usd: Decimal

    @property
    def budget_respected(self) -> bool:
        return not self.over_budget and self.total_cost_usd <= self.total_budget_usd


def summarize(results: list[ProjectResult], total_budget_usd: Decimal) -> Summary:
    ran = [r for r in results if r.outcome != SKIPPED]
    won = [r for r in ran if r.success]
    total = sum((r.spent_usd for r in ran), Decimal(0))
    return Summary(
        attempted=len(ran),
        successes=len(won),
        success_rate=len(won) / len(ran) if ran else 0.0,
        avg_cost_usd=total / len(ran) if ran else Decimal(0),
        avg_cost_success_usd=(sum((r.spent_usd for r in won), Decimal(0)) / len(won))
        if won
        else None,
        total_cost_usd=total,
        prompt_tokens=sum(r.prompt_tokens for r in ran),
        completion_tokens=sum(r.completion_tokens for r in ran),
        avg_duration_s=sum(r.duration_s for r in ran) / len(ran) if ran else 0.0,
        escalated_tasks=sum(r.escalated_tasks for r in ran),
        fallback_calls=sum(r.fallback_calls for r in ran),
        over_budget=[r.name for r in ran if not r.within_budget],
        total_budget_usd=total_budget_usd,
    )


def _usd(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.4f}"


def build_report(
    results: list[ProjectResult], summary: Summary, meta: dict[str, Any]
) -> dict[str, Any]:
    """The JSON document (`schema_version` 1). Money is a string, never a float."""
    return {
        "schema_version": SCHEMA_VERSION,
        **meta,
        "summary": {
            "attempted": summary.attempted,
            "successes": summary.successes,
            "success_rate": round(summary.success_rate, 4),
            "avg_cost_usd": _usd(summary.avg_cost_usd),
            "avg_cost_success_usd": _usd(summary.avg_cost_success_usd),
            "total_cost_usd": _usd(summary.total_cost_usd),
            "prompt_tokens": summary.prompt_tokens,
            "completion_tokens": summary.completion_tokens,
            "avg_duration_s": round(summary.avg_duration_s, 1),
            "escalated_tasks": summary.escalated_tasks,
            "fallback_calls": summary.fallback_calls,
            "budget": {
                "respected": summary.budget_respected,
                "over_budget": summary.over_budget,
                "total_budget_usd": _usd(summary.total_budget_usd),
            },
        },
        "projects": [
            {
                "name": r.name,
                "outcome": r.outcome,
                "detail": r.detail,
                "cap_usd": _usd(r.cap_usd),
                "spent_usd": _usd(r.spent_usd),
                "estimate_usd": _usd(r.estimate_usd),
                "within_budget": r.within_budget,
                "max_task_cost_usd": _usd(r.max_task_cost_usd),
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "calls": r.calls,
                "fallback_calls": r.fallback_calls,
                "escalated_tasks": r.escalated_tasks,
                "attempts": r.attempts,
                "tasks_total": r.tasks_total,
                "tasks_merged": r.tasks_merged,
                "duration_s": round(r.duration_s, 1),
                "hidden_tests": {
                    "passed": r.hidden_passed,
                    "total": r.hidden_total,
                    "failed": r.hidden_failed,
                },
                "cost_by_model": r.by_model,
            }
            for r in results
        ],
    }


def _minutes(seconds: float, t: dict[str, str]) -> str:
    return f"{seconds / 60:.1f} {t['min']}"


def _budget_line(budget: dict[str, Any], t: dict[str, str]) -> str:
    if budget["over_budget"]:
        return t["budget_ko"].format(names=", ".join(budget["over_budget"]))
    return t["budget_ok"] if budget["respected"] else t["budget_ko_total"]


def render_markdown(report: dict[str, Any], lang: str) -> str:
    """The report as a Markdown page in `lang` (fr or en), ready to publish."""
    t = TEXT[lang if lang in TEXT else "en"]
    s = report["summary"]
    lines = [f"# {t['title']}", ""]
    if report["mode"] == "dry-run":
        lines += [f"> **{t['dry']}**", ""]
    routes = report.get("routes") or {}
    lines += [
        f"- {t['run']}: `{report['run_id']}`",
        f"- {t['mode']}: {t['mode_dry'] if report['mode'] == 'dry-run' else t['mode_real']}",
        f"- {t['when']}: {report['started_at']}",
    ]
    if report.get("label"):
        lines.append(f"- {t['label']}: {report['label']}")
    if report.get("preset"):
        lines.append(f"- {t['preset']}: `{report['preset']}`")
    if routes:
        lines.append(
            f"- {t['routes']}: " + "; ".join(f"{k} = {', '.join(v)}" for k, v in routes.items())
        )
    budget = s["budget"]
    lines += [
        "",
        f"## {t['summary']}",
        "",
        f"- **{t['success']}: {s['success_rate'] * 100:.0f} % ({s['successes']}/{s['attempted']})**",
        f"- **{t['avg_cost']}: ${s['avg_cost_usd']}**",
        f"- {t['avg_cost_ok']}: {'$' + s['avg_cost_success_usd'] if s['avg_cost_success_usd'] else t['na']}",
        f"- {t['total_cost']}: ${s['total_cost_usd']}",
        f"- {t['tokens']}: {s['prompt_tokens']:,} / {s['completion_tokens']:,}",
        f"- {t['duration']}: {_minutes(s['avg_duration_s'], t)}",
        f"- {t['escalations']}: {s['escalated_tasks']}",
        f"- {t['fallbacks']}: {s['fallback_calls']}",
        "",
        f"## {t['budget']}",
        "",
        "- " + _budget_line(budget, t),
        "- "
        + t["budget_total"].format(
            spent=f"${s['total_cost_usd']}", total=f"${budget['total_budget_usd']}"
        ),
        "",
        f"## {t['projects']}",
        "",
        f"| {t['col_project']} | {t['col_outcome']} | {t['col_tests']} | {t['col_cost']} | {t['col_tokens']} | {t['col_duration']} | {t['col_esc']} | {t['col_fb']} |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for p in report["projects"]:
        tests = p["hidden_tests"]
        lines.append(
            f"| {p['name']} | {t['outcome.' + p['outcome']]} "
            f"| {tests['passed']}/{tests['total']} "
            f"| ${p['spent_usd']} / ${p['cap_usd']}{'' if p['within_budget'] else ' !'} "
            f"| {p['prompt_tokens']:,} / {p['completion_tokens']:,} "
            f"| {_minutes(p['duration_s'], t)} | {p['escalated_tasks']} | {p['fallback_calls']} |"
        )
    detailed = [p for p in report["projects"] if p["detail"] or p["hidden_tests"]["failed"]]
    if detailed:
        lines += ["", f"## {t['details']}", ""]
        for p in detailed:
            lines.append(f"- **{p['name']}**: {p['detail'] or t['none']}")
            for name in p["hidden_tests"]["failed"][:10]:
                lines.append(f"  - {t['failed_tests']}: `{name}`")
    return "\n".join(lines) + "\n"


def new_run_id(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")


def write_report(results_dir: Path, report: dict[str, Any]) -> list[Path]:
    """Write `report.json`, `report.fr.md` and `report.en.md` in `<results_dir>/<run_id>/`."""
    folder = results_dir / report["run_id"]
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / "report.json"]
    paths[0].write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", "utf-8")
    for lang in LANGS:
        path = folder / f"report.{lang}.md"
        path.write_text(render_markdown(report, lang), "utf-8")
        paths.append(path)
    return paths
