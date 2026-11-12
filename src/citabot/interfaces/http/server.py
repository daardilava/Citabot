"""HTTP server: dispatches API routes and serves the web panel's static files."""

from __future__ import annotations

import logging
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from citabot.domain.errors import DomainError, NotFoundError, SlotUnavailableError, ValidationError

from .framework import HttpError, Request, Response, Router

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_000_000
_STATUS_BY_ERROR: dict[type[DomainError], tuple[int, str]] = {
    ValidationError: (400, "validation_error"),
    NotFoundError: (404, "not_found"),
    SlotUnavailableError: (409, "slot_unavailable"),
}
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
}
# Windows may map .js to text/plain in its registry; browsers then refuse ES modules.
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}


def make_handler(router: Router, web_dir: Path) -> type[BaseHTTPRequestHandler]:
    web_root = web_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "Citabot"

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
            except Exception:  # last line of defence; details stay in the log
                logger.exception("Error no controlado en %s %s", self.command, url.path)
                response = Response.error(500, "internal_error", "Error interno del servidor.")
            self._send(response, cacheable=not is_api)

        def _dispatch(self, path: str, query: str) -> Response:
            handler, params = router.resolve(self.command, path)
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
            )
            return handler(request)

        def _static(self, path: str) -> Response:
            if self.command != "GET":
                raise HttpError(405, "method_not_allowed", "Método no permitido.")
            relative = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (web_root / relative).resolve()
            # Block path traversal: the resolved file must stay inside web/.
            if web_root not in target.parents or not target.is_file():
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
            for name, value in _SECURITY_HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(response.body)

    return Handler


def create_server(host: str, port: int, router: Router, web_dir: Path) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(router, web_dir))
    server.daemon_threads = True
    return server
