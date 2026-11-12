"""A tiny HTTP toolkit on top of the standard library: request, response, router.

The project has no third-party dependencies, so it runs anywhere Python does.
Handlers only translate HTTP <-> application calls, which keeps a later move to
FastAPI mechanical: one route function per handler, same services underneath.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any


class HttpError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass
class Request:
    method: str
    path: str
    query: Mapping[str, str]
    headers: Mapping[str, str]
    body: bytes
    params: dict[str, int] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        try:
            data = json.loads(self.body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HttpError(400, "invalid_json", "El cuerpo debe ser JSON válido.") from exc
        if not isinstance(data, dict):
            raise HttpError(400, "invalid_json", "El cuerpo debe ser un objeto JSON.")
        return data


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str = "application/json; charset=utf-8"

    @classmethod
    def json(cls, data: Any, status: int = 200) -> Response:
        return cls(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

    @classmethod
    def text(cls, text: str, status: int = 200) -> Response:
        return cls(status, text.encode("utf-8"), "text/plain; charset=utf-8")

    @classmethod
    def error(cls, status: int, code: str, message: str) -> Response:
        return cls.json({"error": {"code": code, "message": message}}, status)


Handler = Callable[[Request], Response]
_PARAM = re.compile(r"\{(\w+)\}")


class Router:
    """Maps `METHOD /path/{id}` to a handler. Path parameters are integers."""

    def __init__(self) -> None:
        self._routes: list[tuple[str, re.Pattern[str], Handler]] = []

    def add(self, method: str, pattern: str, handler: Handler) -> None:
        regex = re.compile("^" + _PARAM.sub(r"(?P<\1>\\d{1,12})", pattern) + "$")
        self._routes.append((method, regex, handler))

    def route(self, method: str, pattern: str) -> Callable[[Handler], Handler]:
        def decorator(handler: Handler) -> Handler:
            self.add(method, pattern, handler)
            return handler

        return decorator

    def resolve(self, method: str, path: str) -> tuple[Handler, dict[str, int]]:
        path_matched = False
        for route_method, regex, handler in self._routes:
            match = regex.match(path)
            if not match:
                continue
            path_matched = True
            if route_method == method:
                return handler, {k: int(v) for k, v in match.groupdict().items()}
        if path_matched:
            raise HttpError(405, "method_not_allowed", "Método no permitido.")
        raise HttpError(404, "not_found", "Ruta no encontrada.")
