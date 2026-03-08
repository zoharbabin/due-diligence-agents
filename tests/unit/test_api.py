"""Tests for API & Webhook Integration (Issue #133)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dd_agents.api.webhooks import (
    EmailConfig,
    SlackMessage,
    WebhookDispatcher,
    WebhookPayload,
    send_webhook,
)


class TestWebhookPayload:
    """Test webhook payload model."""

    def test_payload_defaults(self) -> None:
        payload = WebhookPayload(event="run.completed")
        assert payload.run_id == ""
        assert payload.data == {}

    def test_payload_with_data(self) -> None:
        payload = WebhookPayload(
            event="run.completed",
            run_id="run_123",
            data={"total_findings": 200, "total_customers": 50},
        )
        assert payload.event == "run.completed"
        assert payload.data["total_findings"] == 200


class TestSlackMessage:
    """Test Slack message model."""

    def test_simple_message(self) -> None:
        msg = SlackMessage(text="Pipeline completed")
        assert msg.text == "Pipeline completed"
        assert msg.blocks == []


class TestEmailConfig:
    """Test email configuration model."""

    def test_defaults(self) -> None:
        config = EmailConfig()
        assert config.smtp_port == 587
        assert config.use_tls is True

    def test_custom_config(self) -> None:
        config = EmailConfig(smtp_host="mail.example.com", to_addrs=["team@example.com"])
        assert config.to_addrs == ["team@example.com"]


class TestWebhookDispatcher:
    """Test webhook dispatcher."""

    def test_register_webhook(self) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.register_webhook("https://example.com/hook", events=["run.completed"])
        assert len(dispatcher._webhooks) == 1

    def test_register_slack(self) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.register_slack("https://hooks.slack.com/test")
        assert len(dispatcher._slack_urls) == 1

    def test_register_email(self) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.register_email(EmailConfig(to_addrs=["test@example.com"]))
        assert len(dispatcher._email_configs) == 1

    @patch("dd_agents.api.webhooks.send_webhook", return_value=True)
    def test_dispatch_webhook(self, mock_send: MagicMock) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.register_webhook("https://example.com/hook", events=["run.completed"])
        delivered = dispatcher.dispatch("run.completed", "run_123", {"total_findings": 50})
        assert delivered == 1
        mock_send.assert_called_once()

    @patch("dd_agents.api.webhooks.send_webhook", return_value=True)
    def test_dispatch_filters_events(self, mock_send: MagicMock) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.register_webhook("https://example.com/hook", events=["run.failed"])
        delivered = dispatcher.dispatch("run.completed", "run_123")
        assert delivered == 0
        mock_send.assert_not_called()

    @patch("dd_agents.api.webhooks.send_slack_notification", return_value=True)
    def test_dispatch_slack(self, mock_slack: MagicMock) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.register_slack("https://hooks.slack.com/test")
        delivered = dispatcher.dispatch("run.completed", "run_123")
        assert delivered == 1

    def test_dispatch_empty(self) -> None:
        dispatcher = WebhookDispatcher()
        delivered = dispatcher.dispatch("run.completed", "run_123")
        assert delivered == 0


class TestSendWebhook:
    """Test HTTP webhook sending."""

    @patch("dd_agents.api.webhooks.urllib.request.urlopen")
    def test_send_success(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        payload = WebhookPayload(event="run.completed", run_id="test")
        result = send_webhook("https://example.com/hook", payload)
        assert result is True

    @patch("dd_agents.api.webhooks.urllib.request.urlopen", side_effect=Exception("Connection refused"))
    def test_send_failure(self, mock_urlopen: MagicMock) -> None:
        payload = WebhookPayload(event="run.completed")
        result = send_webhook("https://example.com/hook", payload)
        assert result is False

    @patch("dd_agents.api.webhooks.urllib.request.urlopen")
    def test_send_with_hmac(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        payload = WebhookPayload(event="run.completed")
        result = send_webhook("https://example.com/hook", payload, secret="my-secret")
        assert result is True
        # Verify HMAC header was set
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.has_header("X-dd-signature")


class TestAPIServerImport:
    """Test that API server module can be imported."""

    def test_server_module_importable(self) -> None:
        from dd_agents.api import server

        # FastAPI may or may not be installed
        if server.HAS_FASTAPI:
            assert server.app is not None
        else:
            assert server.app is None

    def test_webhooks_module_importable(self) -> None:
        from dd_agents.api import webhooks

        assert webhooks.WebhookDispatcher is not None


class TestPathValidation:
    """Test path traversal protection in API server."""

    def test_validate_path_rejects_traversal(self) -> None:
        """Paths with '..' components are rejected."""
        from dd_agents.api import server

        if not server.HAS_FASTAPI:
            return  # Skip if FastAPI not installed

        import pytest

        with pytest.raises(Exception, match="traversal"):
            server._validate_path("../../etc/passwd")

    def test_validate_path_rejects_nested_traversal(self) -> None:
        """Nested traversal paths are rejected."""
        from dd_agents.api import server

        if not server.HAS_FASTAPI:
            return

        import pytest

        with pytest.raises(Exception, match="traversal"):
            server._validate_path("/tmp/safe/../../etc/passwd")

    def test_validate_path_allows_normal_path(self) -> None:
        """Normal paths are allowed through."""
        from dd_agents.api import server

        if not server.HAS_FASTAPI:
            return

        result = server._validate_path("/tmp/safe/config.json")
        # On macOS /tmp resolves to /private/tmp
        assert result.name == "config.json"
        assert "safe" in str(result)
