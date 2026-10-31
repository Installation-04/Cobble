import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_no_hardcoded_colors as checker


def write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_clean_tree_and_token_file_are_allowed(tmp_path: Path) -> None:
    write(tmp_path, "styles/tokens.css", ":root { --background: #ffffff; --x: rgb(0 0 0 / 0.5); }")
    write(tmp_path, "App.tsx", '<div className="bg-background text-foreground border-border" />')
    assert checker.check(tmp_path) == []


@pytest.mark.parametrize(
    "snippet",
    [
        "color: #fff;",
        "color: #1D4ED8;",
        "background: rgb(1 2 3);",
        "background: rgba(1, 2, 3, 0.5);",
        "color: hsl(10 20% 30%);",
        "color: oklch(0.5 0.1 200);",
        '<div className="bg-red-500" />',
        '<div className="hover:text-gray-700" />',
        '<div className="bg-white" />',
        '<div className="border-black" />',
    ],
)
def test_offenders_are_reported(tmp_path: Path, snippet: str) -> None:
    write(tmp_path, "components/Thing.tsx", f"x\n{snippet}\n")
    errors = checker.check(tmp_path)
    assert len(errors) == 1
    assert errors[0].startswith("components/Thing.tsx:2:")


@pytest.mark.parametrize(
    "snippet",
    [
        '<div className="bg-background text-muted-foreground" />',
        "const id = 'user-#42';",
        "&#39; entity",
        '<div className="text-whitespace border-blackout" />',
        "const getRgba = 1;",
    ],
)
def test_false_positives_are_avoided(tmp_path: Path, snippet: str) -> None:
    write(tmp_path, "a.tsx", snippet)
    assert checker.check(tmp_path) == []


def test_token_file_only_exempt_at_its_path(tmp_path: Path) -> None:
    write(tmp_path, "other/tokens.css", ":root { --a: #fff; }")
    assert len(checker.check(tmp_path)) == 1


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path, "a.css", "a { color: #abc; }")
    assert checker.main(["prog", str(tmp_path)]) == 1
    assert "a.css:1" in capsys.readouterr().err
    write(tmp_path, "a.css", "a { color: var(--foreground); }")
    assert checker.main(["prog", str(tmp_path)]) == 0
