"""The HTTP layer's own error: a status, a stable code and a message for people."""

from __future__ import annotations


class HttpError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    """Every error the API returns has this shape."""
    return {"error": {"code": code, "message": message}}
