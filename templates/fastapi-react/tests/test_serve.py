from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import seed, serve

ROOT = Path(__file__).resolve().parents[1]


def make_app(tmp_path: Path) -> tuple[FastAPI, Path]:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text('<script src="./assets/app.js"></script>', "utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", "utf-8")
    application = FastAPI()

    @application.get("/api/ping")
    def ping() -> dict[str, str]:
        return {"pong": "yes"}

    return application, static


def test_frontend_is_served_after_the_api(tmp_path: Path) -> None:
    application, static = make_app(tmp_path)
    assert serve.mount_frontend(application, static)
    assert serve.mount_frontend(application, static)  # mounting twice changes nothing
    client = TestClient(application)
    assert client.get("/api/ping").json() == {"pong": "yes"}
    assert "./assets/app.js" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200


def test_no_static_directory_means_api_only(tmp_path: Path) -> None:
    assert not serve.mount_frontend(FastAPI(), tmp_path / "missing")


def test_seed_runs_once_per_data_directory(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[int] = []
    monkeypatch.setattr(seed, "seed", lambda: calls.append(1))
    assert serve.seed_once(tmp_path / "data") is True
    assert serve.seed_once(tmp_path / "data") is False
    assert calls == [1]


def test_template_is_ready_for_the_demo_prefix_and_runs_unprivileged() -> None:
    vite = (ROOT / "frontend" / "vite.config.ts").read_text("utf-8")
    assert 'base: "./"' in vite  # relative asset URLs work under /demo/<project>/<milestone>/
    dockerfile = (ROOT / "Dockerfile").read_text("utf-8")
    assert "USER 10001" in dockerfile and "--mount" not in dockerfile
