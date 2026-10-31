from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fake_llm.app import create_app
from fake_llm.cassettes import CassetteStore

REPO_CASSETTES = Path(__file__).resolve().parents[1] / "cassettes"


@pytest.fixture
def cassette_dir(tmp_path: Path) -> Path:
    (tmp_path / "default.json").write_text(
        json.dumps({"version": 1, "default": True, "response": {"content": "default reply here"}})
    )
    (tmp_path / "hi.json").write_text(
        json.dumps(
            {
                "version": 1,
                "request": {"model": "m", "messages": [{"role": "user", "content": "hi"}]},
                "response": {"content": "hello there friend"},
            }
        )
    )
    return tmp_path


@pytest.fixture
async def client(cassette_dir: Path) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(CassetteStore(cassette_dir))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://fake") as c:
        yield c
