import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_i18n


def write(root: Path, lang: str, name: str, data: dict[str, object]) -> None:
    (root / lang).mkdir(parents=True, exist_ok=True)
    (root / lang / name).write_text(json.dumps(data), encoding="utf-8")


def test_valid(tmp_path: Path) -> None:
    write(tmp_path, "fr", "common.json", {"a": {"b": "x"}})
    write(tmp_path, "en", "common.json", {"a": {"b": "y"}})
    assert check_i18n.check(tmp_path) == []


def test_missing_key(tmp_path: Path) -> None:
    write(tmp_path, "fr", "common.json", {"a": "x", "b": "x"})
    write(tmp_path, "en", "common.json", {"a": "y"})
    assert check_i18n.check(tmp_path) == ["en/common.json: key missing: b"]


def test_missing_file(tmp_path: Path) -> None:
    write(tmp_path, "fr", "common.json", {"a": "x"})
    write(tmp_path, "en", "other.json", {"a": "y"})
    errors = check_i18n.check(tmp_path)
    assert "en/common.json: file missing" in errors
    assert "fr/other.json: file missing" in errors


def test_empty_value(tmp_path: Path) -> None:
    write(tmp_path, "fr", "common.json", {"a": "x"})
    write(tmp_path, "en", "common.json", {"a": " "})
    assert check_i18n.check(tmp_path) == ["en/common.json: empty or non-string value: a"]
