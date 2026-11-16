"""Fixtures for the local API tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from dd_agents.api.app import create_app

if TYPE_CHECKING:
    from collections.abc import Iterator

TOKEN = "test-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BASE = "http://127.0.0.1:8765"

VALID_CONFIG: dict[str, Any] = json.loads(
    (Path(__file__).parents[2] / "fixtures" / "deal_config_valid.json").read_text(encoding="utf-8")
)


@pytest.fixture
def registry_dir(tmp_path: Path) -> Path:
    return tmp_path / "registry"


@pytest.fixture
def data_room(tmp_path: Path) -> Path:
    room = tmp_path / "room"
    room.mkdir()
    (room / "contract.txt").write_text("Subject A agreement", encoding="utf-8")
    return room


@pytest.fixture
def client(registry_dir: Path) -> Iterator[TestClient]:
    app = create_app(token=TOKEN, registry_dir=registry_dir)
    with TestClient(app, base_url=BASE, headers=AUTH) as c:
        yield c
