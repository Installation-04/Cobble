"""scripts/dev_env.py: the module-manager settings are added without touching what exists."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "dev_env.py"


@pytest.fixture
def dev_env() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dev_env_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text("utf-8").splitlines() if "=" in line)


def test_a_new_environment_gets_a_module_manager_token_and_the_catalogue_path(
    tmp_path: Path, dev_env: ModuleType
) -> None:
    path = tmp_path / ".env"
    assert dev_env.main(["dev_env.py", str(path)]) == 0
    values = parse(path)
    assert len(values["MODULE_MANAGER_TOKEN"]) == 64
    assert values["COBBLE_CATALOG_DIR"].endswith("/catalog")
    assert values["POSTGRES_PASSWORD"]
    assert path.stat().st_mode & 0o777 == 0o600


def test_an_existing_environment_only_gains_what_is_missing(
    tmp_path: Path, dev_env: ModuleType
) -> None:
    path = tmp_path / ".env"
    path.write_text("POSTGRES_PASSWORD=keep-me\nMODULE_MANAGER_TOKEN=already-set\n")
    added = dev_env.ensure_module_settings(path)
    values = parse(path)
    assert values["POSTGRES_PASSWORD"] == "keep-me"
    assert values["MODULE_MANAGER_TOKEN"] == "already-set"
    assert "MODULE_MANAGER_TOKEN" not in added
    assert "COBBLE_CATALOG_DIR" in added


def test_running_it_twice_changes_nothing(tmp_path: Path, dev_env: ModuleType) -> None:
    path = tmp_path / ".env"
    dev_env.main(["dev_env.py", str(path)])
    first = path.read_text("utf-8")
    dev_env.main(["dev_env.py", str(path)])
    assert path.read_text("utf-8") == first
