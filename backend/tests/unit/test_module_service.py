"""The module-manager service: HTTP API, operations, events, disk catalogue, start-up."""

from __future__ import annotations

import json
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from cobble_sdk import Hardware
from fastapi.testclient import TestClient

from cobble.config import Settings
from cobble.module_manager.__main__ import build_app, main
from cobble.module_manager.app import create_app
from cobble.module_manager.disk_catalog import DiskCatalog
from cobble.module_manager.hardware import detect_gpu, host_hardware, read_ram_mb
from cobble.module_manager.runner import ComposeRunner, RunnerError
from cobble.module_manager.service import OperationController
from cobble.module_manager.vault import VaultError

from .test_module_manager import (
    FORGEJO,
    GITEA,
    GPU_ONLY,
    OLLAMA,
    SCRIPTS,
    WOODPECKER,
    Rig,
)

TOKEN = "service-token-for-tests"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class Service:
    def __init__(self, rig: Rig | None = None, defer: bool = False) -> None:
        self.rig = rig or Rig()
        self.published: list[tuple[str, dict[str, Any]]] = []
        self.deferred: list[Callable[[], None]] = []
        spawn = self.deferred.append if defer else (lambda job: job())
        self.controller = OperationController(
            lambda kind, payload: self.published.append((kind, payload)), spawn
        )
        # The rig's manager was built without a sink: rebuild it so steps reach the controller.
        from cobble.module_manager.manager import ModuleManager

        self.rig.manager = ModuleManager(
            self.rig.sessions,
            self.rig.catalog,
            self.rig.runner,
            self.rig.store,
            self.rig.manager._hardware,
            on_event=self.controller.on_step,
        )
        self.controller.bind(self.rig.manager)
        self.client = TestClient(create_app(self.controller, TOKEN))

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self.client.post(path, json=body, headers=AUTH)

    def get(self, path: str) -> Any:
        return self.client.get(path, headers=AUTH)


# --- authentication ---------------------------------------------------------------------------


def test_health_is_open_and_everything_else_needs_the_token() -> None:
    svc = Service()
    assert svc.client.get("/healthz").json() == {"status": "ok"}
    for path in ("/v1/catalog", "/v1/modules/forgejo/secrets", "/v1/operations/x"):
        assert svc.client.get(path).status_code == 401
        assert svc.client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert svc.client.get(path, headers={"Authorization": TOKEN}).status_code == 401
    for path in ("/v1/plan", "/v1/operations"):
        assert (
            svc.client.post(path, json={"action": "install", "modules": ["forgejo"]}).status_code
            == 401
        )
    body = svc.client.get("/v1/catalog").json()
    assert body == {"error": {"code": "unauthorized", "params": {}}}


def test_an_empty_token_never_authenticates() -> None:
    svc = Service()
    client = TestClient(create_app(svc.controller, ""))
    assert client.get("/v1/catalog", headers={"Authorization": "Bearer "}).status_code == 401


# --- catalogue --------------------------------------------------------------------------------


def test_the_catalogue_shows_modules_their_fit_and_their_state() -> None:
    svc = Service(Rig([FORGEJO, WOODPECKER, GPU_ONLY], Hardware(ram_mb=8192)))
    svc.post("/v1/operations", {"action": "install", "modules": ["forgejo"]})
    body = svc.get("/v1/catalog").json()
    assert body["hardware"] == {"ram_mb": 8192, "gpu": "none"}
    by_id = {m["id"]: m for m in body["modules"]}
    assert set(by_id) == {"forgejo", "woodpecker", "gpu-only"}
    assert by_id["forgejo"]["installed"]["state"] == "running"
    assert by_id["woodpecker"]["installed"] is None
    assert by_id["woodpecker"]["requires"] == ["git"]
    assert by_id["forgejo"]["description"] == {"fr": "Module de test", "en": "Test module"}
    assert by_id["forgejo"]["hardware"]["ok"] is True
    gpu = by_id["gpu-only"]["hardware"]
    assert gpu["ok"] is False
    assert gpu["problems"] == [{"code": "gpu", "needed": "nvidia", "have": "none"}]


def test_the_catalogue_reports_the_chosen_variant() -> None:
    svc = Service(Rig([OLLAMA], Hardware(ram_mb=16384, gpu="nvidia")))
    ollama = svc.get("/v1/catalog").json()["modules"][0]
    assert ollama["hardware"]["variant"] == "nvidia"
    assert ollama["variants"] == ["nvidia", "cpu"]


# --- planning and refusals --------------------------------------------------------------------


def test_a_plan_is_a_preview_that_changes_nothing() -> None:
    svc = Service()
    plan = svc.post("/v1/plan", {"action": "install", "modules": ["woodpecker"]}).json()
    assert [s["module"] for s in plan["steps"]] == ["forgejo", "woodpecker"]
    assert plan["auto_added"] == ["forgejo"]
    assert plan["links_added"] == [
        {"consumer": "woodpecker", "provider": "forgejo", "capability": "git"}
    ]
    assert svc.rig.counts() == {"modules": 0, "secrets": 0, "links": 0}
    assert svc.rig.runner.calls == []


def refusal(
    svc: Service, path: str, body: dict[str, Any], status: int, code: str
) -> dict[str, Any]:
    response = svc.post(path, body)
    assert response.status_code == status, response.text
    error = response.json()["error"]
    assert error["code"] == code
    return error["params"]  # type: ignore[no-any-return]


def test_every_planning_refusal_has_a_status_a_code_and_the_data_to_ask_again() -> None:
    svc = Service(Rig([FORGEJO, GITEA, WOODPECKER, GPU_ONLY]))
    install = {"action": "install", "modules": ["woodpecker"]}
    params = refusal(svc, "/v1/plan", install, 409, "module_needs_choice")
    assert params == {"capability": "git", "candidates": ["forgejo", "gitea"]}
    assert svc.post("/v1/plan", {**install, "choices": {"git": "gitea"}}).status_code == 200
    refusal(
        svc, "/v1/plan", {**install, "choices": {"git": "woodpecker"}}, 422, "module_invalid_choice"
    )
    refusal(svc, "/v1/plan", {"action": "install", "modules": ["nope"]}, 404, "module_unknown")
    refusal(
        svc,
        "/v1/plan",
        {"action": "uninstall", "modules": ["forgejo"]},
        404,
        "module_not_installed",
    )


def test_a_module_that_cannot_run_here_is_refused_with_the_reasons() -> None:
    svc = Service(Rig([GPU_ONLY], Hardware(ram_mb=4096)))
    # the plan itself is fine; the hardware verdict is reported by the catalogue (greyed out in
    # the Store) and enforced when the module is installed
    assert svc.post("/v1/plan", {"action": "install", "modules": ["gpu-only"]}).status_code == 200
    accepted = svc.post("/v1/operations", {"action": "install", "modules": ["gpu-only"]})
    operation = svc.get(f"/v1/operations/{accepted.json()['operation_id']}").json()
    assert (operation["state"], operation["error"]["step"], operation["error"]["code"]) == (
        "failed",
        "hardware",
        "no_compatible_variant",
    )


def test_conflict_cascade_and_hardware_refusals() -> None:
    svc = Service(Rig([FORGEJO, GITEA, WOODPECKER, GPU_ONLY]))
    svc.post("/v1/operations", {"action": "install", "modules": ["forgejo", "woodpecker"]})
    params = refusal(
        svc, "/v1/plan", {"action": "install", "modules": ["gitea"]}, 409, "module_conflict"
    )
    assert params["capability"] == "git"
    assert params["modules"] == ["forgejo", "gitea"]
    params = refusal(
        svc,
        "/v1/plan",
        {"action": "uninstall", "modules": ["forgejo"]},
        409,
        "module_needs_confirmation",
    )
    assert params == {"cascade": ["woodpecker"]}
    ok = svc.post(
        "/v1/plan", {"action": "uninstall", "modules": ["forgejo"], "confirm_cascade": True}
    )
    assert ok.status_code == 200
    assert ok.json()["cascade"] == ["woodpecker"]


def test_a_request_with_nothing_to_do_or_nonsense_is_rejected() -> None:
    svc = Service()
    for body in (
        {"action": "install", "modules": []},
        {"action": "explode", "modules": ["forgejo"]},
        {"modules": ["forgejo"]},
    ):
        response = svc.post("/v1/plan", body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_request"


# --- operations -------------------------------------------------------------------------------


def test_an_operation_is_accepted_runs_and_reports_its_plan() -> None:
    svc = Service()
    response = svc.post("/v1/operations", {"action": "install", "modules": ["woodpecker"]})
    assert response.status_code == 202
    operation = svc.get(f"/v1/operations/{response.json()['operation_id']}").json()
    assert operation["state"] == "done"
    assert operation["error"] is None
    assert [s["module"] for s in operation["plan"]["steps"]] == ["forgejo", "woodpecker"]
    assert set(svc.rig.modules()) == {"forgejo", "woodpecker"}
    assert svc.get("/v1/operations/unknown").status_code == 404


def test_a_failed_operation_says_where_and_why_and_leaves_nothing() -> None:
    svc = Service()
    svc.rig.runner.fail.add(("up", "cobble-woodpecker"))
    accepted = svc.post("/v1/operations", {"action": "install", "modules": ["woodpecker"]})
    assert accepted.status_code == 202  # the failure is reported by the operation, not the request
    operation = svc.get(f"/v1/operations/{accepted.json()['operation_id']}").json()
    assert operation["state"] == "failed"
    assert operation["error"] == {
        "module": "woodpecker",
        "step": "up",
        "code": "up_failed",
        "rolled_back": ["woodpecker", "forgejo"],
        "partial": False,
    }
    assert svc.rig.counts() == {"modules": 0, "secrets": 0, "links": 0}


def test_only_one_operation_runs_at_a_time() -> None:
    svc = Service(defer=True)
    first = svc.post("/v1/operations", {"action": "install", "modules": ["forgejo"]})
    assert first.status_code == 202
    assert svc.get(f"/v1/operations/{first.json()['operation_id']}").json()["state"] == "running"
    busy = svc.post("/v1/operations", {"action": "install", "modules": ["woodpecker"]})
    assert busy.status_code == 409
    assert busy.json()["error"]["code"] == "module_busy"
    svc.deferred.pop()()  # the first operation finishes
    assert (
        svc.post("/v1/operations", {"action": "install", "modules": ["woodpecker"]}).status_code
        == 202
    )


def test_a_refused_request_does_not_leave_the_service_busy() -> None:
    svc = Service(Rig([FORGEJO, GITEA, WOODPECKER]), defer=True)
    assert (
        svc.post("/v1/operations", {"action": "install", "modules": ["woodpecker"]}).status_code
        == 409
    )
    assert (
        svc.post("/v1/operations", {"action": "install", "modules": ["forgejo"]}).status_code == 202
    )


def test_progress_events_carry_the_operation_and_never_a_secret() -> None:
    svc = Service()
    svc.rig.runner.hook_secrets[SCRIPTS["register"]] = {"service_token": "tok-from-the-hook-123"}
    operation_id = svc.post(
        "/v1/operations", {"action": "install", "modules": ["woodpecker"]}
    ).json()["operation_id"]
    kinds = [kind for kind, _ in svc.published]
    assert kinds[0] == "module.operation"
    assert kinds[-1] == "module.operation"
    steps = [p for kind, p in svc.published if kind == "module.step"]
    assert steps
    assert all(p["operation_id"] == operation_id for p in steps)
    assert {"module", "kind", "step", "ok", "code"} <= set(steps[0])
    assert svc.published[0][1] == {"operation_id": operation_id, "state": "running"}
    assert svc.published[-1][1]["state"] == "done"
    with svc.rig.sessions() as session:
        secrets = [
            v.reveal()
            for module, key in [
                ("forgejo", "api_token"),
                ("forgejo", "service_token"),
                ("woodpecker", "agent_secret"),
            ]
            if (v := svc.rig.store.get(session, module, key)) is not None
        ]
    assert len(secrets) == 3
    assert not any(secret in json.dumps(svc.published) for secret in secrets)


def test_a_sink_that_fails_never_breaks_an_operation() -> None:
    svc = Service()

    def broken(_event: dict[str, Any]) -> None:
        raise RuntimeError("redis is down")

    svc.rig.manager._on_event = broken
    response = svc.post("/v1/operations", {"action": "install", "modules": ["forgejo"]})
    assert svc.get(f"/v1/operations/{response.json()['operation_id']}").json()["state"] == "done"


# --- secrets ----------------------------------------------------------------------------------


def test_secret_status_says_set_or_not_and_nothing_else() -> None:
    svc = Service()
    svc.post("/v1/operations", {"action": "install", "modules": ["forgejo"]})
    response = svc.get("/v1/modules/forgejo/secrets")
    assert response.json() == {"admin_password": True, "api_token": True}
    with svc.rig.sessions() as session:
        value = svc.rig.store.get(session, "forgejo", "api_token")
    assert value is not None
    assert value.reveal() not in response.text
    assert svc.get("/v1/modules/nope/secrets").json()["error"]["code"] == "module_unknown"


def test_connections_give_the_core_its_address_and_only_its_secrets() -> None:
    svc = Service()
    assert svc.get("/v1/connections").json() == {"connections": {}}
    svc.post("/v1/operations", {"action": "install", "modules": ["forgejo"]})
    connections = svc.get("/v1/connections").json()["connections"]
    assert set(connections) == {"forgejo"}
    with svc.rig.sessions() as session:
        token = svc.rig.store.get(session, "forgejo", "api_token")
        password = svc.rig.store.get(session, "forgejo", "admin_password")
    assert token is not None and password is not None
    assert connections["forgejo"] == {
        "provides": ["git"],
        "url": "http://cobble-forgejo-forgejo:3000",
        "secrets": {"api_token": token.reveal()},
    }
    assert password.reveal() not in json.dumps(connections)


def test_connections_need_the_token_and_skip_modules_that_are_not_running() -> None:
    svc = Service()
    assert svc.client.get("/v1/connections").status_code == 401
    svc.post("/v1/operations", {"action": "install", "modules": ["forgejo"]})
    svc.post("/v1/operations", {"action": "uninstall", "modules": ["forgejo"]})
    assert svc.get("/v1/connections").json() == {"connections": {}}


# --- hardware ---------------------------------------------------------------------------------


def test_ram_is_read_from_meminfo(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemFree: 1 kB\nMemTotal:       16384000 kB\n")
    assert read_ram_mb(meminfo) == 16000
    assert read_ram_mb(tmp_path / "missing") == 0
    meminfo.write_text("garbage\n")
    assert read_ram_mb(meminfo) == 0


def test_the_gpu_is_detected_from_device_nodes(tmp_path: Path) -> None:
    dev, proc = tmp_path / "dev", tmp_path / "proc"
    dev.mkdir()
    proc.mkdir()
    assert detect_gpu(dev, proc) == "none"
    (dev / "kfd").touch()
    assert detect_gpu(dev, proc) == "none"  # /dev/kfd alone is not enough
    (dev / "dri").mkdir()
    assert detect_gpu(dev, proc) == "amd"
    (dev / "nvidiactl").touch()
    assert detect_gpu(dev, proc) == "nvidia"


def test_settings_override_detection(tmp_path: Path) -> None:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 2048000 kB\n")
    assert host_hardware(0, "auto", meminfo=meminfo, dev=tmp_path, proc=tmp_path) == Hardware(
        2000, "none"
    )
    assert host_hardware(8192, "nvidia", meminfo=meminfo) == Hardware(8192, "nvidia")


# --- the catalogue on disk --------------------------------------------------------------------


def write_module(root: Path, module_id: str, manifest_id: str | None = None, **extra: Any) -> None:
    directory = root / module_id
    directory.mkdir(parents=True)
    data = {
        "id": manifest_id or module_id,
        "name": module_id,
        "version": "1.0.0",
        "category": "test",
        "description": {"fr": "x", "en": "x"},
        "license": "MIT",
        "images": ["example.org/x:1@sha256:" + "e" * 64],
        **extra,
    }
    (directory / "manifest.yaml").write_text(yaml.safe_dump(data))


def test_the_disk_catalogue_lists_valid_modules_and_reports_the_others(tmp_path: Path) -> None:
    write_module(tmp_path, "good")
    write_module(tmp_path, "mismatch", manifest_id="other")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "manifest.yaml").write_text("id: broken\nnonsense: true\n")
    (tmp_path / "empty").mkdir()
    (tmp_path / "README.md").write_text("not a module")
    catalog = DiskCatalog(tmp_path, lambda *a: {})
    assert set(catalog.manifests()) == {"good"}
    problems = catalog.problems()
    assert set(problems) == {"mismatch", "broken"}
    assert any("does not match" in p for p in problems["mismatch"])
    assert DiskCatalog(tmp_path / "absent", lambda *a: {}).manifests() == {}


def test_the_disk_catalogue_renders_the_compose_file_of_the_module(tmp_path: Path) -> None:
    write_module(tmp_path, "good", compose="stack.yml")
    seen: list[tuple[Any, ...]] = []

    def render(module_dir: str, compose_file: str, env: Any, variant: str | None) -> dict[str, Any]:
        seen.append((module_dir, compose_file, dict(env), variant))
        return {"services": {}}

    catalog = DiskCatalog(tmp_path, render)
    assert catalog.module_dir("good") == str(tmp_path / "good")
    catalog.compose("good", "cpu", {"COBBLE_SECRET_X": "v"})
    assert seen == [(str(tmp_path / "good"), "stack.yml", {"COBBLE_SECRET_X": "v"}, "cpu")]


def test_compose_runner_render(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'echo "$@" > "$STUB_DIR/args"\n'
        '[ -f "$STUB_DIR/out" ] && cat "$STUB_DIR/out"\n'
        '[ -f "$STUB_DIR/exit" ] && exit "$(cat "$STUB_DIR/exit")"\n'
        "exit 0\n"
    )
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("STUB_DIR", str(tmp_path))
    runner = ComposeRunner(str(docker))
    (tmp_path / "out").write_text('{"services": {"a": {}}}')
    assert runner.render("/m/x", "compose.yml", {}, "cpu") == {"services": {"a": {}}}
    args = (tmp_path / "args").read_text()
    assert "--project-directory /m/x -f /m/x/compose.yml --profile cpu config --format json" in args
    (tmp_path / "out").write_text("not json")
    with pytest.raises(RunnerError) as bad_json:
        runner.render("/m/x", "compose.yml", {})
    assert bad_json.value.code == "render_failed"
    (tmp_path / "exit").write_text("1")
    with pytest.raises(RunnerError):
        runner.render("/m/x", "compose.yml", {})


# --- start-up ---------------------------------------------------------------------------------


class FakeRedis:
    def xadd(self, *args: Any, **kwargs: Any) -> str:
        return "1-0"


def settings_for(tmp_path: Path, **changes: Any) -> Settings:
    base: dict[str, Any] = {
        "database_url": "sqlite://",
        "module_manager_token": TOKEN,
        "module_master_key_file": str(tmp_path / "keys" / "master.key"),
        "module_catalog_dir": str(tmp_path / "catalog"),
        "module_ram_mb": 4096,
        "module_gpu": "none",
    }
    return Settings(**{**base, **changes})


def test_the_first_start_creates_the_master_key_privately(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    app, _manager = build_app(settings, FakeRedis())  # type: ignore[arg-type]
    key = Path(settings.module_master_key_file)
    assert key.stat().st_mode & 0o777 == 0o600
    first = key.read_bytes()
    build_app(settings, FakeRedis())  # type: ignore[arg-type]
    assert key.read_bytes() == first  # a restart never replaces the key
    assert TestClient(app).get("/healthz").status_code == 200


def test_a_key_that_others_can_read_stops_the_service(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    build_app(settings, FakeRedis())  # type: ignore[arg-type]
    Path(settings.module_master_key_file).chmod(0o644)
    with pytest.raises(VaultError) as info:
        build_app(settings, FakeRedis())  # type: ignore[arg-type]
    assert info.value.code == "key_file_permissions"


def test_the_service_refuses_to_start_without_a_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cobble.module_manager.__main__.get_settings",
        lambda: settings_for(tmp_path, module_manager_token=""),
    )
    assert main() == 78
    assert not (tmp_path / "keys").exists()  # nothing was created


def test_the_public_url_becomes_platform_variables_for_modules() -> None:
    from cobble.module_manager.__main__ import docker_gid, public_env

    assert public_env("http://192.168.1.20:8080/") == {
        "COBBLE_PUBLIC_URL": "http://192.168.1.20:8080",
        "COBBLE_PUBLIC_HOST": "192.168.1.20",
        "COBBLE_PUBLIC_PORT": "8080",
        "COBBLE_GATEWAY_ALIAS": "cobble-gateway",  # an address: pipelines reach it directly
    }
    named = public_env("https://cobble.example.org")
    assert named["COBBLE_PUBLIC_HOST"] == "cobble.example.org"
    assert named["COBBLE_PUBLIC_PORT"] == "443"
    assert (
        named["COBBLE_GATEWAY_ALIAS"] == "cobble.example.org"
    )  # a name: the gateway answers to it
    assert public_env("http://nas.local")["COBBLE_PUBLIC_PORT"] == "80"
    assert public_env("http://localhost:8080")["COBBLE_GATEWAY_ALIAS"] == "cobble-gateway"
    assert public_env("")["COBBLE_PUBLIC_URL"] == "http://localhost"
    assert docker_gid("/definitely/not/there") == "0"
    assert docker_gid("/") == str(__import__("os").stat("/").st_gid)


def test_extra_platform_variables_are_a_json_object_of_cobble_variables() -> None:
    from cobble.module_manager.__main__ import extra_env

    assert extra_env("") == {} and extra_env("  ") == {}
    assert extra_env('{"COBBLE_SKIP_STEPS": "trivy"}') == {"COBBLE_SKIP_STEPS": "trivy"}
    for bad in ('["x"]', '{"PATH": "/evil"}', '{"COBBLE_X": 1}', "not json"):
        with pytest.raises(ValueError):
            extra_env(bad)
