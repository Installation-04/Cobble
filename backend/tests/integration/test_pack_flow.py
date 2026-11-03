"""Step-6 criterion against the REAL pack (Forgejo + Woodpecker): a green merge request is
merged, a red one is refused, at both levels (our code and the git server's protection).

Skipped unless COBBLE_PACK_FLOW=1 and the COBBLE_PACK_* variables point at a running pack
(install the forgejo and woodpecker modules and export their address and token as COBBLE_PACK_*).
"""

from __future__ import annotations

import base64
import os
import re
import uuid
from pathlib import Path

import pytest

from cobble.capabilities import CIState, MergeRefused
from cobble.providers import ForgejoGit, PackSettings, ProviderError, WoodpeckerCI

pytestmark = pytest.mark.integration

TEMPLATE = Path(__file__).resolve().parents[3] / "templates" / "fastapi-react"
CI_TIMEOUT_S = float(os.environ.get("COBBLE_PACK_FLOW_TIMEOUT_S", "900"))


@pytest.fixture(scope="module")
def settings() -> PackSettings:
    if os.environ.get("COBBLE_PACK_FLOW") != "1":
        pytest.skip("COBBLE_PACK_FLOW=1 is not set")
    pack = PackSettings()
    if not pack.configured():
        pytest.skip("COBBLE_PACK_FORGEJO_TOKEN / COBBLE_PACK_WOODPECKER_TOKEN are not set")
    return pack


@pytest.fixture(scope="module")
def ci(settings: PackSettings) -> WoodpeckerCI:
    return WoodpeckerCI(settings)


@pytest.fixture(scope="module")
def git(settings: PackSettings, ci: WoodpeckerCI) -> ForgejoGit:
    return ForgejoGit(settings, ci=ci)


@pytest.fixture(scope="module")
def repo(git: ForgejoGit, ci: WoodpeckerCI):  # type: ignore[no-untyped-def]
    name = f"flow-{uuid.uuid4().hex[:8]}"
    created = git.create_repo_from_template(name, TEMPLATE)
    ci.activate(created)
    return created


def test_template_placeholder_is_replaced(git: ForgejoGit, repo) -> None:  # type: ignore[no-untyped-def]
    entry = git._api.request(
        "GET", f"{git._repo_path(repo)}/contents/README.md", params={"ref": "main"}
    )
    readme = base64.b64decode(entry["content"]).decode()
    assert repo.name in readme
    assert not re.search(r"\{\{\s*project_name\s*\}\}", readme)


def test_green_branch_is_merged(git: ForgejoGit, ci: WoodpeckerCI, repo) -> None:  # type: ignore[no-untyped-def]
    git.commit_files(repo, "feature/notes", {"docs/NOTES.md": "# Notes\n"}, "docs: add notes")
    mr = git.open_merge_request(repo, "feature/notes", "main", "Add notes")
    assert mr.head_sha
    status = ci.wait(repo, mr.head_sha, CI_TIMEOUT_S)
    assert status.state is CIState.SUCCESS, status
    git.merge(mr)
    pull = git._api.request("GET", f"{git._repo_path(repo)}/pulls/{mr.number}")
    assert pull["merged"] is True


def test_red_branch_is_refused_and_stays_open(
    git: ForgejoGit,
    ci: WoodpeckerCI,
    settings: PackSettings,
    repo,  # type: ignore[no-untyped-def]
) -> None:
    broken = (
        "from fastapi.testclient import TestClient\n\nfrom app.main import app\n\n\n"
        "def test_health_returns_ok() -> None:\n"
        '    assert TestClient(app).get("/api/health").status_code == 500\n'
    )
    git.commit_files(repo, "feature/broken", {"tests/test_health.py": broken}, "test: break it")
    mr = git.open_merge_request(repo, "feature/broken", "main", "Break a test")
    assert mr.head_sha

    # Merging before CI has finished is refused too (pending is not green).
    with pytest.raises(MergeRefused):
        git.merge(mr)

    status = ci.wait(repo, mr.head_sha, CI_TIMEOUT_S)
    assert status.state is CIState.FAILURE, status

    # Level 1: our own check.
    with pytest.raises(MergeRefused):
        git.merge(mr)
    # Level 2: the git server's branch protection alone (no CI provider to consult).
    bare = ForgejoGit(settings)
    with pytest.raises(MergeRefused):
        bare.merge(mr)
    # ... and a raw API merge, bypassing both of our checks, is refused by the server.
    with pytest.raises(ProviderError):
        git._api.request(
            "POST",
            f"{git._repo_path(repo)}/pulls/{mr.number}/merge",
            json={"Do": "merge", "head_commit_id": mr.head_sha},
        )
    pull = git._api.request("GET", f"{git._repo_path(repo)}/pulls/{mr.number}")
    assert pull["merged"] is False
    assert pull["state"] == "open"


def test_default_branch_rejects_direct_pushes(git: ForgejoGit, repo) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ProviderError):
        git.commit_files(repo, "main", {"sneaky.txt": "x"}, "chore: direct push")
