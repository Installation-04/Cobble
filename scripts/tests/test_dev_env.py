import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dev_env


def test_creates_private_file_with_random_secrets(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    assert dev_env.ensure_env(path) is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    values = dict(line.split("=", 1) for line in path.read_text().splitlines())
    assert values["LITELLM_MASTER_KEY"].startswith("sk-cobble-")
    assert len(values["POSTGRES_PASSWORD"]) == 32
    assert values["POSTGRES_PASSWORD"] != values["REDIS_PASSWORD"]


def test_never_overwrites_existing_file(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("KEEP=me\n")
    assert dev_env.ensure_env(path) is False
    assert path.read_text() == "KEEP=me\n"


def test_two_runs_generate_different_secrets(tmp_path: Path) -> None:
    dev_env.ensure_env(tmp_path / "a")
    dev_env.ensure_env(tmp_path / "b")
    assert (tmp_path / "a").read_text() != (tmp_path / "b").read_text()
