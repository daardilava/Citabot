"""Domain errors. The HTTP layer maps each one to a status code."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for errors the caller can act on."""


class ValidationError(DomainError):
    """The input is malformed or breaks a business rule."""


class NotFoundError(DomainError):
    """The requested record does not exist for this business."""


class AuthenticationError(DomainError):
    """The credentials are wrong or the session is missing or expired."""


class RateLimitedError(DomainError):
    """Too many attempts in a short time; the caller must wait."""


class SlotUnavailableError(DomainError):
    """The requested appointment slot is closed, past or already taken."""
