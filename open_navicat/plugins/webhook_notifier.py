"""Bundled plugin: send notifications via webhook (Slack, Discord, etc)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from open_navicat.plugin.base import BasePlugin

_log = logging.getLogger(__name__)


def _send_webhook(message: str, config: dict) -> None:
    """POST a JSON payload to a webhook URL."""
    url = config.get("url", "")
    if not url:
        _log.warning("Webhook URL not configured")
        return
    payload = json.dumps({"text": message}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.URLError as e:
        _log.warning("Webhook send failed: %s", e)


class WebhookNotifier(BasePlugin):
    @property
    def name(self) -> str:
        return "webhook_notifier"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Send backup/query notifications via webhook (Slack, Discord, Teams)"

    def get_notification_backends(self) -> dict[str, callable]:
        return {"webhook": _send_webhook}
