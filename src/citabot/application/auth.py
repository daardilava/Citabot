"""Accounts and sessions: sign up a business, sign in, and resolve who is calling."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from citabot.domain.errors import AuthenticationError, RateLimitedError, ValidationError
from citabot.domain.models import TimeRange, User

from .ports import (
    BusinessRepository,
    Clock,
    PasswordHasher,
    SessionRepository,
    UnitOfWork,
    UserRepository,
)
from .rate_limit import SlidingWindowLimiter

SESSION_TTL = timedelta(days=14)
MIN_PASSWORD_CHARS = 8
MAX_PASSWORD_CHARS = 200
MAX_NAME_CHARS = 80
MAX_EMAIL_CHARS = 254
# After this many wrong passwords for one email from one client, that pair is
# refused for the window. Keyed by both so a stranger cannot lock you out.
MAX_FAILED_LOGINS = 5
# A client that fails this often across any emails is refused too (password spraying).
MAX_FAILED_LOGINS_PER_CLIENT = 20
FAILED_LOGIN_WINDOW = timedelta(minutes=15)
# New accounts a single client may create per window.
MAX_SIGNUPS_PER_CLIENT = 5
SIGNUP_WINDOW = timedelta(hours=1)
_TOO_MANY_ATTEMPTS = "Demasiados intentos. Espera unos minutos y vuelve a probar."

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_BAD_CREDENTIALS = "El correo o la contraseña no son correctos."


@dataclass(frozen=True)
class Session:
    # The secret the browser keeps. It exists only here and in the cookie.
    token: str
    user: User
    expires_at: datetime


class AuthService:
    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepository,
        sessions: SessionRepository,
        businesses: BusinessRepository,
        hasher: PasswordHasher,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._users = users
        self._sessions = sessions
        self._businesses = businesses
        self._hasher = hasher
        self._clock = clock
        self._pair_failures = SlidingWindowLimiter(MAX_FAILED_LOGINS, FAILED_LOGIN_WINDOW)
        self._client_failures = SlidingWindowLimiter(MAX_FAILED_LOGINS_PER_CLIENT, FAILED_LOGIN_WINDOW)
        self._signups = SlidingWindowLimiter(MAX_SIGNUPS_PER_CLIENT, SIGNUP_WINDOW)
        self._decoy_hash: str | None = None

    def register(self, business_name: str, name: str, email: str, password: str, client: str = "") -> Session:
        """Create a business with its first user and sign them in.

        `client` identifies the caller (its IP address) for rate limiting.
        """
        if self._signups.is_limited(client, self._clock.now()):
            raise RateLimitedError(_TOO_MANY_ATTEMPTS)
        business_name, name, email = business_name.strip(), name.strip(), _normalise(email)
        if not business_name or len(business_name) > MAX_NAME_CHARS:
            raise ValidationError(
                f"El nombre del negocio es obligatorio (máximo {MAX_NAME_CHARS} caracteres)."
            )
        if not name or len(name) > MAX_NAME_CHARS:
            raise ValidationError(f"Tu nombre es obligatorio (máximo {MAX_NAME_CHARS} caracteres).")
        if len(email) > MAX_EMAIL_CHARS or not _EMAIL.match(email):
            raise ValidationError("Escribe un correo válido.")
        if not MIN_PASSWORD_CHARS <= len(password) <= MAX_PASSWORD_CHARS:
            raise ValidationError(f"La contraseña debe tener al menos {MIN_PASSWORD_CHARS} caracteres.")

        password_hash = self._hasher.hash(password)  # slow on purpose: keep it out of the transaction
        with self._uow:
            if self._users.find_by_email(email) is not None:
                raise ValidationError("Ya existe una cuenta con ese correo. Inicia sesión.")
            business = self._businesses.add(
                name=business_name,
                vertical="general",
                welcome_message=(
                    f"¡Hola! 👋 Soy el asistente virtual de {business_name}. Puedo agendar tu cita, "
                    "contarte horarios y precios o resolver tus dudas. ¿Qué necesitas?"
                ),
                slot_minutes=30,
                hours={weekday: [TimeRange(time(9), time(18))] for weekday in range(5)},
            )
            user = self._users.add(business.id, email, name, password_hash, self._clock.now())
            session = self._open_session(user)
        self._signups.hit(client, self._clock.now())
        return session

    def login(self, email: str, password: str, client: str = "") -> Session:
        """`client` identifies the caller (its IP address) for rate limiting."""
        email = _normalise(email)
        now = self._clock.now()
        pair = (email, client)
        if self._pair_failures.is_limited(pair, now) or self._client_failures.is_limited(client, now):
            raise RateLimitedError(_TOO_MANY_ATTEMPTS)

        user = self._users.find_by_email(email)
        # Verify against a decoy when the account does not exist, so the response
        # takes as long and says the same as for a wrong password.
        stored = user.password_hash if user else self._decoy()
        if not self._hasher.verify(password, stored) or user is None:
            self._pair_failures.hit(pair, now)
            self._client_failures.hit(client, now)
            raise AuthenticationError(_BAD_CREDENTIALS)

        self._pair_failures.reset(pair)
        with self._uow:
            self._sessions.delete_expired(now)
            return self._open_session(user)

    def start_session(self, user: User, expires_at: datetime | None = None) -> Session:
        """Sign a known user in without a password. Only for demo accounts.

        `expires_at` caps the session, so it never outlives its demo business.
        """
        with self._uow:
            return self._open_session(user, expires_at)

    def authenticate(self, token: str) -> User | None:
        """The user behind a session token, or None when it is unknown or expired."""
        user_id = self._sessions.find_user_id(_digest(token), self._clock.now())
        return self._users.get(user_id) if user_id is not None else None

    def logout(self, token: str) -> None:
        self._sessions.delete(_digest(token))

    # ------------------------------------------------------------ helpers

    def _open_session(self, user: User, cap: datetime | None = None) -> Session:
        now = self._clock.now()
        token = secrets.token_urlsafe(32)
        expires_at = min(now + SESSION_TTL, cap) if cap else now + SESSION_TTL
        self._sessions.add(_digest(token), user.id, expires_at, now)
        return Session(token, user, expires_at)

    def _decoy(self) -> str:
        if self._decoy_hash is None:
            self._decoy_hash = self._hasher.hash(secrets.token_urlsafe(16))
        return self._decoy_hash


def _normalise(email: str) -> str:
    return email.strip().lower()


def _digest(token: str) -> str:
    """Sessions are looked up by hash, so a leaked database does not leak live sessions."""
    return hashlib.sha256(token.encode()).hexdigest()
