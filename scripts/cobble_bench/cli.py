"""Command line of the agent bench (`make bench`, `scripts/bench.py`).

A real run spends money with real models, so it never starts by accident: it needs the explicit
`--yes-real-models` flag (or `COBBLE_BENCH_REAL_MODELS=yes`), credentials, and a model
connection that is not the development fake. Every refusal is printed in French and English.
`--dry-run` replaces the platform with an in-memory simulator: no network, no model, no cost.
"""

from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from . import projects as refs
from .api import ApiError, CobbleApi, HttpCobble
from .fake import FakeCobble, SolutionFetcher
from .fetch import DirFetcher, GitFetcher
from .hidden import HiddenError
from .report import build_report, new_run_id, summarize, write_report
from .runner import BenchConfig, BenchRunner, Fetcher
from .validate import validate

RESULTS_DIR = refs.PROJECTS_DIR / "results"
REAL_PYTHON = ["uv", "run", "--quiet", "--project", "{code}", "python"]
EXIT_OK, EXIT_BUDGET, EXIT_USAGE = 0, 1, 2

MESSAGES: dict[str, tuple[str, str]] = {
    "need_confirm": (
        "Refus: `make bench` appelle de vrais modèles et dépense de l'argent (jusqu'à {total} $ ici). "
        "Relancez avec --yes-real-models (ou COBBLE_BENCH_REAL_MODELS=yes) pour confirmer. "
        "Pour tester le banc sans rien dépenser: make bench-dry-run.",
        "Refused: `make bench` calls real models and spends money (up to ${total} here). "
        "Run again with --yes-real-models (or COBBLE_BENCH_REAL_MODELS=yes) to confirm. "
        "To test the bench without spending anything: make bench-dry-run.",
    ),
    "need_credentials": (
        "Refus: identifiants manquants. Définissez COBBLE_BENCH_EMAIL et COBBLE_BENCH_PASSWORD "
        "(compte administrateur de l'instance) et, au besoin, COBBLE_BENCH_URL.",
        "Refused: missing credentials. Set COBBLE_BENCH_EMAIL and COBBLE_BENCH_PASSWORD "
        "(the instance's admin account) and, if needed, COBBLE_BENCH_URL.",
    ),
    "unreachable": (
        "Refus: impossible de se connecter à {url} (état {status}). Vérifiez l'adresse, le compte et que `make dev` ou l'instance tourne.",
        "Refused: cannot sign in to {url} (status {status}). Check the address, the account and that `make dev` or the instance is running.",
    ),
    "no_model": (
        "Refus: aucune connexion à un vrai modèle n'est configurée (rôles sans modèle ou modèle `fake`: {roles}). "
        "Ajoutez une connexion dans Paramètres > Modèles, puis appliquez un préréglage (--preset balanced ou economical-local).",
        "Refused: no connection to a real model is configured (roles with no model or with the `fake` model: {roles}). "
        "Add a connection in Settings > Models, then apply a preset (--preset balanced or economical-local).",
    ),
    "no_code_source": (
        "Refus: sans source du code généré, les tests cachés ne peuvent pas tourner. Donnez --git-url-template "
        "(COBBLE_BENCH_GIT_URL, avec {{repo}}) et COBBLE_BENCH_GIT_TOKEN, ou --code-dir.",
        "Refused: without a source for the generated code the hidden tests cannot run. Give --git-url-template "
        "(COBBLE_BENCH_GIT_URL, containing {{repo}}) and COBBLE_BENCH_GIT_TOKEN, or --code-dir.",
    ),
    "bad_args": ("Erreur: {detail}", "Error: {detail}"),
    "no_fastapi": (
        "Le mode simulation et la validation ont besoin de fastapi et de pytest: utilisez make bench-dry-run (ou make bench-check).",
        "The dry run and the validation need fastapi and pytest: use make bench-dry-run (or make bench-check).",
    ),
    "plan": (
        "Banc d'essai: {count} projet(s), plafond par projet {cap}, budget total {total} $.",
        "Bench: {count} project(s), per-project cap {cap}, total budget ${total}.",
    ),
    "done": (
        "Terminé. Rapports: {paths}",
        "Done. Reports: {paths}",
    ),
    "budget_violation": (
        "ATTENTION: budget dépassé par {names}. Le critère « aucun agent ne dépasse son budget » n'est pas rempli.",
        'WARNING: budget exceeded by {names}. The criterion "no agent exceeds its budget" is not met.',
    ),
}


def bilingual(key: str, **values: Any) -> str:
    fr, en = MESSAGES[key]
    return f"{fr.format(**values)}\n{en.format(**values)}"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bench",
        description="Agent bench: reference projects, hidden tests, cost and success report.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="list the reference projects")
    mode.add_argument(
        "--validate-solutions",
        action="store_true",
        help="check hidden tests against the reference solutions and their mutations (no model)",
    )
    mode.add_argument(
        "--dry-run", action="store_true", help="simulate the platform: no model, no cost"
    )
    p.add_argument(
        "--yes-real-models",
        action="store_true",
        help="confirm that real models will be used and paid",
    )
    p.add_argument("--projects", help="comma-separated reference projects (default: all)")
    p.add_argument(
        "--base-url", default=os.environ.get("COBBLE_BENCH_URL", "http://localhost:8080")
    )
    p.add_argument(
        "--git-url-template",
        default=os.environ.get("COBBLE_BENCH_GIT_URL"),
        help="clone URL with {repo}",
    )
    p.add_argument(
        "--code-dir", type=Path, help="use <dir>/<project>/ instead of cloning (offline)"
    )
    p.add_argument("--preset", help="apply this model preset first (balanced, economical-local)")
    p.add_argument(
        "--slot",
        action="append",
        default=[],
        metavar="SLOT=MODEL",
        help="local|cheap|strong model for the preset",
    )
    p.add_argument("--lang", choices=("fr", "en"), default="en", help="language of the interview")
    p.add_argument("--cap", help="per-project budget cap in USD (default: each project's own)")
    p.add_argument("--total-budget", default="8.00", help="total budget of the run in USD")
    p.add_argument("--timeout-scale", type=float, default=1.0)
    p.add_argument("--poll-s", type=float, default=5.0)
    p.add_argument(
        "--label", default="", help="free text recorded in the report (version, preset...)"
    )
    p.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    p.add_argument(
        "--python", help="interpreter command for the hidden tests ({code} = project root)"
    )
    return p


def _decimal(text: str, name: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"{name}: not a number") from None
    if value <= 0:
        raise ValueError(f"{name}: must be positive")
    return value


def _has_fastapi() -> bool:
    try:
        import fastapi  # noqa: F401
        import httpx  # noqa: F401
        import pytest  # noqa: F401
    except ImportError:
        return False
    return True


def _fake_models(setup: dict[str, Any]) -> list[str]:
    """Roles whose chain is empty or reaches the development fake model."""
    roles = []
    for role, chain in (setup.get("effective") or {}).items():
        if not chain or any("fake" in str(model).lower() for model in chain):
            roles.append(role)
    return roles or ([] if setup.get("effective") else ["?"])


def main(
    argv: Sequence[str] | None = None,
    *,
    api_factory: Callable[[str], CobbleApi] = HttpCobble,
    out: Callable[[str], None] = print,
    sleep: Callable[[float], None] | None = None,
) -> int:
    args = parser().parse_args(argv)
    env = os.environ

    def fail(key: str, **values: Any) -> int:
        out(bilingual(key, **values))
        return EXIT_USAGE

    try:
        selected = [n.strip() for n in args.projects.split(",")] if args.projects else None
        chosen = refs.load_all(selected)
        total = _decimal(args.total_budget, "--total-budget")
        cap = _decimal(args.cap, "--cap") if args.cap else None
    except (refs.ProjectError, ValueError) as exc:
        return fail("bad_args", detail=str(exc))

    if args.list:
        for p in chosen:
            out(f"{p.name}\t${p.budget_usd:.2f}\t{p.title['en']} / {p.title['fr']}")
        return EXIT_OK

    if args.validate_solutions:
        if not _has_fastapi():
            return fail("no_fastapi")
        bad = 0
        for p in chosen:
            try:
                verdict = validate(p, args.python.split() if args.python else None)
            except HiddenError as exc:
                out(f"{p.name}: ERROR {exc}")
                bad += 1
                continue
            caught = sum(m.caught for m in verdict.mutations)
            out(
                f"{p.name}: {'OK' if verdict.ok else 'FAIL'} "
                f"(solution {verdict.solution.passed}/{verdict.solution.total}, "
                f"empty template {verdict.empty_template.passed}/{verdict.empty_template.total}, "
                f"mutations caught {caught}/{len(verdict.mutations)})"
            )
            for m in verdict.mutations:
                if not m.caught:
                    out(f"  missed: {m.name} {m.problem or ''}".rstrip())
            bad += 0 if verdict.ok else 1
        return EXIT_OK if bad == 0 else EXIT_BUDGET

    dry = bool(args.dry_run)
    python: Sequence[str] | None = args.python.split() if args.python else None
    if dry:
        if not _has_fastapi():
            return fail("no_fastapi")
        cobble = FakeCobble()
        api: CobbleApi = cobble
        fetcher: Fetcher = SolutionFetcher(cobble)
        api.login("dry-run", "dry-run")
        python = python or [sys.executable]
    else:
        per_project = sum((cap or Decimal(str(p.budget_usd)) for p in chosen), Decimal(0))
        spend_limit = min(total, per_project)
        confirmed = args.yes_real_models or env.get("COBBLE_BENCH_REAL_MODELS") == "yes"
        if not confirmed:
            return fail("need_confirm", total=f"{spend_limit:.2f}")
        email, password = env.get("COBBLE_BENCH_EMAIL"), env.get("COBBLE_BENCH_PASSWORD")
        if not email or not password:
            return fail("need_credentials")
        if args.code_dir is not None:
            fetcher = DirFetcher(args.code_dir)
        elif args.git_url_template:
            fetcher = GitFetcher(args.git_url_template, env.get("COBBLE_BENCH_GIT_TOKEN"))
        else:
            return fail("no_code_source")
        api = api_factory(args.base_url)
        try:
            api.login(email, password)
            setup = api.model_setup()
            slots = dict(item.split("=", 1) for item in args.slot if "=" in item)
            if args.preset:
                api.apply_preset(args.preset, slots)
                setup = api.model_setup()
        except ApiError as exc:
            shown = urllib.parse.urlsplit(args.base_url)
            return fail(
                "unreachable",
                url=f"{shown.scheme}://{shown.hostname}:{shown.port or ''}".rstrip(":"),
                status=exc.status,
            )
        bad_roles = _fake_models(setup)
        if bad_roles:
            return fail("no_model", roles=", ".join(bad_roles))
        python = python or (REAL_PYTHON if not env.get("BENCH_PYTHON") else None)

    config = BenchConfig(
        lang=args.lang,
        per_project_cap_usd=cap,
        total_budget_usd=total,
        timeout_scale=args.timeout_scale,
        poll_s=0.0 if dry else args.poll_s,
        python=python,
    )
    run_id = ("dry-" if dry else "") + new_run_id()
    started = datetime.now(UTC)
    out(bilingual("plan", count=len(chosen), cap=f"${cap}" if cap else "per project", total=total))
    kwargs: dict[str, Any] = (
        {"sleep": sleep} if sleep else ({"sleep": lambda _: None} if dry else {})
    )
    runner = BenchRunner(api, fetcher, config, run_label=run_id, log=out, **kwargs)
    results = runner.run(chosen)
    summary = summarize(results, total)
    setup_now = {} if dry else api.model_setup()
    meta = {
        "run_id": run_id,
        "mode": "dry-run" if dry else "real",
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "label": args.label,
        "preset": args.preset,
        "routes": setup_now.get("effective", {}),
        "lang": args.lang,
        "host": urllib.parse.urlsplit(args.base_url).hostname if not dry else None,
    }
    report = build_report(results, summary, meta)
    paths = write_report(args.results_dir, report)
    out(bilingual("done", paths=", ".join(str(p) for p in paths)))
    if summary.over_budget or not summary.budget_respected:
        out(bilingual("budget_violation", names=", ".join(summary.over_budget) or "total"))
        return EXIT_BUDGET
    return EXIT_OK
