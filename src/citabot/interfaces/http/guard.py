"""ASGI middleware that every request passes before reaching a route.

It is plain ASGI rather than Starlette's BaseHTTPMiddleware so it can read
the body itself, with a deadline and a size limit, before anything else runs.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import urlsplit

from .errors import error_body

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

MAX_BODY_BYTES = 1_000_000
# An oversized body is still read (and thrown away) up to this size, so the 413
# reaches the client instead of being lost to a connection reset. Past it, the
# server just hangs up.
_DRAIN_LIMIT_BYTES = 10_000_000
# A client that stops sending its body for this long gets a 408.
REQUEST_TIMEOUT_SECONDS = 30.0

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "content-security-policy": (
        "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
}
# The interactive API docs load Swagger UI from a CDN and run an inline script.
_DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)
DOCS_PATH = "/api/docs"
# Sent only when the site is served over HTTPS: browsers then refuse plain HTTP for a year.
_HSTS = "max-age=31536000; includeSubDomains"


class _RefusedError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


class _DisconnectedError(Exception):
    """The client left before sending its body: there is nobody to answer."""


class RequestGuard:
    """Reads the body first, refuses cross-site writes, adds security headers.

    Reading the body before anything can refuse the request matters: closing a
    socket with unread data resets the connection, and the reset can wipe out
    the error response before the client reads it.
    """

    def __init__(self, app: ASGIApp, https: bool = False) -> None:
        self.app = app
        self.https = https

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        send = self._with_headers(scope["path"], send)
        try:
            body = await self._read_body(scope, receive)
            self._check_origin(scope)
        except _RefusedError as refused:
            await _send_json(send, refused.status, error_body(refused.code, refused.message))
            return
        except _DisconnectedError:
            return

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()  # after the body: wait for the disconnect

        await self.app(scope, replay, send)

    async def _read_body(self, scope: Scope, receive: Receive) -> bytes:
        declared = _header(scope, b"content-length")
        if declared is not None and not declared.isdigit():
            raise _RefusedError(400, "bad_request", "Content-Length inválido.")
        too_large = _RefusedError(413, "payload_too_large", "El cuerpo supera 1 MB.")
        if declared is not None and int(declared) > _DRAIN_LIMIT_BYTES:
            raise too_large
        chunks: list[bytes] = []
        size = 0
        while True:
            try:
                message = await asyncio.wait_for(receive(), REQUEST_TIMEOUT_SECONDS)
            except asyncio.TimeoutError as exc:
                raise _RefusedError(408, "request_timeout", "La petición tardó demasiado.") from exc
            if message["type"] == "http.disconnect":
                raise _DisconnectedError
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > _DRAIN_LIMIT_BYTES:
                raise too_large
            if size <= MAX_BODY_BYTES:
                chunks.append(chunk)  # past the limit, keep reading but drop the bytes
            if not message.get("more_body", False):
                if size > MAX_BODY_BYTES:
                    raise too_large
                return b"".join(chunks)

    def _check_origin(self, scope: Scope) -> None:
        """CSRF: a browser names the page that sent a write request. Refuse the ones
        that come from another site (the session cookie is SameSite=Lax too)."""
        origin = _header(scope, b"origin")
        if (
            origin
            and scope["method"] not in _SAFE_METHODS
            and scope["path"].startswith("/api/")
            and urlsplit(origin).netloc != _header(scope, b"host")
        ):
            raise _RefusedError(403, "cross_site_request", "Solicitud de otro sitio rechazada.")

    def _with_headers(self, path: str, send: Send) -> Send:
        is_api = path.startswith(("/api/", "/webhooks/"))
        extra = dict(_SECURITY_HEADERS)
        if path == DOCS_PATH:
            extra["content-security-policy"] = _DOCS_CSP
        if self.https:
            extra["strict-transport-security"] = _HSTS
        # no-cache = revalidate; keeps the panel fresh while you edit the files.
        extra["cache-control"] = "no-store" if is_api else "no-cache"
        encoded = [(k.encode(), v.encode()) for k, v in extra.items()]

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                message["headers"] = [
                    *message.get("headers", []),
                    *((k, v) for k, v in encoded if k not in present),
                ]
            await send(message)

        return wrapped


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return bytes(value).decode("latin-1")
    return None


async def _send_json(send: Send, status: int, data: object) -> None:
    body = json.dumps(data, ensure_ascii=False).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
