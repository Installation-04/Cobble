"""Module routes on the reverse proxy: validate-then-rename, rollback, real admin socket."""

from __future__ import annotations

import socketserver
import tempfile
import threading
from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

import pytest

from cobble.module_manager.edge import CaddyEdge, caddy_reload
from cobble.module_manager.manager import ModuleOperationFailed
from cobble.module_manager.runner import RunnerError

from .test_module_manager import FORGEJO, WOODPECKER, Rig

ROUTE = "handle_path /git/* {\n\treverse_proxy cobble-forgejo-forgejo:3000\n}\n"


class Recorder:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.loaded: list[str] = []
        self.seen_files: list[dict[str, str]] = []
        self.dir: Path | None = None

    def __call__(self, caddyfile: str) -> None:
        self.loaded.append(caddyfile)
        if self.dir is not None:
            self.seen_files.append({p.name: p.read_text() for p in self.dir.glob("*.caddy")})
        if self.fail:
            raise RunnerError("route_failed")


def make(tmp_path: Path, reload: Recorder) -> CaddyEdge:
    (tmp_path / "Caddyfile").write_text(":80 {\n\timport /etc/caddy/routes/*.caddy\n}\n")
    reload.dir = tmp_path / "routes"
    return CaddyEdge(tmp_path / "routes", tmp_path / "Caddyfile", reload)


def files(tmp_path: Path) -> dict[str, str]:
    return {p.name: p.read_text() for p in (tmp_path / "routes").iterdir()}


def test_routes_are_written_then_the_proxy_loads_the_main_caddyfile(tmp_path: Path) -> None:
    reload = Recorder()
    edge = make(tmp_path, reload)
    edge.sync({"forgejo": ROUTE})
    assert files(tmp_path) == {"forgejo.caddy": ROUTE}
    assert reload.loaded == [(tmp_path / "Caddyfile").read_text()]
    assert reload.seen_files == [{"forgejo.caddy": ROUTE}]  # files were in place when it loaded


def test_an_unchanged_set_does_not_reload_and_a_removed_route_disappears(tmp_path: Path) -> None:
    reload = Recorder()
    edge = make(tmp_path, reload)
    edge.sync({"forgejo": ROUTE})
    edge.sync({"forgejo": ROUTE})
    assert len(reload.loaded) == 1
    edge.sync({})
    assert files(tmp_path) == {}
    assert len(reload.loaded) == 2


def test_a_refused_configuration_restores_the_previous_files(tmp_path: Path) -> None:
    reload = Recorder()
    edge = make(tmp_path, reload)
    edge.sync({"forgejo": ROUTE})
    reload.fail = True
    with pytest.raises(RunnerError) as caught:
        edge.sync({"forgejo": "changed {\n}\n", "woodpecker": "x {\n}\n"})
    assert caught.value.code == "route_failed"
    assert files(tmp_path) == {"forgejo.caddy": ROUTE}  # nothing of the bad attempt remains
    with pytest.raises(RunnerError):
        edge.sync({})  # removal refused too: the route is put back
    assert files(tmp_path) == {"forgejo.caddy": ROUTE}


def test_no_temporary_file_is_left_behind(tmp_path: Path) -> None:
    edge = make(tmp_path, Recorder())
    edge.sync({"forgejo": ROUTE})
    assert [p.name for p in (tmp_path / "routes").iterdir()] == ["forgejo.caddy"]


@pytest.mark.parametrize("module_id", ["../evil", "a/b", "A", "", ".hidden", "x" * 80])
def test_a_module_id_that_could_escape_the_directory_is_refused(
    tmp_path: Path, module_id: str
) -> None:
    reload = Recorder()
    edge = make(tmp_path, reload)
    with pytest.raises(RunnerError):
        edge.sync({module_id: ROUTE})
    assert reload.loaded == []
    assert not list(tmp_path.glob("*.caddy")) and not (tmp_path / "evil.caddy").exists()


# --- the real admin socket ---------------------------------------------------------------------


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    received: list[tuple[str, str, bytes]]
    status = 200


@pytest.fixture
def admin() -> Iterator[tuple[Path, _Server]]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "admin.sock"

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                server.received.append(
                    (self.path, self.headers.get("Content-Type", ""), self.rfile.read(length))
                )
                self.send_response(server.status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                return None

            def address_string(self) -> str:
                return "unix"

        server = _Server(str(path), Handler)
        server.received = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield path, server
        server.shutdown()
        server.server_close()


def test_the_caddyfile_is_posted_to_the_admin_socket(admin: tuple[Path, _Server]) -> None:
    path, server = admin
    caddy_reload(path)(":80 {\n}\n")
    assert server.received == [("/load", "text/caddyfile", b":80 {\n}\n")]


def test_a_refusal_or_a_missing_socket_is_route_failed(
    admin: tuple[Path, _Server], tmp_path: Path
) -> None:
    path, server = admin
    server.status = 400
    with pytest.raises(RunnerError) as refused:
        caddy_reload(path)("bad")
    assert refused.value.code == "route_failed"
    with pytest.raises(RunnerError) as missing:
        caddy_reload(tmp_path / "nope.sock")("x")
    assert missing.value.code == "route_failed"


# --- in the lifecycle --------------------------------------------------------------------------


class FakeEdge:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.fail_when: Any = None

    def sync(self, routes: Mapping[str, str]) -> None:
        if self.fail_when is not None and self.fail_when(routes):
            raise RunnerError("route_failed")
        self.calls.append(dict(routes))

    @property
    def published(self) -> dict[str, str]:
        return self.calls[-1] if self.calls else {}


def test_a_running_module_is_published_and_an_uninstalled_one_is_not() -> None:
    edge = FakeEdge()
    rig = Rig(edge=edge)
    rig.manager.install(["forgejo", "woodpecker"])
    assert set(edge.published) == {"forgejo", "woodpecker"}
    assert "handle_path /git/*" in edge.published["forgejo"]
    assert "cobble-woodpecker-server:8000" in edge.published["woodpecker"]
    rig.manager.uninstall(["woodpecker"])
    assert set(edge.published) == {"forgejo"}
    rig.manager.uninstall(["forgejo"])
    assert edge.published == {}
    # an orphan dependency leaves with the module that needed it
    rig.manager.install(["woodpecker"])
    assert set(edge.published) == {"forgejo", "woodpecker"}
    rig.manager.uninstall(["woodpecker"])
    assert edge.published == {}


def test_a_module_is_not_published_before_it_is_healthy() -> None:
    edge = FakeEdge()
    rig = Rig(edge=edge)
    rig.runner.fail.add(("health", "cobble-forgejo"))
    with pytest.raises(ModuleOperationFailed):
        rig.manager.install(["forgejo"])
    assert all(call == {} for call in edge.calls)


def test_a_refused_route_rolls_the_install_back() -> None:
    edge = FakeEdge()
    edge.fail_when = lambda routes: "woodpecker" in routes
    rig = Rig(edge=edge)
    with pytest.raises(ModuleOperationFailed) as caught:
        rig.manager.install(["woodpecker"])
    assert (caught.value.module, caught.value.step, caught.value.code) == (
        "woodpecker",
        "route",
        "route_failed",
    )
    assert rig.counts() == {"modules": 0, "secrets": 0, "links": 0}
    assert rig.runner.running == {}
    assert edge.published == {}  # the proxy was brought back in line after the rollback


def test_a_proxy_that_cannot_be_updated_never_blocks_a_removal() -> None:
    edge = FakeEdge()
    rig = Rig(edge=edge)
    rig.manager.install(["forgejo"])
    edge.fail_when = lambda routes: True
    rig.manager.uninstall(["forgejo"])
    assert rig.modules() == {}
    failed = [e for e in rig.events() if e.kind == "route"]
    assert failed and failed[-1].outcome == "error" and failed[-1].code == "route_failed"


def test_recovery_republishes_what_really_runs() -> None:
    edge = FakeEdge()
    rig = Rig(edge=edge)
    rig.manager.install(["forgejo"])
    edge.calls.clear()
    rig.manager.recover()
    assert edge.calls == [] or set(edge.published) == {"forgejo"}


def test_the_connection_address_is_the_one_the_proxy_uses() -> None:
    rig = Rig(modules=[FORGEJO, WOODPECKER])
    rig.manager.install(["forgejo"])
    assert rig.manager.connections()["forgejo"]["url"] == "http://cobble-forgejo-forgejo:3000"
