"""ForgejoGit and WoodpeckerCI against httpx.MockTransport: every call, refusals, polling,
error mapping, template rendering and credential hygiene."""

from __future__ import annotations

import base64
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from cobble.capabilities import CIState, CIStatus, MergeRefused, MergeRequestRef, RepoRef
from cobble.providers import (
    ForgejoGit,
    PackSettings,
    ProviderAuthError,
    ProviderConflict,
    ProviderError,
    ProviderNotFound,
    ProviderUnavailable,
    WoodpeckerCI,
    render_template,
)

TOKEN = "forgejo-secret-token"
WP_TOKEN = "woodpecker-secret-token"
SHA = "a" * 40
REPO = RepoRef("demo", "http://forgejo:3000/cobble-bot/demo.git")


def settings(**overrides: object) -> PackSettings:
    base: dict[str, object] = {
        "forgejo_url": "http://forgejo:3000",
        "forgejo_token": TOKEN,
        "forgejo_owner": "cobble-bot",
        "woodpecker_url": "http://wp:8000/ci",
        "woodpecker_token": WP_TOKEN,
        "ci_poll_interval_s": 1.0,
    }
    return PackSettings(**(base | overrides))  # type: ignore[arg-type]


class Recorder:
    """Routes (method, path) -> response, and records every request."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] = {}
        self.calls: list[httpx.Request] = []

    def on(self, method: str, path: str, status: int = 200, body: object = None) -> None:
        self.routes[(method, path)] = lambda _r: httpx.Response(status, json=body)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        handler = self.routes.get((request.method, request.url.path))
        if handler is None:
            return httpx.Response(
                404, json={"message": f"no route {request.method} {request.url.path}"}
            )
        return handler(request)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def paths(self) -> list[str]:
        return [f"{r.method} {r.url.path}" for r in self.calls]


def pull(state: str = "open", merged: bool = False, sha: str = SHA) -> dict[str, object]:
    return {
        "number": 7,
        "state": state,
        "merged": merged,
        "head": {"ref": "feat", "sha": sha},
        "base": {"ref": "main"},
    }


def git_with(rec: Recorder, ci: object | None = None, **kw: object) -> ForgejoGit:
    return ForgejoGit(  # type: ignore[arg-type]
        settings(**kw), ci=ci, transport=rec.transport(), sleep=lambda _s: None
    )


# --- template ---------------------------------------------------------------------------


def test_render_template_replaces_placeholder_in_text_only(tmp_path: Path) -> None:
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    (src / "README.md").write_text("# {{project_name}} and {{ project_name }}\n")
    (src / "sub" / "x.py").write_text('NAME = "{{project_name}}"\n')
    (src / "logo.bin").write_bytes(b"\xff\xfe{{project_name}}")
    (src / "node_modules").mkdir()
    (src / "node_modules" / "skip.js").write_text("x")
    (src / ".woodpecker.yaml").write_text("steps: []\n")
    dst.mkdir()
    render_template(src, dst, "todo-app")
    assert (dst / "README.md").read_text() == "# todo-app and todo-app\n"
    assert (dst / "sub" / "x.py").read_text() == 'NAME = "todo-app"\n'
    assert (dst / "logo.bin").read_bytes() == b"\xff\xfe{{project_name}}"
    assert (dst / ".woodpecker.yaml").exists()
    assert not (dst / "node_modules").exists()


def test_real_template_has_no_unrendered_placeholder_in_code(tmp_path: Path) -> None:
    template = Path(__file__).resolve().parents[3] / "templates" / "fastapi-react"
    render_template(template, tmp_path, "my-app")
    assert "my-app" in (tmp_path / "README.md").read_text()
    assert "my-app" in (tmp_path / "PROJECT.md").read_text()
    assert (tmp_path / ".woodpecker.yaml").exists()
    assert "{{" not in (tmp_path / "app" / "main.py").read_text()


# --- create repo -------------------------------------------------------------------------


def test_create_repo_creates_pushes_waits_then_protects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "t").mkdir()
    (tmp_path / "t" / "README.md").write_text("# {{project_name}}")
    rec = Recorder()
    rec.on("POST", "/api/v1/user/repos", 201, {"name": "demo"})
    branch_calls = iter([404, 404, 200])
    rec.routes[("GET", "/api/v1/repos/cobble-bot/demo/branches/main")] = lambda _r: httpx.Response(
        next(branch_calls), json={}
    )
    rec.on("POST", "/api/v1/repos/cobble-bot/demo/branch_protections", 201, {})
    sleeps: list[float] = []
    git = ForgejoGit(settings(), transport=rec.transport(), sleep=sleeps.append)
    pushed: list[tuple[str, str]] = []

    def fake_push(self: ForgejoGit, clone_url: str, tree: Path) -> None:
        pushed.append((clone_url, (tree / "README.md").read_text()))

    monkeypatch.setattr(ForgejoGit, "_push_tree", fake_push)
    repo = git.create_repo_from_template("demo", tmp_path / "t")

    assert repo == RepoRef("demo", "http://forgejo:3000/cobble-bot/demo.git")
    assert pushed == [(repo.clone_url, "# demo")]
    assert sleeps == [1.0, 1.0]
    create = json.loads(rec.calls[0].content)
    assert create["private"] is True and create["auto_init"] is False
    protection = json.loads(rec.calls[-1].content)
    assert protection["enable_push"] is False
    assert protection["enable_status_check"] is True
    assert protection["status_check_contexts"] == ["ci/woodpecker/pr/*"]
    assert protection["apply_to_admins"] is True
    # Protection comes after the push, otherwise the first push would be refused.
    assert rec.paths()[-1].endswith("/branch_protections")
    assert all(c.headers["authorization"] == f"token {TOKEN}" for c in rec.calls)


def test_create_repo_looks_up_owner_when_not_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "t").mkdir()
    rec = Recorder()
    rec.on("GET", "/api/v1/user", 200, {"login": "svc"})
    rec.on("POST", "/api/v1/user/repos", 201, {})
    rec.on("GET", "/api/v1/repos/svc/demo/branches/main", 200, {})
    rec.on("POST", "/api/v1/repos/svc/demo/branch_protections", 201, {})
    monkeypatch.setattr(ForgejoGit, "_push_tree", lambda *_a: None)
    repo = git_with(rec, forgejo_owner="").create_repo_from_template("demo", tmp_path / "t")
    assert repo.clone_url == "http://forgejo:3000/svc/demo.git"


def test_protection_is_updated_when_it_already_exists() -> None:
    rec = Recorder()
    rec.on("POST", "/api/v1/repos/cobble-bot/demo/branch_protections", 409, {"message": "exists"})
    rec.on("PATCH", "/api/v1/repos/cobble-bot/demo/branch_protections/main", 200, {})
    git_with(rec).protect_default_branch(REPO)
    assert rec.paths()[-1] == "PATCH /api/v1/repos/cobble-bot/demo/branch_protections/main"


@pytest.mark.parametrize("name", ["", "../x", "a b", "-x", "x" * 101])
def test_create_repo_rejects_bad_names(name: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid repository name"):
        git_with(Recorder()).create_repo_from_template(name, tmp_path)


def test_create_repo_conflict_is_mapped(tmp_path: Path) -> None:
    rec = Recorder()
    rec.on("POST", "/api/v1/user/repos", 409, {"message": "already exists"})
    with pytest.raises(ProviderConflict, match="already exists"):
        git_with(rec).create_repo_from_template("demo", tmp_path)


def test_default_branch_that_never_appears_is_an_error() -> None:
    rec = Recorder()
    git = ForgejoGit(settings(), transport=rec.transport(), sleep=lambda _s: None)
    with pytest.raises(ProviderError, match="did not appear"):
        git._wait_for_branch(REPO, attempts=3)


# --- git CLI hygiene ---------------------------------------------------------------------


def test_push_tree_publishes_without_persisting_credentials(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)  # noqa: S603, S607
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("hello")
    git = ForgejoGit(settings(), transport=Recorder().transport())
    git._push_tree(remote.as_uri(), tree)
    log = subprocess.run(  # noqa: S603
        ["git", "--git-dir", str(remote), "log", "--format=%an|%s", "main"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert log.strip() == "Cobble|chore: initial commit from template"
    config = (tree / ".git" / "config").read_text()
    assert TOKEN not in config
    assert base64.b64encode(f"cobble-bot:{TOKEN}".encode()).decode() not in config
    assert "extraHeader" not in config


def test_git_failure_message_never_contains_the_token(tmp_path: Path) -> None:
    git = ForgejoGit(settings(), transport=Recorder().transport())
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "a.txt").write_text("x")
    with pytest.raises(ProviderError) as info:
        git._push_tree("http://127.0.0.1:9/none.git", tree)
    assert TOKEN not in str(info.value)
    assert base64.b64encode(f"cobble-bot:{TOKEN}".encode()).decode() not in str(info.value)


def test_scrub_removes_secrets_from_text() -> None:
    git = ForgejoGit(settings(), transport=Recorder().transport())
    header = base64.b64encode(f"cobble-bot:{TOKEN}".encode()).decode()
    assert git._scrub(f"x {TOKEN} y {header}") == "x *** y ***"


# --- merge requests ---------------------------------------------------------------------


def test_open_merge_request_returns_head_sha() -> None:
    rec = Recorder()
    rec.on("POST", "/api/v1/repos/cobble-bot/demo/pulls", 201, pull())
    mr = git_with(rec).open_merge_request(REPO, "feat", "main", "Add feat")
    assert mr == MergeRequestRef(REPO, 7, "feat", "main", SHA)
    assert json.loads(rec.calls[0].content) == {"head": "feat", "base": "main", "title": "Add feat"}


def test_open_merge_request_reuses_the_existing_one() -> None:
    rec = Recorder()
    rec.on("POST", "/api/v1/repos/cobble-bot/demo/pulls", 409, {"message": "already exists"})
    rec.on("GET", "/api/v1/repos/cobble-bot/demo/pulls", 200, [pull()])
    assert git_with(rec).open_merge_request(REPO, "feat", "main", "t").number == 7


def test_open_merge_request_conflict_without_existing_one_raises() -> None:
    rec = Recorder()
    rec.on("POST", "/api/v1/repos/cobble-bot/demo/pulls", 409, {"message": "nothing to compare"})
    rec.on("GET", "/api/v1/repos/cobble-bot/demo/pulls", 200, [])
    with pytest.raises(ProviderConflict):
        git_with(rec).open_merge_request(REPO, "feat", "main", "t")


class StubCI:
    def __init__(self, state: CIState, detail: str = "") -> None:
        self.state = state
        self.detail = detail
        self.asked: list[tuple[str, str]] = []

    def activate(self, repo: RepoRef) -> None: ...

    def status(self, repo: RepoRef, ref: str) -> CIStatus:
        self.asked.append((repo.name, ref))
        return CIStatus(self.state, self.detail)

    def wait(self, repo: RepoRef, ref: str, timeout_s: float) -> CIStatus:
        return self.status(repo, ref)


MR = MergeRequestRef(REPO, 7, "feat", "main", SHA)
PULL_PATH = "/api/v1/repos/cobble-bot/demo/pulls/7"


def test_merge_succeeds_when_ci_is_green_and_checks_the_current_head() -> None:
    rec = Recorder()
    newer = "b" * 40
    rec.on("GET", PULL_PATH, 200, pull(sha=newer))
    rec.on("POST", PULL_PATH + "/merge", 200, None)
    ci = StubCI(CIState.SUCCESS)
    git_with(rec, ci).merge(MR)
    assert ci.asked == [("demo", newer)]  # the head as of now, not the stale one in the ref
    body = json.loads(rec.calls[-1].content)
    assert body == {"Do": "squash", "head_commit_id": newer, "delete_branch_after_merge": True}


@pytest.mark.parametrize("state", [CIState.PENDING, CIState.FAILURE])
def test_merge_is_refused_when_ci_is_not_green(state: CIState) -> None:
    rec = Recorder()
    rec.on("GET", PULL_PATH, 200, pull())
    with pytest.raises(MergeRefused, match=state.value):
        git_with(rec, StubCI(state, "pipeline #3")).merge(MR)
    assert not any(p.endswith("/merge") for p in rec.paths())  # never even asked the server


def test_merge_refused_by_server_protection_is_mapped() -> None:
    rec = Recorder()
    rec.on("GET", PULL_PATH, 200, pull())
    rec.on(
        "POST", PULL_PATH + "/merge", 405, {"message": "Not all required status checks successful"}
    )
    with pytest.raises(MergeRefused, match="required status checks"):
        git_with(rec, StubCI(CIState.SUCCESS)).merge(MR)


def _merge_after_base_moved(
    refusals: int, mergeable: list[bool]
) -> tuple[Recorder, list[float], bool]:
    """Merge refused `refusals` times while the server recomputes mergeability, then accepted.

    `mergeable` is what successive reads of the pull request report (the last one repeats).
    """
    rec = Recorder()
    reads = list(mergeable)

    def read(_r: httpx.Request) -> httpx.Response:
        value = reads.pop(0) if len(reads) > 1 else reads[0]
        return httpx.Response(200, json={**pull(), "mergeable": value})

    rec.routes[("GET", PULL_PATH)] = read
    state = {"left": refusals}

    def handler(_r: httpx.Request) -> httpx.Response:
        if state["left"] > 0:
            state["left"] -= 1
            return httpx.Response(405, json={"message": "Please try again later"})
        return httpx.Response(200, json=None)

    rec.routes[("POST", PULL_PATH + "/merge")] = handler
    slept: list[float] = []
    git = ForgejoGit(
        settings(), ci=StubCI(CIState.SUCCESS), transport=rec.transport(), sleep=slept.append
    )
    try:
        git.merge(MR)
    except MergeRefused:
        return rec, slept, False
    return rec, slept, True


def test_merge_is_retried_while_the_server_recomputes_mergeability() -> None:
    rec, slept, merged = _merge_after_base_moved(refusals=2, mergeable=[True])
    assert merged
    assert len([p for p in rec.paths() if p == f"POST {PULL_PATH}/merge"]) == 3
    assert len(slept) == 2


def test_merge_gives_up_after_a_few_retries() -> None:
    rec, _slept, merged = _merge_after_base_moved(refusals=99, mergeable=[True])
    assert not merged
    assert len([p for p in rec.paths() if p == f"POST {PULL_PATH}/merge"]) == 4


def test_a_pull_request_reported_unmergeable_for_a_moment_is_retried() -> None:
    # Right after the base moved Forgejo first reports "not mergeable", then settles.
    rec, _slept, merged = _merge_after_base_moved(refusals=1, mergeable=[True, False, False, True])
    assert merged
    assert len([p for p in rec.paths() if p == f"POST {PULL_PATH}/merge"]) == 2


def test_a_real_conflict_is_refused_after_the_reads_settle() -> None:
    rec, slept, merged = _merge_after_base_moved(refusals=1, mergeable=[True, False])
    assert not merged
    assert len(slept) == 3  # three reads, all unmergeable
    assert len([p for p in rec.paths() if p == f"POST {PULL_PATH}/merge"]) == 1


def test_merge_other_server_errors_are_not_refusals() -> None:
    rec = Recorder()
    rec.on("GET", PULL_PATH, 200, pull())
    rec.on("POST", PULL_PATH + "/merge", 500, {"message": "boom"})
    with pytest.raises(ProviderError) as info:
        git_with(rec, StubCI(CIState.SUCCESS)).merge(MR)
    assert not isinstance(info.value, MergeRefused)


def test_merge_of_a_closed_or_merged_request() -> None:
    rec = Recorder()
    rec.on("GET", PULL_PATH, 200, pull(state="closed"))
    with pytest.raises(MergeRefused, match="closed"):
        git_with(rec, StubCI(CIState.SUCCESS)).merge(MR)
    rec.on("GET", PULL_PATH, 200, pull(state="closed", merged=True))
    git_with(rec, StubCI(CIState.FAILURE)).merge(MR)  # already merged: nothing to do


def commit_status(rec: Recorder, statuses: list[dict[str, str]]) -> None:
    rec.on(
        "GET", f"/api/v1/repos/cobble-bot/demo/commits/{SHA}/status", 200, {"statuses": statuses}
    )


def test_without_ci_provider_forgejo_statuses_decide() -> None:
    rec = Recorder()
    rec.on("GET", PULL_PATH, 200, pull())
    rec.on("POST", PULL_PATH + "/merge", 200, None)
    commit_status(rec, [{"context": "ci/woodpecker/pr/woodpecker", "status": "success"}])
    git_with(rec).merge(MR)
    assert rec.paths()[-1].endswith("/merge")


@pytest.mark.parametrize(
    "statuses",
    [
        [],
        [{"context": "ci/woodpecker/push/woodpecker", "status": "success"}],
        [{"context": "ci/woodpecker/pr/woodpecker", "status": "pending"}],
        [{"context": "ci/woodpecker/pr/woodpecker", "status": "failure"}],
    ],
)
def test_without_ci_provider_missing_or_bad_statuses_refuse(statuses: list[dict[str, str]]) -> None:
    rec = Recorder()
    rec.on("GET", PULL_PATH, 200, pull())
    commit_status(rec, statuses)
    with pytest.raises(MergeRefused):
        git_with(rec).merge(MR)


def test_tag() -> None:
    rec = Recorder()
    rec.on("POST", "/api/v1/repos/cobble-bot/demo/tags", 201, {})
    git_with(rec).tag(REPO, "v0.1.0", "main")
    assert json.loads(rec.calls[0].content) == {"tag_name": "v0.1.0", "target": "main"}


def test_tag_conflict() -> None:
    rec = Recorder()
    rec.on("POST", "/api/v1/repos/cobble-bot/demo/tags", 409, {"message": "tag exists"})
    with pytest.raises(ProviderConflict):
        git_with(rec).tag(REPO, "v0.1.0", "main")


def test_commit_files_creates_a_branch_and_updates_existing_files() -> None:
    rec = Recorder()
    base = "/api/v1/repos/cobble-bot/demo"
    rec.on("GET", f"{base}/branches/feat", 404, {"message": "nope"})
    rec.on("GET", f"{base}/contents/old.txt", 200, {"sha": "oldsha"})
    rec.on("GET", f"{base}/contents/new.txt", 404, {"message": "nope"})
    rec.on("POST", f"{base}/contents", 201, {"commit": {"sha": SHA}})
    sha = git_with(rec).commit_files(REPO, "feat", {"old.txt": "a", "new.txt": "b"}, "msg")
    assert sha == SHA
    body = json.loads(rec.calls[-1].content)
    assert body["branch"] == "main" and body["new_branch"] == "feat"
    ops = {o["path"]: o for o in body["files"]}
    assert ops["old.txt"]["operation"] == "update" and ops["old.txt"]["sha"] == "oldsha"
    assert ops["new.txt"]["operation"] == "create"
    assert base64.b64decode(ops["new.txt"]["content"]) == b"b"


def test_merge_request_refresh() -> None:
    rec = Recorder()
    rec.on("GET", PULL_PATH, 200, pull(sha="c" * 40))
    assert git_with(rec).merge_request(MR).head_sha == "c" * 40


# --- error mapping ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (404, ProviderNotFound),
        (422, ProviderConflict),
        (500, ProviderError),
    ],
)
def test_http_errors_are_mapped_without_leaking_the_token(
    status: int, error: type[Exception]
) -> None:
    rec = Recorder()
    rec.on("GET", "/api/v1/user", status, {"message": "nope"})
    with pytest.raises(error) as info:
        git_with(rec, forgejo_owner="").owner  # noqa: B018
    assert TOKEN not in str(info.value)
    assert getattr(info.value, "status", None) == status


def test_network_errors_are_mapped() -> None:
    def boom(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect with {TOKEN}")

    git = ForgejoGit(settings(forgejo_owner=""), transport=httpx.MockTransport(boom))
    with pytest.raises(ProviderUnavailable) as info:
        git.owner  # noqa: B018
    assert TOKEN not in str(info.value)


# --- Woodpecker ---------------------------------------------------------------------------

WP = "/ci/api"


def ci_with(rec: Recorder, **kw: object) -> WoodpeckerCI:
    sleeps = kw.pop("sleeps", None)
    return WoodpeckerCI(
        settings(**kw),
        transport=rec.transport(),
        sleep=sleeps.append if isinstance(sleeps, list) else (lambda _s: None),
        clock=kw.pop("clock", lambda: 0.0),  # type: ignore[arg-type]
    )


def pipelines(*items: tuple[int, str, str, str, str]) -> list[dict[str, object]]:
    return [
        {"number": n, "status": status, "commit": commit, "branch": "main", "refspec": refspec}
        for n, status, commit, refspec, _ in items
    ]


def wp_repo(rec: Recorder) -> None:
    rec.on("GET", f"{WP}/repos/lookup/cobble-bot/demo", 200, {"id": 5, "active": True})


def test_activate_registers_an_unknown_repository_then_applies_settings() -> None:
    rec = Recorder()
    rec.on(
        "GET",
        f"{WP}/user/repos",
        200,
        [
            {"full_name": "cobble-bot/other", "forge_remote_id": "1"},
            {"full_name": "cobble-bot/demo", "forge_remote_id": "9"},
        ],
    )
    rec.on("POST", f"{WP}/repos", 200, {"id": 5})
    rec.on("PATCH", f"{WP}/repos/5", 200, {})
    ci_with(rec).activate(REPO)
    post = next(c for c in rec.calls if c.method == "POST")
    assert post.url.params["forge_remote_id"] == "9"
    patch = json.loads(rec.calls[-1].content)
    assert patch["trusted"] == {"network": False, "volumes": False, "security": False}
    assert patch["allow_pr"] is True
    assert all(c.headers["authorization"] == f"Bearer {WP_TOKEN}" for c in rec.calls)


def test_activate_twice_only_reapplies_settings() -> None:
    rec = Recorder()
    wp_repo(rec)
    rec.on("PATCH", f"{WP}/repos/5", 200, {})
    ci_with(rec).activate(REPO)
    assert rec.paths() == [f"GET {WP}/repos/lookup/cobble-bot/demo", f"PATCH {WP}/repos/5"]


def test_activate_unknown_repo_raises() -> None:
    rec = Recorder()
    rec.on("GET", f"{WP}/user/repos", 200, [])
    with pytest.raises(ProviderNotFound):
        ci_with(rec).activate(REPO)


@pytest.mark.parametrize(
    ("raw", "state"),
    [
        ("success", CIState.SUCCESS),
        ("failure", CIState.FAILURE),
        ("error", CIState.FAILURE),
        ("killed", CIState.FAILURE),
        ("declined", CIState.FAILURE),
        ("skipped", CIState.FAILURE),
        ("pending", CIState.PENDING),
        ("running", CIState.PENDING),
        ("created", CIState.PENDING),
        ("blocked", CIState.PENDING),
    ],
)
def test_status_mapping(raw: str, state: CIState) -> None:
    rec = Recorder()
    wp_repo(rec)
    rec.on("GET", f"{WP}/repos/5/pipelines", 200, pipelines((4, raw, SHA, "feat:main", "")))
    assert ci_with(rec).status(REPO, SHA).state is state


def test_status_picks_the_latest_pipeline_of_the_ref() -> None:
    rec = Recorder()
    wp_repo(rec)
    rec.on(
        "GET",
        f"{WP}/repos/5/pipelines",
        200,
        pipelines(
            (2, "failure", "1" * 40, "feat:main", ""),
            (5, "success", "2" * 40, "feat:main", ""),
            (6, "failure", "3" * 40, "other:main", ""),
        ),
    )
    assert ci_with(rec).status(REPO, "feat").state is CIState.SUCCESS  # by branch (refspec source)
    assert ci_with(rec).status(REPO, "2" * 40).detail == "pipeline #5 success"
    assert ci_with(rec).status(REPO, "2222222").state is CIState.SUCCESS  # short sha


def test_status_without_pipeline_or_activation_is_pending() -> None:
    rec = Recorder()
    wp_repo(rec)
    rec.on("GET", f"{WP}/repos/5/pipelines", 200, [])
    assert ci_with(rec).status(REPO, SHA) == CIStatus(CIState.PENDING, "no pipeline yet")
    inactive = Recorder()
    assert ci_with(inactive).status(REPO, SHA).state is CIState.PENDING


def test_wait_polls_until_done() -> None:
    rec = Recorder()
    wp_repo(rec)
    answers = iter(
        [
            [],
            pipelines((1, "running", SHA, "feat:main", "")),
            pipelines((1, "success", SHA, "feat:main", "")),
        ]
    )
    rec.routes[("GET", f"{WP}/repos/5/pipelines")] = lambda _r: httpx.Response(
        200, json=next(answers)
    )
    sleeps: list[float] = []
    status = ci_with(rec, sleeps=sleeps).wait(REPO, SHA, 60)
    assert status.state is CIState.SUCCESS
    assert sleeps == [1.0, 1.0]


def test_wait_times_out_with_the_last_pending_status() -> None:
    rec = Recorder()
    wp_repo(rec)
    rec.on("GET", f"{WP}/repos/5/pipelines", 200, pipelines((1, "running", SHA, "feat:main", "")))
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    ci = WoodpeckerCI(
        settings(ci_poll_interval_s=10),
        transport=rec.transport(),
        sleep=sleep,
        clock=lambda: now[0],
    )
    status = ci.wait(REPO, SHA, 25)
    assert status.state is CIState.PENDING
    assert sleeps == [10, 10, 10]


def test_wait_returns_immediately_on_failure() -> None:
    rec = Recorder()
    wp_repo(rec)
    rec.on("GET", f"{WP}/repos/5/pipelines", 200, pipelines((1, "failure", SHA, "feat:main", "")))
    sleeps: list[float] = []
    assert ci_with(rec, sleeps=sleeps).wait(REPO, SHA, 60).state is CIState.FAILURE
    assert sleeps == []


def test_ci_errors_are_mapped() -> None:
    rec = Recorder()
    rec.on("GET", f"{WP}/repos/lookup/cobble-bot/demo", 401, {"message": "bad token"})
    with pytest.raises(ProviderAuthError) as info:
        ci_with(rec).status(REPO, SHA)
    assert WP_TOKEN not in str(info.value)


def test_bad_clone_url_is_rejected() -> None:
    with pytest.raises(ProviderError):
        ci_with(Recorder()).activate(RepoRef("x", "http://forgejo:3000/x.git"))


# --- settings ------------------------------------------------------------------------------


def test_settings_read_the_pack_env_file_and_hide_secrets(tmp_path: Path) -> None:
    from cobble.providers import load_settings

    env = tmp_path / ".env.pack"
    env.write_text(
        "COBBLE_PACK_FORGEJO_URL=http://g:3000\nCOBBLE_PACK_FORGEJO_TOKEN=tok-AAA111\n"
        "COBBLE_PACK_WOODPECKER_URL=http://w:8000/ci\nCOBBLE_PACK_WOODPECKER_TOKEN=tok-BBB222\n"
        "COBBLE_PACK_FORGEJO_OWNER=bot\nSOMETHING_ELSE=1\n"
    )
    loaded = load_settings(env)
    assert loaded.forgejo_url == "http://g:3000" and loaded.forgejo_owner == "bot"
    assert loaded.configured()
    assert "AAA111" not in repr(loaded) and "BBB222" not in repr(loaded)


def test_settings_defaults_are_in_network_urls() -> None:
    default = PackSettings()
    assert default.forgejo_url == "http://forgejo:3000"
    assert default.woodpecker_url == "http://woodpecker-server:8000/ci"
    assert not default.configured()
