"""`logs` of the agent runners and `diff` of the git providers (ADR 0007)."""

from __future__ import annotations

import uuid

import httpx
import pytest

from cobble.capabilities.agent import AgentRunNotFound, AgentTask, AgentUnavailable
from cobble.capabilities.fakes import FakeAgentRunner, FakeCIProvider, FakeGitProvider
from cobble.capabilities.git import DIFF_LIMIT, RepoRef, cap_diff
from cobble.capabilities.llm import Role
from cobble.providers import ForgejoGit, ProviderUnavailable
from cobble.providers.agent_service import HttpAgentRunner

from .test_pack_providers import REPO, Recorder, git_with
from .test_pack_providers import settings as pack_settings

# --- cap_diff -----------------------------------------------------------------------------


def test_cap_diff_leaves_short_text_and_cuts_long_text_on_a_line() -> None:
    assert cap_diff("a\nb\n") == ("a\nb\n", False)
    assert cap_diff("x" * 10, 10) == ("x" * 10, False)
    assert cap_diff("aaa\nbbb\nccc\n", 9) == ("aaa\nbbb\n", True)
    assert cap_diff("x" * 20, 10) == ("x" * 10, True)  # no newline to cut at
    text, cut = cap_diff("y" * (DIFF_LIMIT + 5))
    assert (len(text), cut) == (DIFF_LIMIT, True)


# --- HttpAgentRunner.logs -----------------------------------------------------------------


def http_runner(handler: object) -> HttpAgentRunner:
    return HttpAgentRunner(
        "http://agents:8080",
        "tok",
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


def test_http_logs_sends_the_offset_and_reads_the_next_one() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="héllo\n", headers={"X-Next-Offset": "42"})

    text, nxt = http_runner(handler).logs("run-9", 30)
    assert (text, nxt) == ("héllo\n", 42)
    request = seen[0]
    assert (request.method, request.url.path, request.url.params["offset"]) == (
        "GET",
        "/v1/runs/run-9/logs",
        "30",
    )
    assert request.headers["authorization"] == "Bearer tok"
    assert request.headers["accept"] == "text/plain"


def test_http_logs_without_a_header_advances_by_the_bytes_received() -> None:
    runner = http_runner(lambda _r: httpx.Response(200, text="é\n"))
    assert runner.logs("r", 10) == ("é\n", 13)
    bad = http_runner(lambda _r: httpx.Response(200, text="ab", headers={"X-Next-Offset": "x"}))
    assert bad.logs("r") == ("ab", 2)


def test_http_logs_errors() -> None:
    with pytest.raises(AgentRunNotFound):
        http_runner(lambda _r: httpx.Response(404)).logs("r")
    with pytest.raises(AgentUnavailable):
        http_runner(lambda _r: httpx.Response(502)).logs("r")

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    with pytest.raises(AgentUnavailable):
        http_runner(boom).logs("r")


# --- FakeAgentRunner.logs -----------------------------------------------------------------


def fake_task() -> AgentTask:
    return AgentTask(
        uuid.UUID(int=1), uuid.UUID(int=2), "fake://x.git", "task/t-001", Role.WORKER, "do it"
    )


def test_fake_logs_are_deterministic_and_resumable() -> None:
    runner = FakeAgentRunner()
    run = runner.start(fake_task())
    text, nxt = runner.logs(run)
    assert text == "fake log of run-1\n$ worker on task/t-001\niteration 1: done\n"
    assert nxt == len(text)
    assert runner.logs(run) == (text, nxt)
    assert runner.logs(run, 5) == (text[5:], nxt)
    assert runner.logs(run, nxt) == ("", nxt)
    runner.stop(run)
    assert runner.logs(run, nxt)[0] == "stopped on request\n"


def test_fake_logs_errors() -> None:
    runner = FakeAgentRunner()
    with pytest.raises(AgentRunNotFound):
        runner.logs("run-7")
    run = runner.start(fake_task())
    runner.lost.add(run)
    with pytest.raises(AgentRunNotFound):
        runner.logs(run)
    runner.unavailable = True
    with pytest.raises(AgentUnavailable):
        runner.logs(run)


# --- FakeGitProvider.diff -----------------------------------------------------------------


def test_fake_git_diff() -> None:
    git = FakeGitProvider(FakeCIProvider())
    repo = RepoRef("r", "fake://r.git")
    assert git.diff(repo, "main", "feat") == ("", False)  # never pushed
    git.open_merge_request(repo, "feat", "main", "t")
    text, cut = git.diff(repo, "main", "feat", request_number=1)
    assert text.startswith("diff --git a/feat.txt") and not cut
    git.diffs[("r", "feat")] = "z" * (DIFF_LIMIT + 1)
    assert git.diff(repo, "main", "feat")[1] is True
    assert git.diff_calls[-1] == ("r", "main", "feat", None)


# --- ForgejoGit.diff ----------------------------------------------------------------------

P = "/api/v1/repos/cobble-bot/demo"
DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n"


def text_route(rec: Recorder, path: str, body: str, status: int = 200) -> None:
    rec.routes[("GET", path)] = lambda _r: httpx.Response(status, text=body)


def test_diff_by_known_pull_request_number() -> None:
    rec = Recorder()
    text_route(rec, f"{P}/pulls/7.diff", DIFF)
    assert git_with(rec).diff(REPO, "main", "feat", request_number=7) == (DIFF, False)
    assert rec.paths() == [f"GET {P}/pulls/7.diff"]
    assert rec.calls[0].headers["authorization"] == "token forgejo-secret-token"


def test_diff_finds_the_pull_request_of_the_pair() -> None:
    rec = Recorder()
    rec.on("GET", f"{P}/pulls/main/feat", 200, {"number": 9})
    text_route(rec, f"{P}/pulls/9.diff", DIFF)
    assert git_with(rec).diff(REPO, "main", "feat") == (DIFF, False)


def test_diff_falls_back_to_a_comparison_before_any_pull_request() -> None:
    rec = Recorder()
    text_route(rec, f"{P}/compare/main...feat.diff", DIFF)
    assert git_with(rec).diff(REPO, "main", "feat") == (DIFF, False)
    assert rec.paths() == [f"GET {P}/pulls/main/feat", f"GET {P}/compare/main...feat.diff"]


def test_diff_of_an_unknown_branch_is_empty() -> None:
    assert git_with(Recorder()).diff(REPO, "main", "ghost") == ("", False)
    rec = Recorder()
    text_route(rec, f"{P}/pulls/7.diff", "", 404)
    text_route(rec, f"{P}/compare/main...feat.diff", "", 404)
    assert git_with(rec).diff(REPO, "main", "feat", request_number=7) == ("", False)


def test_diff_is_truncated() -> None:
    rec = Recorder()
    text_route(rec, f"{P}/pulls/7.diff", ("+" + "x" * 99 + "\n") * 5000)
    text, cut = git_with(rec).diff(REPO, "main", "feat", request_number=7)
    assert cut is True and len(text) <= DIFF_LIMIT and text.endswith("\n")


def test_diff_errors_are_provider_errors() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x", request=request)

    git = ForgejoGit(pack_settings(), transport=httpx.MockTransport(boom))
    with pytest.raises(ProviderUnavailable):
        git.diff(REPO, "main", "feat", request_number=1)
