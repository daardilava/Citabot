"""«Ver la demo»: a private, throwaway copy of the sample business for each visitor."""

from __future__ import annotations

from datetime import timedelta

from citabot.domain.errors import RateLimitedError, ValidationError

from .auth import AuthService, Session
from .ports import BusinessRepository, Clock, DemoSeeder
from .rate_limit import SlidingWindowLimiter

DEMO_TTL = timedelta(hours=24)
MAX_DEMOS_PER_CLIENT = 10
DEMO_WINDOW = timedelta(hours=1)


class DemoService:
    """Visitors never share data: each one gets a business that expires after DEMO_TTL.

    Expired demos are purged whenever a new one starts, so the database holds
    at most the demos of the last day.
    """

    def __init__(
        self, seeder: DemoSeeder, businesses: BusinessRepository, auth: AuthService, clock: Clock
    ) -> None:
        self._seeder = seeder
        self._businesses = businesses
        self._auth = auth
        self._clock = clock
        self._starts = SlidingWindowLimiter(MAX_DEMOS_PER_CLIENT, DEMO_WINDOW)

    def start(self, client: str = "") -> Session:
        """Create a demo business and sign the visitor in to it.

        `client` identifies the caller (its IP address) for rate limiting.
        """
        now = self._clock.now()
        if self._starts.is_limited(client, now):
            raise RateLimitedError("Demasiadas demostraciones seguidas. Espera unos minutos.")
        self._seeder.purge_expired(now)
        expires_at = now + DEMO_TTL
        user = self._seeder.create(now, expires_at)
        self._starts.hit(client, now)
        return self._auth.start_session(user, expires_at)

    def reset(self, business_id: int) -> None:
        if not self._businesses.get(business_id).is_demo:
            raise ValidationError("Solo un negocio de demostración se puede reiniciar.")
        self._seeder.reset(business_id, self._clock.now())
