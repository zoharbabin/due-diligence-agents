"""Projects and config routes."""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING

from .conftest import VALID_CONFIG

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def _create(client: TestClient, room: Path, name: str = "Deal One") -> dict[str, object]:
    r = client.post("/api/projects", json={"name": name, "data_room": str(room)})
    assert r.status_code == 201, r.text
    body: dict[str, object] = r.json()
    return body


class TestProjects:
    def test_create_list_get(self, client: TestClient, data_room: Path) -> None:
        created = _create(client, data_room)
        assert created["slug"] == "deal_one"
        assert client.get("/api/projects").json()[0]["slug"] == "deal_one"
        got = client.get("/api/projects/deal_one").json()
        assert got["path"] == str(data_room.resolve())

    def test_project_saved_before_labels_existed_gets_the_report_label(
        self, client: TestClient, registry_dir: Path, data_room: Path
    ) -> None:
        from dd_agents.persistence.project_registry import ProjectRegistryManager

        _create(client, data_room)
        ProjectRegistryManager(registry_dir).sync_project_from_run("deal_one", "run_1", 2, 11, {"P2": 11}, 10.0)
        assert client.get("/api/projects/deal_one").json()["risk_label"] == "Medium"
        assert client.get("/api/projects").json()[0]["risk_label"] == "Medium"

    def test_duplicate_is_409(self, client: TestClient, data_room: Path) -> None:
        _create(client, data_room)
        r = client.post("/api/projects", json={"name": "Deal One", "data_room": str(data_room)})
        assert r.status_code == 409

    def test_missing_dir_is_422(self, client: TestClient, tmp_path: Path) -> None:
        r = client.post("/api/projects", json={"name": "X", "data_room": str(tmp_path / "nope")})
        assert r.status_code == 422

    def test_file_instead_of_dir_is_422(self, client: TestClient, data_room: Path) -> None:
        r = client.post("/api/projects", json={"name": "X", "data_room": str(data_room / "contract.txt")})
        assert r.status_code == 422

    def test_blank_name_is_422(self, client: TestClient, data_room: Path) -> None:
        assert client.post("/api/projects", json={"name": "  ", "data_room": str(data_room)}).status_code == 422

    def test_unknown_slug_is_404(self, client: TestClient) -> None:
        assert client.get("/api/projects/nope").status_code == 404

    def test_delete_keeps_data_room(self, client: TestClient, data_room: Path) -> None:
        _create(client, data_room)
        assert client.delete("/api/projects/deal_one").status_code == 204
        assert client.get("/api/projects/deal_one").status_code == 404
        assert (data_room / "contract.txt").exists()

    def test_scan_summary(self, client: TestClient, data_room: Path) -> None:
        (data_room / "sub").mkdir()
        (data_room / "sub" / "a.pdf").write_bytes(b"%PDF")
        (data_room / "_dd").mkdir()
        (data_room / "_dd" / "skip.json").write_text("{}")
        _create(client, data_room)
        scan = client.get("/api/projects/deal_one/scan").json()
        assert scan["total_files"] == 2
        assert scan["by_extension"] == {".pdf": 1, ".txt": 1}

    def test_scan_does_not_follow_symlinks_out(self, client: TestClient, data_room: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("x")
        (data_room / "link").symlink_to(outside)
        _create(client, data_room)
        assert client.get("/api/projects/deal_one/scan").json()["total_files"] == 1


class TestConfig:
    def test_get_without_config_is_404(self, client: TestClient, data_room: Path) -> None:
        _create(client, data_room)
        assert client.get("/api/projects/deal_one/config").status_code == 404

    def test_put_valid_writes_and_pins_data_room(self, client: TestClient, data_room: Path) -> None:
        _create(client, data_room)
        cfg = copy.deepcopy(VALID_CONFIG)
        cfg["data_room"] = {"path": "/somewhere/else"}
        r = client.put("/api/projects/deal_one/config", json=cfg)
        assert r.status_code == 200, r.text
        on_disk = json.loads((data_room / "deal-config.json").read_text(encoding="utf-8"))
        assert on_disk["data_room"]["path"] == str(data_room.resolve())
        assert client.get("/api/projects/deal_one/config").json()["data_room"]["path"] == str(data_room.resolve())
        assert client.get("/api/projects/deal_one").json()["config_path"].endswith("deal-config.json")

    def test_put_invalid_is_422_and_writes_nothing(self, client: TestClient, data_room: Path) -> None:
        _create(client, data_room)
        bad = copy.deepcopy(VALID_CONFIG)
        del bad["buyer"]
        r = client.put("/api/projects/deal_one/config", json=bad)
        assert r.status_code == 422
        assert r.json()["detail"]["errors"][0]["loc"]
        assert not (data_room / "deal-config.json").exists()

    def test_invalid_put_keeps_previous_config(self, client: TestClient, data_room: Path) -> None:
        _create(client, data_room)
        assert client.put("/api/projects/deal_one/config", json=VALID_CONFIG).status_code == 200
        before = (data_room / "deal-config.json").read_text(encoding="utf-8")
        assert client.put("/api/projects/deal_one/config", json={"nope": 1}).status_code == 422
        assert (data_room / "deal-config.json").read_text(encoding="utf-8") == before

    def test_stateless_validate(self, client: TestClient) -> None:
        ok = client.post("/api/config/validate", json=VALID_CONFIG).json()
        assert ok == {"valid": True, "errors": []}
        bad = client.post("/api/config/validate", json={"x": 1}).json()
        assert bad["valid"] is False
        assert bad["errors"]

    def test_schema(self, client: TestClient) -> None:
        schema = client.get("/api/config/schema").json()
        assert schema["type"] == "object"
        assert "buyer" in schema["properties"]
