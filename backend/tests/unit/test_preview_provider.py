"""HttpPreviewProvider on MockTransport; ForgejoGit.restore_tag against a real local repository."""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import httpx
import pytest

from cobble.capabilities import RepoRef
from cobble.capabilities.git import TagExists
from cobble.capabilities.preview import (
    PreviewRejected,
    PreviewRequest,
    PreviewState,
    PreviewUnavailable,
)
from cobble.providers import ForgejoGit, PackSettings
from cobble.providers.preview_service import HttpPreviewProvider

from .test_pack_providers import Recorder

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TOKEN = "preview-secret-token"
REQUEST = PreviewRequest(PID, "M1", "http://forgejo:3000/o/r.git", "milestone-M1")


def provider(handler: httpx.MockTransport) -> HttpPreviewProvider:
    return HttpPreviewProvider("http://preview:8091/", TOKEN, transport=handler)


def test_deploy_posts_the_request_with_the_bearer_token() -> None:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"state": "building", "path": f"/demo/{PID}/M1/"})

    status = provider(httpx.MockTransport(handle)).deploy(REQUEST)
    assert (status.state, status.path) == (PreviewState.BUILDING, f"/demo/{PID}/M1/")
    assert seen[0].headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(seen[0].content) == {
        "project_id": str(PID),
        "milestone": "M1",
        "repo_clone_url": REQUEST.repo_clone_url,
        "ref": "milestone-M1",
    }
    assert seen[0].url.path == "/v1/previews"


def test_status_remove_and_errors() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/previews/{PID}-M1"
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json={"state": "failed", "path": "/demo/x/", "detail": "boom"})

    p = provider(httpx.MockTransport(handle))
    status = p.status(PID, "M1")
    assert status is not None and status.state is PreviewState.FAILED and status.detail == "boom"
    p.remove(PID, "M1")

    missing = provider(httpx.MockTransport(lambda _r: httpx.Response(404)))
    assert missing.status(PID, "M1") is None
    missing.remove(PID, "M1")

    refused = provider(httpx.MockTransport(lambda _r: httpx.Response(422)))
    with pytest.raises(PreviewRejected):
        refused.deploy(REQUEST)
    broken = provider(httpx.MockTransport(lambda _r: httpx.Response(500)))
    with pytest.raises(PreviewUnavailable):
        broken.deploy(REQUEST)
    garbage = provider(httpx.MockTransport(lambda _r: httpx.Response(200, text="nope")))
    with pytest.raises(PreviewUnavailable):
        garbage.status(PID, "M1")


def test_unreachable_service_does_not_leak_the_token() -> None:
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot connect {TOKEN}")

    with pytest.raises(PreviewUnavailable) as err:
        provider(httpx.MockTransport(down)).deploy(REQUEST)
    assert TOKEN not in str(err.value)


# --- restore_tag ------------------------------------------------------------------------------

ENV = {
    "PATH": "/usr/bin:/bin:/usr/local/bin",
    "HOME": "/nonexistent",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(*args: str, cwd: Path) -> str:
    done = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        env=ENV,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def make_repo(tmp_path: Path) -> tuple[RepoRef, Path]:
    bare = tmp_path / "remote" / "cobble-bot" / "demo.git"
    bare.parent.mkdir(parents=True)
    git("init", "-q", "--bare", "-b", "main", str(bare), cwd=tmp_path)
    work = tmp_path / "work"
    git("init", "-q", "-b", "main", str(work), cwd=tmp_path)
    git("remote", "add", "origin", str(bare), cwd=work)
    (work / "a.txt").write_text("one\n")
    git("add", "-A", cwd=work)
    git("commit", "-qm", "first", cwd=work)
    git("tag", "milestone-M1", cwd=work)
    (work / "a.txt").write_text("two\n")
    (work / "b.txt").write_text("new\n")
    git("add", "-A", cwd=work)
    git("commit", "-qm", "second", cwd=work)
    git("push", "-q", "origin", "main", "--tags", cwd=work)
    return RepoRef("demo", str(bare)), work


def forgejo(rec: Recorder) -> ForgejoGit:
    settings = PackSettings(
        forgejo_url="http://forgejo:3000",
        forgejo_token="t",  # type: ignore[arg-type]
        forgejo_owner="cobble-bot",
    )
    return ForgejoGit(settings, transport=httpx.MockTransport(rec))


def test_restore_tag_pushes_a_commit_with_the_tags_tree_and_opens_a_merge_request(
    tmp_path: Path,
) -> None:
    repo, work = make_repo(tmp_path)
    rec = Recorder()
    pulls = "/api/v1/repos/cobble-bot/demo/pulls"
    rec.on(
        "POST",
        pulls,
        201,
        {"number": 7, "head": {"ref": "restore/milestone-M1", "sha": "x"}, "base": {"ref": "main"}},
    )
    request = forgejo(rec).restore_tag(repo, "milestone-M1", "Restore milestone-M1")
    assert request is not None
    assert (request.number, request.source_branch, request.target_branch) == (
        7,
        "restore/milestone-M1",
        "main",
    )
    assert json.loads(rec.calls[0].content)["head"] == "restore/milestone-M1"
    bare = Path(repo.clone_url)
    pushed = git("rev-parse", "restore/milestone-M1", cwd=bare)
    assert pushed == request.head_sha
    assert git("rev-parse", f"{pushed}^{{tree}}", cwd=bare) == git(
        "rev-parse", "milestone-M1^{tree}", cwd=bare
    )
    assert git("rev-parse", f"{pushed}^", cwd=bare) == git("rev-parse", "main", cwd=bare)
    del work


def test_restore_tag_has_nothing_to_do_when_the_tree_is_already_there(tmp_path: Path) -> None:
    repo, work = make_repo(tmp_path)
    git("tag", "milestone-M2", cwd=work)
    git("push", "-q", "origin", "milestone-M2", cwd=work)
    assert forgejo(Recorder()).restore_tag(repo, "milestone-M2", "msg") is None


def test_restore_tag_rejects_odd_tag_names(tmp_path: Path) -> None:
    repo, _ = make_repo(tmp_path)
    with pytest.raises(ValueError, match="invalid tag"):
        forgejo(Recorder()).restore_tag(repo, "--upload-pack=x", "msg")


def test_tag_conflict_is_a_tag_exists() -> None:
    rec = Recorder()
    rec.on("POST", "/api/v1/repos/cobble-bot/demo/tags", 409, {"message": "tag exists"})
    with pytest.raises(TagExists):
        forgejo(rec).tag(RepoRef("demo", "http://forgejo:3000/cobble-bot/demo.git"), "t", "main")
