"""HTTP server: dispatches API routes and serves the web panel's static files."""

from __future__ import annotations

import logging
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from citabot.domain.errors import (
    AuthenticationError,
    DomainError,
    NotFoundError,
    RateLimitedError,
    SlotUnavailableError,
    ValidationError,
)

from .framework import HttpError, Request, Response, Router

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_000_000
REQUEST_TIMEOUT_SECONDS = 30
MAX_CONNECTIONS = 64
_STATUS_BY_ERROR: dict[type[DomainError], tuple[int, str]] = {
    ValidationError: (400, "validation_error"),
    NotFoundError: (404, "not_found"),
    SlotUnavailableError: (409, "slot_unavailable"),
    AuthenticationError: (401, "unauthorized"),
    RateLimitedError: (429, "too_many_requests"),
}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
}
# Sent only when the site is served over HTTPS: browsers then refuse plain HTTP for a year.
_HSTS = "max-age=31536000; includeSubDomains"
# Windows may map .js to text/plain in its registry; browsers then refuse ES modules.
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}


def make_handler(
    router: Router, web_dir: Path, trust_proxy: bool = False, https: bool = False
) -> type[BaseHTTPRequestHandler]:
    web_root = web_dir.resolve()
    security_headers = _SECURITY_HEADERS | ({"Strict-Transport-Security": _HSTS} if https else {})

    class Handler(BaseHTTPRequestHandler):
        server_version = "Citabot"
        # Socket timeout: a client that stops sending (or never sends the body it
        # announced) is dropped instead of holding a worker thread forever.
        timeout = REQUEST_TIMEOUT_SECONDS

        def do_GET(self) -> None:
            self._handle()

        do_POST = do_PUT = do_PATCH = do_DELETE = do_GET  # noqa: N815

        def log_message(self, format: str, *args: object) -> None:
            logger.debug("%s %s", self.address_string(), format % args)

        def _handle(self) -> None:
            url = urlsplit(self.path)
            is_api = url.path.startswith(("/api/", "/webhooks/"))
            try:
                response = self._dispatch(url.path, url.query) if is_api else self._static(url.path)
            except HttpError as exc:
                response = Response.error(exc.status, exc.code, exc.message)
            except DomainError as exc:
                status, code = _STATUS_BY_ERROR.get(type(exc), (400, "domain_error"))
                response = Response.error(status, code, str(exc))
            except TimeoutError:  # the body never arrived in full
                self.close_connection = True
                response = Response.error(408, "request_timeout", "La petición tardó demasiado.")
            except Exception:  # last line of defence; details stay in the log
                logger.exception("Error no controlado en %s %s", self.command, url.path)
                response = Response.error(500, "internal_error", "Error interno del servidor.")
            self._send(response, cacheable=not is_api)

        def _dispatch(self, path: str, query: str) -> Response:
            handler, params = router.resolve(self.command, path)
            # CSRF: a browser names the page that sent a write request. Refuse the
            # ones that come from another site (the session cookie is SameSite=Lax too).
            origin = self.headers.get("Origin")
            if (
                origin
                and self.command not in _SAFE_METHODS
                and path.startswith("/api/")
                and urlsplit(origin).netloc != self.headers.get("Host")
            ):
                raise HttpError(403, "cross_site_request", "Solicitud de otro sitio rechazada.")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError as exc:
                raise HttpError(400, "bad_request", "Content-Length inválido.") from exc
            if length > MAX_BODY_BYTES:
                self.close_connection = True
                raise HttpError(413, "payload_too_large", "El cuerpo supera 1 MB.")
            request = Request(
                method=self.command,
                path=path,
                query=dict(parse_qsl(query)),
                headers={k.lower(): v for k, v in self.headers.items()},
                body=self.rfile.read(length) if length > 0 else b"",
                params=params,
                client=self._client(),
            )
            return handler(request)

        def _client(self) -> str:
            """The caller's IP. Behind a reverse proxy the socket only shows the proxy,
            so with `trust_proxy` the last X-Forwarded-For entry (the one our proxy
            appended) is used instead. Never trust that header without a proxy:
            any client can send it."""
            forwarded = self.headers.get("X-Forwarded-For") if trust_proxy else None
            if forwarded:
                return forwarded.rsplit(",", 1)[-1].strip()
            return str(self.client_address[0])

        def _static(self, path: str) -> Response:
            if self.command != "GET":
                raise HttpError(405, "method_not_allowed", "Método no permitido.")
            relative = "index.html" if path in ("", "/") else path.strip("/")
            if "." not in relative.rsplit("/", 1)[-1]:
                relative += ".html"  # clean URLs: /precios serves precios.html
            target = (web_root / relative).resolve()
            # Block path traversal: the resolved file must stay inside web/.
            if web_root not in target.parents or not target.is_file():
                not_found = web_root / "404.html"
                if target.suffix == ".html" and not_found.is_file():
                    return Response(404, not_found.read_bytes(), _CONTENT_TYPES[".html"])
                raise HttpError(404, "not_found", "Archivo no encontrado.")
            content_type = (
                _CONTENT_TYPES.get(target.suffix.lower())
                or mimetypes.guess_type(target.name)[0]
                or "application/octet-stream"
            )
            return Response(200, target.read_bytes(), content_type)

        def _send(self, response: Response, cacheable: bool) -> None:
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            # no-cache = revalidate; keeps the panel fresh while you edit the files.
            self.send_header("Cache-Control", "no-cache" if cacheable else "no-store")
            for name, value in (security_headers | response.headers).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(response.body)

    return Handler


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """One thread per connection, but never more than `max_connections` at once.

    When every slot is busy the accept loop waits, and new connections queue in
    the kernel's backlog instead of spawning threads without limit.
    """

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        max_connections: int = MAX_CONNECTIONS,
    ) -> None:
        super().__init__(address, handler)
        self._slots = threading.BoundedSemaphore(max_connections)

    def process_request(self, request: Any, client_address: Any) -> None:
        self._slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def create_server(
    host: str,
    port: int,
    router: Router,
    web_dir: Path,
    max_connections: int = MAX_CONNECTIONS,
    trust_proxy: bool = False,
    https: bool = False,
) -> ThreadingHTTPServer:
    """`https` says the site is served over TLS (usually by the proxy in front)."""
    handler = make_handler(router, web_dir, trust_proxy, https)
    return BoundedThreadingHTTPServer((host, port), handler, max_connections)
