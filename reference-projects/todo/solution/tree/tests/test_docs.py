from pathlib import Path

README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def test_the_readme_explains_how_to_start_the_application() -> None:
    assert "uv run uvicorn app.main:app" in README
    assert "pnpm build" in README


def test_the_readme_explains_how_to_run_the_tests() -> None:
    assert "uv run pytest" in README
    assert "pnpm --dir frontend test" in README


def test_the_readme_tells_where_the_data_is_kept() -> None:
    assert "TODO_DB" in README
