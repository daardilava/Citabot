"""WhatsApp Cloud API adapter (Meta Graph API).

Enabled with MESSAGING_PROVIDER=whatsapp_cloud. It has not been exercised
against Meta's servers from this repository: check the payloads against the
current Cloud API reference before going live.

Mapping of quick replies:
  * up to 3 options  -> interactive reply buttons (title <= 20 chars)
  * up to 10 options -> interactive list message  (row title <= 24 chars)
  * otherwise        -> plain text with a numbered list
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

BUTTON_TITLE_MAX = 20
LIST_ROW_TITLE_MAX = 24
TIMEOUT_SECONDS = 10


class WhatsAppCloudGateway:
    def __init__(self, access_token: str, phone_number_id: str, api_version: str) -> None:
        if not access_token or not phone_number_id:
            raise ValueError("WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are required")
        self._token = access_token
        self._url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"

    def send_text(self, to_phone: str, text: str, options: Sequence[str] = ()) -> None:
        payload = build_payload(to_phone, text, options)
        request = urllib.request.Request(  # fixed https URL
            self._url,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response.read()


def build_payload(to_phone: str, text: str, options: Sequence[str]) -> dict[str, Any]:
    base: dict[str, Any] = {"messaging_product": "whatsapp", "to": to_phone.lstrip("+")}
    if 1 <= len(options) <= 3:
        buttons = [
            {"type": "reply", "reply": {"id": f"opt_{i}", "title": option[:BUTTON_TITLE_MAX]}}
            for i, option in enumerate(options, start=1)
        ]
        return {
            **base,
            "type": "interactive",
            "interactive": {"type": "button", "body": {"text": text}, "action": {"buttons": buttons}},
        }
    if 4 <= len(options) <= 10:
        rows = [
            {"id": f"opt_{i}", "title": option[:LIST_ROW_TITLE_MAX]}
            for i, option in enumerate(options, start=1)
        ]
        return {
            **base,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": text},
                "action": {"button": "Ver opciones", "sections": [{"title": "Opciones", "rows": rows}]},
            },
        }
    if options:
        text += "\n\n" + "\n".join(f"{i}. {option}" for i, option in enumerate(options, start=1))
    return {**base, "type": "text", "text": {"body": text}}


@dataclass(frozen=True)
class InboundMessage:
    phone: str
    text: str
    profile_name: str | None
    # Meta's id for the message ("wamid..."); the same one comes back on a redelivery.
    message_id: str | None = None


def parse_webhook(payload: dict[str, Any]) -> list[InboundMessage]:
    """Extract customer messages from a Cloud API webhook notification.

    Text, button replies and list replies are supported; other types (audio,
    images, status updates) are ignored.
    """
    inbound: list[InboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for message in value.get("messages", []):
                text = _message_text(message)
                sender = message.get("from")
                if text and sender:
                    message_id = message.get("id")
                    inbound.append(
                        InboundMessage(
                            f"+{sender}",
                            text,
                            names.get(sender),
                            message_id if isinstance(message_id, str) else None,
                        )
                    )
    return inbound


def _message_text(message: dict[str, Any]) -> str | None:
    kind = message.get("type")
    if kind == "text":
        body = message.get("text", {}).get("body")
        return body if isinstance(body, str) else None
    if kind == "interactive":
        interactive = message.get("interactive", {})
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        title = reply.get("title")
        return title if isinstance(title, str) else None
    if kind == "button":  # reply to a template quick-reply button
        title = message.get("button", {}).get("text")
        return title if isinstance(title, str) else None
    return None


def signature_is_valid(app_secret: str, body: bytes, header: str | None) -> bool:
    """Verify Meta's X-Hub-Signature-256 header so only Meta can post to the webhook."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))
