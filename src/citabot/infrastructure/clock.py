"""Clock adapters. Times are naive and local to the business.

MVP simplification: the server is assumed to run in the business's timezone.
A multi-country deployment should store UTC and convert with the tenant's zone.
"""

from __future__ import annotations

from datetime import datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().replace(microsecond=0)


class FixedClock:
    """Deterministic clock for tests."""

    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment
