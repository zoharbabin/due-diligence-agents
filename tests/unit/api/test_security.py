"""The API must refuse anything that is not the desktop app on this machine."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from dd_agents.api.app import create_app
from dd_agents.api.security import PathConfinementError, confine_path

from .conftest import AUTH, BASE, TOKEN

if TYPE_CHECKING:
    from pathlib import Path


def test_health_ok_with_token(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_missing_token_is_401(registry_dir: Path) -> None:
    app = create_app(token=TOKEN, registry_dir=registry_dir)
    with TestClient(app, base_url=BASE) as c:
        assert c.get("/api/health").status_code == 401


@pytest.mark.parametrize("header", ["Bearer wrong", "Basic abc", "Bearer", TOKEN])
def test_bad_token_is_401(registry_dir: Path, header: str) -> None:
    app = create_app(token=TOKEN, registry_dir=registry_dir)
    with TestClient(app, base_url=BASE) as c:
        assert c.get("/api/health", headers={"Authorization": header}).status_code == 401


def test_token_is_required_to_be_long(registry_dir: Path) -> None:
    with pytest.raises(ValueError, match="token"):
        create_app(token="short", registry_dir=registry_dir)


@pytest.mark.parametrize("host", ["evil.example.com", "evil.example.com:8765", "127.0.0.1.evil.com"])
def test_foreign_host_is_403(client: TestClient, host: str) -> None:
    assert client.get("/api/health", headers={"Host": host}).status_code == 403


@pytest.mark.parametrize("host", ["127.0.0.1:9000", "localhost:9000", "[::1]:9000", "127.0.0.1"])
def test_loopback_host_is_accepted(client: TestClient, host: str) -> None:
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_foreign_origin_is_403(client: TestClient) -> None:
    assert client.get("/api/health", headers={"Origin": "https://evil.example.com"}).status_code == 403


def test_same_origin_is_accepted(client: TestClient) -> None:
    assert client.get("/api/health", headers={"Origin": BASE}).status_code == 200


def test_other_loopback_port_origin_is_403(client: TestClient) -> None:
    """A different local web page must not talk to the API."""
    assert client.get("/api/health", headers={"Origin": "http://127.0.0.1:9999"}).status_code == 403


def test_no_cors_headers_are_sent(client: TestClient) -> None:
    r = client.get("/api/health", headers={"Origin": BASE})
    assert not any(h.lower().startswith("access-control-") for h in r.headers)


def test_preflight_is_not_answered(client: TestClient) -> None:
    r = client.options(
        "/api/health",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code in (403, 405)


def test_auth_failure_does_not_leak_token(registry_dir: Path) -> None:
    app = create_app(token=TOKEN, registry_dir=registry_dir)
    with TestClient(app, base_url=BASE) as c:
        r = c.get("/api/health", headers={"Authorization": "Bearer nope"})
    assert TOKEN not in r.text


def test_openapi_requires_token(registry_dir: Path) -> None:
    app = create_app(token=TOKEN, registry_dir=registry_dir)
    with TestClient(app, base_url=BASE) as c:
        assert c.get("/openapi.json").status_code == 401
        assert c.get("/openapi.json", headers=AUTH).status_code == 200


class TestConfinePath:
    def test_inside_root(self, tmp_path: Path) -> None:
        (tmp_path / "a").mkdir()
        assert confine_path("a", [tmp_path]) == (tmp_path / "a").resolve()

    def test_dotdot_escape(self, tmp_path: Path) -> None:
        with pytest.raises(PathConfinementError):
            confine_path("../etc/passwd", [tmp_path])

    def test_absolute_outside(self, tmp_path: Path) -> None:
        with pytest.raises(PathConfinementError):
            confine_path("/etc/passwd", [tmp_path])

    def test_symlink_escape(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()
        (root / "link").symlink_to(outside)
        with pytest.raises(PathConfinementError):
            confine_path("link", [root])

    def test_sibling_prefix_is_not_inside(self, tmp_path: Path) -> None:
        root = tmp_path / "room"
        root.mkdir()
        (tmp_path / "room-evil").mkdir()
        with pytest.raises(PathConfinementError):
            confine_path(str(tmp_path / "room-evil"), [root])

    def test_nul_byte(self, tmp_path: Path) -> None:
        with pytest.raises(PathConfinementError):
            confine_path("a\x00b", [tmp_path])
