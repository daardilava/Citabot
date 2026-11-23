"""The ASGI application: API routes, error shapes, static web files and the request guard."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from citabot.container import Container
from citabot.domain.errors import (
    AuthenticationError,
    DomainError,
    NotFoundError,
    RateLimitedError,
    SlotUnavailableError,
    ValidationError,
)

from .api import build_api
from .errors import HttpError, error_body
from .guard import DOCS_PATH, RequestGuard

logger = logging.getLogger(__name__)

_STATUS_BY_ERROR: dict[type[DomainError], tuple[int, str]] = {
    ValidationError: (400, "validation_error"),
    NotFoundError: (404, "not_found"),
    SlotUnavailableError: (409, "slot_unavailable"),
    AuthenticationError: (401, "unauthorized"),
    RateLimitedError: (429, "too_many_requests"),
}
# Windows may map .js to text/plain in its registry; browsers then refuse ES modules.
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}
# Pydantic error types, in the words the panel shows.
_FIELD_PROBLEMS = {
    "missing": "es obligatorio",
    "string_too_short": "es obligatorio",
    "string_type": "debe ser texto",
    "int_type": "debe ser un número entero",
    "bool_type": "debe ser verdadero o falso",
    "dict_type": "debe ser un objeto",
    "list_type": "debe ser una lista",
}
_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


def json_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(error_body(code, message), status)


def create_app(c: Container) -> Any:
    """The ASGI app to serve. The request guard wraps FastAPI, so it sees every
    request first, including ones no route matches."""
    app = FastAPI(
        title="Citabot API",
        version="0.1.0",
        description="Agente de citas y preguntas frecuentes por WhatsApp para pymes.",
        docs_url=DOCS_PATH,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.include_router(build_api(c))
    _add_error_handlers(app)
    _add_static_files(app, c.settings.web_dir)
    return RequestGuard(app, https=c.settings.cookie_secure)


def _add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HttpError)
    async def http_error(_request: Request, exc: HttpError) -> JSONResponse:
        return json_error(exc.status, exc.code, exc.message)

    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        status, code = _STATUS_BY_ERROR.get(type(exc), (400, "domain_error"))
        return json_error(status, code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first: dict[str, Any] = exc.errors()[0] if exc.errors() else {}
        location = [str(part) for part in first.get("loc", ())]
        if location[:1] == ["path"]:  # a malformed id names nothing that exists
            return json_error(404, "not_found", "Ruta no encontrada.")
        if first.get("type") == "json_invalid":
            return json_error(400, "invalid_json", "El cuerpo debe ser JSON válido.")
        if first.get("type") == "model_attributes_type":
            return json_error(400, "invalid_json", "El cuerpo debe ser un objeto JSON.")
        field = location[-1] if len(location) > 1 else "cuerpo"
        problem = _FIELD_PROBLEMS.get(first.get("type", ""), "no es válido")
        return json_error(400, "validation_error", f"El campo «{field}» {problem}.")

    @app.exception_handler(StarletteHTTPException)
    async def http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, "http_error")
        message = "Ruta no encontrada." if exc.status_code == 404 else "Método no permitido."
        return json_error(exc.status_code, code, message)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, _exc: Exception) -> JSONResponse:
        # Last line of defence; details stay in the log.
        logger.exception("Error no controlado en %s %s", request.method, request.url.path)
        return json_error(500, "internal_error", "Error interno del servidor.")


def _add_static_files(app: FastAPI, web_dir: Path) -> None:
    web_root = web_dir.resolve()
    not_found_page = web_root / "404.html"

    @app.get("/{path:path}", include_in_schema=False)
    def static(path: str) -> Response:
        if path.startswith(("api/", "webhooks/")):
            raise HttpError(404, "not_found", "Ruta no encontrada.")
        relative = path.strip("/") or "index.html"
        if "." not in relative.rsplit("/", 1)[-1]:
            relative += ".html"  # clean URLs: /precios serves precios.html
        target = (web_root / relative).resolve()
        # Block path traversal: the resolved file must stay inside web/.
        if web_root not in target.parents or not target.is_file():
            if target.suffix == ".html" and not_found_page.is_file():
                return Response(not_found_page.read_bytes(), 404, media_type=_CONTENT_TYPES[".html"])
            raise HttpError(404, "not_found", "Archivo no encontrado.")
        content_type = (
            _CONTENT_TYPES.get(target.suffix.lower())
            or mimetypes.guess_type(target.name)[0]
            or "application/octet-stream"
        )
        return Response(target.read_bytes(), media_type=content_type)
