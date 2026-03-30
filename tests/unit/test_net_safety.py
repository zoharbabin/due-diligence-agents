"""Tests for dd_agents.net_safety module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from dd_agents.net_safety import UnsafeURLError, resolve_and_validate, validate_url


class TestValidateUrl:
    """Tests for validate_url."""

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ],
    )
    def test_allows_safe_https_url(self, _mock_dns: object) -> None:
        result = validate_url("https://example.com/path")
        assert result == "https://example.com/path"

    def test_blocks_http_by_default(self) -> None:
        with pytest.raises(UnsafeURLError, match="scheme"):
            validate_url("http://example.com")

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ],
    )
    def test_allows_http_when_enabled(self, _mock_dns: object) -> None:
        result = validate_url("http://example.com", allow_http=True)
        assert result == "http://example.com"

    def test_blocks_ftp_scheme(self) -> None:
        with pytest.raises(UnsafeURLError, match="scheme"):
            validate_url("ftp://evil.com/file")

    def test_blocks_javascript_scheme(self) -> None:
        with pytest.raises(UnsafeURLError, match="scheme"):
            validate_url("javascript:alert(1)")

    def test_blocks_metadata_host(self) -> None:
        with pytest.raises(UnsafeURLError, match="metadata"):
            validate_url("https://169.254.169.254/latest/meta-data")

    def test_blocks_google_metadata(self) -> None:
        with pytest.raises(UnsafeURLError, match="metadata"):
            validate_url("https://metadata.google.internal/computeMetadata")

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (2, 1, 6, "", ("127.0.0.1", 0)),
        ],
    )
    def test_blocks_loopback(self, _mock_dns: object) -> None:
        with pytest.raises(UnsafeURLError, match="private"):
            validate_url("https://localhost/admin")

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (2, 1, 6, "", ("10.0.0.1", 0)),
        ],
    )
    def test_blocks_private_ip(self, _mock_dns: object) -> None:
        with pytest.raises(UnsafeURLError, match="private"):
            validate_url("https://internal.corp.com")

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (2, 1, 6, "", ("192.168.1.1", 0)),
        ],
    )
    def test_blocks_192_168(self, _mock_dns: object) -> None:
        with pytest.raises(UnsafeURLError, match="private"):
            validate_url("https://router.local")

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (2, 1, 6, "", ("172.16.0.1", 0)),
        ],
    )
    def test_blocks_172_16(self, _mock_dns: object) -> None:
        with pytest.raises(UnsafeURLError, match="private"):
            validate_url("https://internal.example.com")

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (10, 1, 6, "", ("::1", 0, 0, 0)),
        ],
    )
    def test_blocks_ipv6_loopback(self, _mock_dns: object) -> None:
        with pytest.raises(UnsafeURLError, match="private"):
            validate_url("https://ipv6host.example.com")

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (2, 1, 6, "", ("224.0.0.1", 0)),
        ],
    )
    def test_blocks_multicast(self, _mock_dns: object) -> None:
        with pytest.raises(UnsafeURLError, match="private"):
            validate_url("https://multicast.example.com")

    def test_blocks_malformed_url(self) -> None:
        with pytest.raises(UnsafeURLError):
            validate_url("not-a-url")

    def test_blocks_empty_url(self) -> None:
        with pytest.raises(UnsafeURLError):
            validate_url("")

    def test_blocks_userinfo_in_url(self) -> None:
        with pytest.raises(UnsafeURLError, match="credentials"):
            validate_url("https://admin:password@internal.corp.com/")

    def test_blocks_username_only_in_url(self) -> None:
        with pytest.raises(UnsafeURLError, match="credentials"):
            validate_url("https://admin@internal.corp.com/")

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        side_effect=__import__("socket").gaierror("DNS failed"),
    )
    def test_blocks_dns_failure(self, _mock_dns: object) -> None:
        with pytest.raises(UnsafeURLError, match="DNS"):
            validate_url("https://nonexistent.invalid")


class TestResolveAndValidate:
    """Tests for resolve_and_validate."""

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ],
    )
    def test_returns_resolved_ips(self, _mock_dns: object) -> None:
        url, ips = resolve_and_validate("https://example.com")
        assert url == "https://example.com"
        assert "93.184.216.34" in ips

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (2, 1, 6, "", ("10.0.0.1", 0)),
        ],
    )
    def test_blocks_private_ip(self, _mock_dns: object) -> None:
        with pytest.raises(UnsafeURLError, match="private"):
            resolve_and_validate("https://evil.com")

    def test_blocks_http_by_default(self) -> None:
        with pytest.raises(UnsafeURLError, match="scheme"):
            resolve_and_validate("http://example.com")

    def test_blocks_userinfo(self) -> None:
        with pytest.raises(UnsafeURLError, match="credentials"):
            resolve_and_validate("https://user:pass@example.com")


class TestIPv4MappedIPv6:
    """Tests for IPv4-mapped IPv6 address detection."""

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (10, 1, 6, "", ("::ffff:127.0.0.1", 0, 0, 0)),
        ],
    )
    def test_blocks_ipv4_mapped_loopback(self, _mock_dns: object) -> None:
        with pytest.raises(UnsafeURLError, match="private"):
            validate_url("https://sneaky.example.com")

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (10, 1, 6, "", ("::ffff:169.254.169.254", 0, 0, 0)),
        ],
    )
    def test_blocks_ipv4_mapped_metadata(self, _mock_dns: object) -> None:
        with pytest.raises(UnsafeURLError, match="private"):
            validate_url("https://sneaky-metadata.example.com")

    @patch(
        "dd_agents.net_safety.socket.getaddrinfo",
        return_value=[
            (10, 1, 6, "", ("::ffff:10.0.0.1", 0, 0, 0)),
        ],
    )
    def test_blocks_ipv4_mapped_private(self, _mock_dns: object) -> None:
        with pytest.raises(UnsafeURLError, match="private"):
            validate_url("https://internal-mapped.example.com")
