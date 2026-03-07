"""Webhook notification dispatcher (Issue #133).

Sends HTTP POST notifications to registered webhook URLs when
pipeline events occur (run started, completed, failed).

Supports:
- Generic HTTP webhooks with HMAC-SHA256 signing
- Slack incoming webhooks
- Email notifications via SMTP
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import smtplib
import urllib.request
from datetime import UTC, datetime
from email.mime.text import MIMEText
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class WebhookPayload(BaseModel):
    """Standard webhook event payload."""

    event: str = Field(description="Event type: run.started, run.completed, run.failed, run.gate_failed")
    run_id: str = Field(default="")
    timestamp: str = Field(default="")
    data: dict[str, Any] = Field(default_factory=dict)


class SlackMessage(BaseModel):
    """Slack incoming webhook message."""

    text: str
    blocks: list[dict[str, Any]] = Field(default_factory=list)


class EmailConfig(BaseModel):
    """SMTP email notification config."""

    smtp_host: str = Field(default="localhost")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    from_addr: str = Field(default="dd-agents@example.com")
    to_addrs: list[str] = Field(default_factory=list)
    use_tls: bool = Field(default=True)


def send_webhook(url: str, payload: WebhookPayload, secret: str = "") -> bool:
    """Send an HTTP POST webhook with optional HMAC signing."""
    try:
        body = json.dumps(payload.model_dump(), default=str).encode("utf-8")
        headers: dict[str, str] = {"Content-Type": "application/json"}

        if secret:
            signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-DD-Signature"] = f"sha256={signature}"

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return bool(resp.status < 400)
    except Exception:
        logger.warning("Webhook delivery failed: %s", url, exc_info=True)
        return False


def send_slack_notification(webhook_url: str, event: str, run_id: str, data: dict[str, Any]) -> bool:
    """Send a Slack notification via incoming webhook."""
    emoji = {"run.completed": ":white_check_mark:", "run.failed": ":x:", "run.started": ":rocket:"}.get(event, ":bell:")

    findings = data.get("total_findings", 0)
    customers = data.get("total_customers", 0)
    p0 = data.get("finding_counts", {}).get("P0", 0)
    p1 = data.get("finding_counts", {}).get("P1", 0)

    text = (
        f"{emoji} *DD Pipeline {event.split('.')[-1].title()}*\n"
        f"Run: `{run_id}`\n"
        f"Customers: {customers} | Findings: {findings} (P0: {p0}, P1: {p1})"
    )

    msg = SlackMessage(text=text)
    try:
        body = json.dumps(msg.model_dump(), default=str).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return bool(resp.status < 400)
    except Exception:
        logger.warning("Slack notification failed", exc_info=True)
        return False


def send_email_notification(config: EmailConfig, event: str, run_id: str, data: dict[str, Any]) -> bool:
    """Send an email notification via SMTP."""
    if not config.to_addrs:
        return False

    subject = f"DD Pipeline: {event.split('.')[-1].title()} — {run_id}"
    findings = data.get("total_findings", 0)
    customers = data.get("total_customers", 0)

    body = (
        f"Pipeline Event: {event}\n"
        f"Run ID: {run_id}\n"
        f"Timestamp: {datetime.now(UTC).isoformat()}\n\n"
        f"Customers: {customers}\n"
        f"Total Findings: {findings}\n"
        f"Severity Breakdown: {json.dumps(data.get('finding_counts', {}))}\n"
    )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = config.from_addr
    msg["To"] = ", ".join(config.to_addrs)

    try:
        if config.use_tls:
            with smtplib.SMTP(config.smtp_host, config.smtp_port) as smtp:
                smtp.starttls()
                if config.smtp_user:
                    smtp.login(config.smtp_user, config.smtp_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(config.smtp_host, config.smtp_port) as smtp:
                if config.smtp_user:
                    smtp.login(config.smtp_user, config.smtp_password)
                smtp.send_message(msg)
        return True
    except Exception:
        logger.warning("Email notification failed", exc_info=True)
        return False


class WebhookDispatcher:
    """Dispatch pipeline events to registered webhooks."""

    def __init__(self) -> None:
        self._webhooks: list[dict[str, Any]] = []
        self._slack_urls: list[str] = []
        self._email_configs: list[EmailConfig] = []

    def register_webhook(self, url: str, events: list[str] | None = None, secret: str = "") -> None:
        """Register an HTTP webhook."""
        self._webhooks.append(
            {
                "url": url,
                "events": events or ["run.completed", "run.failed"],
                "secret": secret,
            }
        )

    def register_slack(self, webhook_url: str) -> None:
        """Register a Slack incoming webhook."""
        self._slack_urls.append(webhook_url)

    def register_email(self, config: EmailConfig) -> None:
        """Register email notifications."""
        self._email_configs.append(config)

    def dispatch(self, event: str, run_id: str, data: dict[str, Any] | None = None) -> int:
        """Dispatch an event to all matching webhooks. Returns number of successful deliveries."""
        data = data or {}
        payload = WebhookPayload(
            event=event,
            run_id=run_id,
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
            data=data,
        )

        delivered = 0

        for wh in self._webhooks:
            if event in wh["events"] and send_webhook(wh["url"], payload, secret=wh.get("secret", "")):
                delivered += 1

        for url in self._slack_urls:
            if send_slack_notification(url, event, run_id, data):
                delivered += 1

        for email_cfg in self._email_configs:
            if send_email_notification(email_cfg, event, run_id, data):
                delivered += 1

        return delivered
