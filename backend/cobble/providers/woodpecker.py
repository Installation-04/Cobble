"""CIProvider backed by Woodpecker (the `woodpecker` module)."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from cobble.capabilities import CIState, CIStatus, RepoRef

from .errors import ProviderError, ProviderNotFound
from .http import Api
from .settings import PackSettings

_SHA = re.compile(r"^[0-9a-f]{7,40}$")
_PENDING = {"created", "pending", "running", "blocked"}
_SUCCESS = {"success"}
# failure, error, killed, declined and skipped: nothing proves the change is good.
_PIPELINES_PER_PAGE = 50


class WoodpeckerCI:
    def __init__(
        self,
        settings: PackSettings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._api = Api(
            f"{settings.woodpecker_url.rstrip('/')}/api",
            settings.woodpecker_token.get_secret_value(),
            service="ci",
            auth_scheme="Bearer",
            timeout=settings.http_timeout_s,
            transport=transport,
        )
        self._sleep = sleep
        self._clock = clock

    def close(self) -> None:
        self._api.close()

    @staticmethod
    def _full_name(repo: RepoRef) -> str:
        parts = [p for p in urlsplit(repo.clone_url).path.removesuffix(".git").split("/") if p]
        if len(parts) < 2:
            raise ProviderError(f"unexpected repository URL for {repo.name}")
        return f"{parts[-2]}/{parts[-1]}"

    def _lookup(self, repo: RepoRef) -> dict[str, Any] | None:
        try:
            found = self._api.request("GET", f"/repos/lookup/{self._full_name(repo)}")
        except ProviderNotFound:
            return None
        return found if isinstance(found, dict) else None

    def _repo_id(self, repo: RepoRef) -> int:
        found = self._lookup(repo)
        if found is None:
            raise ProviderNotFound(f"CI is not enabled for {repo.name}", status=404)
        return int(found["id"])

    # -- CIProvider --------------------------------------------------------------------

    def activate(self, repo: RepoRef) -> None:
        """Enable CI on the repository (Woodpecker then registers the webhook itself).
        Safe to call again: settings are re-applied."""
        found = self._lookup(repo)
        if found is None:
            full_name = self._full_name(repo)
            listing = self._api.request(
                "GET", "/user/repos", params={"all": "true", "reload": "true"}
            )
            match = next((r for r in listing if r.get("full_name") == full_name), None)
            if match is None:
                raise ProviderNotFound(f"{full_name} is unknown to the CI server", status=404)
            found = self._api.request(
                "POST", "/repos", params={"forge_remote_id": str(match["forge_remote_id"])}
            )
        self._api.request(
            "PATCH",
            f"/repos/{found['id']}",
            json={
                "allow_pr": True,
                # Never trusted: pipelines get no privileged mode, no host volumes.
                "trusted": {"network": False, "volumes": False, "security": False},
                "timeout": 30,
                "cancel_previous_pipeline_events": ["push", "pull_request"],
            },
        )

    def status(self, repo: RepoRef, ref: str) -> CIStatus:
        """State of the latest pipeline for `ref`: a commit sha or a branch name."""
        try:
            repo_id = self._repo_id(repo)
        except ProviderNotFound:
            return CIStatus(CIState.PENDING, "CI is not enabled for this repository")
        pipelines = self._api.request(
            "GET",
            f"/repos/{repo_id}/pipelines",
            params={"page": 1, "perPage": _PIPELINES_PER_PAGE},
        )
        for pipeline in sorted(pipelines or [], key=lambda p: int(p["number"]), reverse=True):
            if self._matches(pipeline, ref):
                return self._to_status(pipeline)
        return CIStatus(CIState.PENDING, "no pipeline yet")

    @staticmethod
    def _matches(pipeline: dict[str, Any], ref: str) -> bool:
        commit = str(pipeline.get("commit") or "")
        if _SHA.match(ref):
            return bool(commit) and commit.startswith(ref)
        # Pull request pipelines carry "source:target" in refspec, push ones "branch:branch".
        source = str(pipeline.get("refspec") or "").split(":", 1)[0]
        return ref in (source, str(pipeline.get("branch") or ""))

    @staticmethod
    def _to_status(pipeline: dict[str, Any]) -> CIStatus:
        raw = str(pipeline.get("status") or "")
        detail = f"pipeline #{pipeline['number']} {raw}"
        if raw in _SUCCESS:
            return CIStatus(CIState.SUCCESS, detail)
        if raw in _PENDING:
            return CIStatus(CIState.PENDING, detail)
        return CIStatus(CIState.FAILURE, detail)

    def wait(self, repo: RepoRef, ref: str, timeout_s: float) -> CIStatus:
        deadline = self._clock() + timeout_s
        status = self.status(repo, ref)
        while status.state is CIState.PENDING and self._clock() < deadline:
            self._sleep(self.settings.ci_poll_interval_s)
            status = self.status(repo, ref)
        return status
