"""The agent bench: reference projects, hidden tests, runner, reports, CLI. No model, no money."""

from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cobble_bench import cli, projects, report, validate
from cobble_bench.fake import FakeCobble, Scenario, SolutionFetcher
from cobble_bench.fetch import GitFetcher
from cobble_bench.hidden import HiddenError, assert_unreachable, run_hidden
from cobble_bench.runner import (
    MESSAGE_LIMIT,
    BenchConfig,
    BenchRunner,
    interview_message,
)

ROOT = Path(__file__).resolve().parents[2]
NAMES = ["blog", "bot", "dashboard", "invoicing", "todo"]


# --- the reference projects ------------------------------------------------------------------


def test_there_are_five_reference_projects() -> None:
    assert projects.names() == NAMES


@pytest.mark.parametrize("name", NAMES)
def test_project_files_are_complete_and_bilingual(name: str) -> None:
    project = projects.load(name)
    for lang in ("fr", "en"):
        assert project.spec(lang).startswith("# ")
        assert len(interview_message(project, lang)) < MESSAGE_LIMIT
    assert (project.path / "README.md").is_file()
    assert list(project.hidden_dir.glob("test_hidden_*.py"))
    assert project.solution_tree.joinpath("app").is_dir()
    assert len(project.mutations()) >= 5
    assert set(project.config["measures"]) == {"fr", "en"}


@pytest.mark.parametrize("name", NAMES)
def test_specs_do_not_contain_test_code(name: str) -> None:
    project = projects.load(name)
    for lang in ("fr", "en"):
        text = project.spec(lang)
        assert "def test_" not in text and "TestClient" not in text and "assert " not in text


def test_hidden_tests_are_not_reachable_from_agent_workspaces() -> None:
    # Nothing mounts or copies the reference projects into a template, a runner or a module.
    for folder in ("core", "catalog", "runners", "services", "templates"):
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path.suffix in {".yml", ".yaml", ".json", ".sh", ".toml", ""}:
                if "node_modules" in path.parts or ".venv" in path.parts:
                    continue
                try:
                    assert "reference-projects" not in path.read_text("utf-8")
                except UnicodeDecodeError:
                    continue
    assert not list((ROOT / "templates").rglob("test_hidden_*"))


def test_the_guard_refuses_a_code_tree_holding_the_hidden_tests() -> None:
    project = projects.load("todo")
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp)
        validate.build_tree(project, tree)
        assert_unreachable(project, tree)
        (tree / "tests").mkdir(exist_ok=True)
        leaked = next(project.hidden_dir.glob("test_hidden_*.py"))
        (tree / "tests" / leaked.name).write_bytes(leaked.read_bytes())
        with pytest.raises(HiddenError):
            assert_unreachable(project, tree)
        with pytest.raises(HiddenError):
            assert_unreachable(project, project.path)


# --- hidden tests are satisfiable and discriminating ------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_the_reference_solution_passes_and_a_mutation_or_the_template_fails(name: str) -> None:
    project = projects.load(name)
    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "good"
        validate.build_tree(project, good)
        assert run_hidden(project, good).ok
        empty = Path(tmp) / "empty"
        validate.build_tree(project, empty, with_solution=False)
        assert not run_hidden(project, empty).ok
        broken = Path(tmp) / "broken"
        validate.build_tree(project, broken)
        mutation = project.mutations()[0]
        target = broken / mutation.file
        text = target.read_text("utf-8")
        assert text.count(mutation.old) == 1
        target.write_text(text.replace(mutation.old, mutation.new), "utf-8")
        assert not run_hidden(project, broken).ok


# --- the runner -------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(seconds, 1.0)


def run_bench(
    scenarios: dict[str, Scenario], names: list[str], **config: object
) -> tuple[FakeCobble, list]:  # type: ignore[type-arg]
    fake = FakeCobble(scenarios)
    clock = Clock()
    cfg = BenchConfig(poll_s=1.0, **config)  # type: ignore[arg-type]
    runner = BenchRunner(
        fake, SolutionFetcher(fake), cfg, run_label="t", sleep=clock.sleep, clock=clock
    )
    return fake, runner.run(projects.load_all(names))


def test_a_successful_project_is_measured() -> None:
    _, results = run_bench(
        {"todo": Scenario(cost_usd="0.25", fallback_calls=2, escalated_tasks=1)}, ["todo"]
    )
    (result,) = results
    assert result.outcome == "success"
    assert result.spent_usd == Decimal("0.25") and result.cap_usd == Decimal("1.0")
    assert result.hidden_total == result.hidden_passed > 0
    assert (result.prompt_tokens, result.fallback_calls, result.escalated_tasks) == (40_000, 2, 1)
    assert result.within_budget and result.tasks_merged == 3 and result.duration_s > 0


def test_the_budget_is_capped_on_the_project_and_the_idea_and_spec_are_sent() -> None:
    fake, _ = run_bench({}, ["bot"])
    state = next(iter(fake._projects.values()))
    assert state["budget"] == Decimal("1.50")
    sent = state["messages"][0]["content"]
    assert "# Simple chat bot" in sent  # the frozen spec is there
    assert projects.load("bot").idea["en"] in sent


def test_a_cap_override_applies_to_every_project() -> None:
    _, results = run_bench({}, ["todo", "bot"], per_project_cap_usd=Decimal("0.50"))
    assert [r.cap_usd for r in results] == [Decimal("0.50")] * 2


def test_a_failed_task_ends_the_project_without_success() -> None:
    _, (result,) = run_bench({"todo": Scenario(ends="failed")}, ["todo"])
    assert result.outcome == "build_failed" and "T-003" in result.detail


def test_the_budget_stopping_a_project_is_reported_and_respected() -> None:
    _, (result,) = run_bench({"todo": Scenario(ends="budget")}, ["todo"])
    assert result.outcome == "budget_paused"
    assert result.within_budget  # the platform stopped it at the cap, not above


def test_overspending_is_detected_as_a_budget_violation() -> None:
    _, (result,) = run_bench({"todo": Scenario(ends="overspend")}, ["todo"])
    assert result.outcome == "budget_paused" and not result.within_budget
    summary = report.summarize([result], Decimal("8"))
    assert summary.over_budget == ["todo"] and not summary.budget_respected


def test_a_build_that_never_ends_times_out() -> None:
    _, (result,) = run_bench({"todo": Scenario(ends="never")}, ["todo"], timeout_scale=0.01)
    assert result.outcome == "timeout"


def test_code_that_fails_the_hidden_tests_is_not_a_success() -> None:
    _, (result,) = run_bench({"todo": Scenario(broken_code=True)}, ["todo"])
    assert result.outcome == "tests_failed"
    assert result.hidden_passed < result.hidden_total and result.hidden_failed


def test_the_total_budget_skips_what_it_cannot_pay() -> None:
    _, results = run_bench(
        {"todo": Scenario(cost_usd="0.90")},
        ["todo", "bot", "blog"],
        total_budget_usd=Decimal("1.00"),
    )
    assert results[0].outcome == "success" and results[2].outcome == "skipped"
    assert results[1].cap_usd == Decimal("0.10")  # only what is left may be spent
    assert results[2].detail == "total_budget"


def test_an_api_error_does_not_stop_the_other_projects() -> None:
    fake = FakeCobble()
    original = fake.create_project
    calls = {"n": 0}

    def flaky(name: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            from cobble_bench.api import ApiError

            raise ApiError(503)
        return original(name)

    fake.create_project = flaky  # type: ignore[method-assign]
    clock = Clock()
    runner = BenchRunner(
        fake,
        SolutionFetcher(fake),
        BenchConfig(poll_s=1.0),
        run_label="t",
        sleep=clock.sleep,
        clock=clock,
    )
    results = runner.run(projects.load_all(["todo", "bot"]))
    assert [r.outcome for r in results] == ["error", "success"]
    assert results[0].detail == "api_503"


# --- reports ----------------------------------------------------------------------------------


def make_report(dry: bool) -> dict:  # type: ignore[type-arg]
    _, results = run_bench({"bot": Scenario(ends="failed")}, ["todo", "bot"])
    summary = report.summarize(results, Decimal("8"))
    meta = {"run_id": "r1", "mode": "dry-run" if dry else "real", "started_at": "2026-01-01T00:00:00Z",
            "label": "v0.3", "preset": "balanced", "routes": {"planner": ["m1"]}}  # fmt: skip
    return report.build_report(results, summary, meta)


def test_summary_figures() -> None:
    body = make_report(False)["summary"]
    assert (body["attempted"], body["successes"], body["success_rate"]) == (2, 1, 0.5)
    assert body["avg_cost_usd"] == "0.1200" and body["budget"]["respected"] is True


def test_markdown_reports_in_both_languages() -> None:
    body = make_report(False)
    en, fr = report.render_markdown(body, "en"), report.render_markdown(body, "fr")
    assert "Success rate: 50 % (1/2)" in en and "No project exceeded its budget" in en
    assert "Taux de réussite: 50 % (1/2)" in fr and "Aucun projet n'a dépassé son budget" in fr
    assert "DRY RUN" not in en
    assert "DRY RUN" in report.render_markdown(make_report(True), "en")
    assert "SIMULATION" in report.render_markdown(make_report(True), "fr")


def test_a_budget_violation_is_shown() -> None:
    _, results = run_bench({"todo": Scenario(ends="overspend")}, ["todo"])
    body = report.build_report(
        results,
        report.summarize(results, Decimal("8")),
        {"run_id": "r", "mode": "real", "started_at": "x"},
    )
    assert "BUDGET EXCEEDED by: todo" in report.render_markdown(body, "en")
    assert "BUDGET DÉPASSÉ par: todo" in report.render_markdown(body, "fr")


def test_reports_are_written(tmp_path: Path) -> None:
    paths = report.write_report(tmp_path, make_report(False))
    assert sorted(p.name for p in paths) == ["report.en.md", "report.fr.md", "report.json"]
    assert json.loads(paths[0].read_text("utf-8"))["schema_version"] == 1


def test_results_are_ignored_by_version_control_except_the_templates() -> None:
    ignore = (projects.PROJECTS_DIR / "results" / ".gitignore").read_text("utf-8")
    assert "*" in ignore.splitlines() and "!SUMMARY.template.en.md" in ignore
    assert "!SUMMARY.template.fr.md" in ignore


# --- the command line -------------------------------------------------------------------------


def run_cli(argv: list[str], monkeypatch: pytest.MonkeyPatch, api=None) -> tuple[int, str]:  # type: ignore[no-untyped-def]
    for var in (
        "COBBLE_BENCH_REAL_MODELS",
        "COBBLE_BENCH_EMAIL",
        "COBBLE_BENCH_PASSWORD",
        "COBBLE_BENCH_GIT_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    lines: list[str] = []
    code = cli.main(argv, api_factory=lambda _: api, out=lines.append, sleep=lambda _: None)
    return code, "\n".join(lines)


def test_a_real_run_refuses_without_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    code, text = run_cli([], monkeypatch)
    assert code == cli.EXIT_USAGE
    assert "Refus" in text and "Refused" in text and "--yes-real-models" in text


def test_a_real_run_refuses_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    code, text = run_cli(["--yes-real-models"], monkeypatch)
    assert code == cli.EXIT_USAGE and "COBBLE_BENCH_EMAIL" in text and "identifiants" in text


def test_a_real_run_refuses_without_a_code_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COBBLE_BENCH_EMAIL", "a@b.co")
    monkeypatch.setenv("COBBLE_BENCH_PASSWORD", "x")
    monkeypatch.setenv("COBBLE_BENCH_REAL_MODELS", "yes")
    lines: list[str] = []
    code = cli.main([], api_factory=lambda _: FakeCobble(), out=lines.append)
    assert code == cli.EXIT_USAGE and "--code-dir" in "\n".join(lines)


def test_a_real_run_refuses_the_development_fake_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COBBLE_BENCH_EMAIL", "a@b.co")
    monkeypatch.setenv("COBBLE_BENCH_PASSWORD", "x")
    fake = FakeCobble()
    fake.models["effective"] = {"planner": ["fake"], "worker": []}
    lines: list[str] = []
    code = cli.main(
        ["--yes-real-models", "--code-dir", str(tmp_path)],
        api_factory=lambda _: fake,
        out=lines.append,
    )
    text = "\n".join(lines)
    assert (
        code == cli.EXIT_USAGE
        and "aucune connexion" in text
        and "no connection to a real model" in text
    )
    assert fake.calls == []  # nothing was created, nothing spent


def test_a_confirmed_run_with_a_real_model_runs_and_writes_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("COBBLE_BENCH_EMAIL", "a@b.co")
    monkeypatch.setenv("COBBLE_BENCH_PASSWORD", "x")
    fake = FakeCobble()
    code_dir = tmp_path / "code"
    validate.build_tree(projects.load("todo"), code_dir / "todo")
    lines: list[str] = []
    code = cli.main(
        ["--yes-real-models", "--projects", "todo", "--preset", "balanced", "--slot", "cheap=m1",
         "--code-dir", str(code_dir), "--results-dir", str(tmp_path / "res"), "--python", sys.executable,
         "--poll-s", "0"],
        api_factory=lambda _: fake, out=lines.append, sleep=lambda _: None,
    )  # fmt: skip
    assert code == cli.EXIT_OK, lines
    assert fake.preset == ("balanced", {"cheap": "m1"})
    (run_dir,) = (tmp_path / "res").iterdir()
    assert not run_dir.name.startswith("dry-")
    assert json.loads((run_dir / "report.json").read_text("utf-8"))["mode"] == "real"


def test_dry_run_writes_reports_without_any_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, text = run_cli(
        ["--dry-run", "--projects", "todo,blog", "--results-dir", str(tmp_path)], monkeypatch
    )
    assert code == cli.EXIT_OK, text
    (run_dir,) = tmp_path.iterdir()
    assert run_dir.name.startswith("dry-")
    body = json.loads((run_dir / "report.json").read_text("utf-8"))
    assert body["mode"] == "dry-run" and body["summary"]["successes"] == 2
    assert "SIMULATION" in (run_dir / "report.fr.md").read_text("utf-8")


def test_list_and_bad_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    code, text = run_cli(["--list"], monkeypatch)
    assert code == 0 and all(name in text for name in NAMES)
    code, text = run_cli(["--projects", "nope"], monkeypatch)
    assert code == cli.EXIT_USAGE and "unknown reference project" in text
    code, _ = run_cli(["--total-budget", "abc"], monkeypatch)
    assert code == cli.EXIT_USAGE


def test_makefile_bench_never_runs_in_ci() -> None:
    makefile = (ROOT / "Makefile").read_text("utf-8")
    ci = "".join(p.read_text("utf-8") for p in (ROOT / ".github" / "workflows").glob("*.yml"))
    assert "bench:" in makefile and "make bench" not in ci and "scripts/bench.py" not in ci


# --- fetching the code ------------------------------------------------------------------------


def test_the_repository_name_follows_the_platform_rule() -> None:
    fetcher = GitFetcher("http://forge.local/org/{repo}.git", "secret")
    name = fetcher.repo_name(
        {"name": "bench-todo-20260101-000000", "id": "ABCDEF12-3456-7890-abcd-ef1234567890"}
    )
    assert name == "bench-todo-20260101-000000-abcdef"
