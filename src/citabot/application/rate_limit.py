"""In-memory sliding-window rate limiting."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Hashable
from datetime import datetime, timedelta


class SlidingWindowLimiter:
    """Counts events per key over the last `window` and says when a key is over `limit`.

    Memory is bounded: past `max_keys` the expired keys are dropped, then the
    oldest ones. Losing a key only forgives its past events, never blocks anyone.

    Per process: with several workers each one counts on its own, so the
    effective limit is `limit × workers`. A shared store (Redis, Postgres)
    replaces this once the app runs on more than one process.
    """

    def __init__(self, limit: int, window: timedelta, max_keys: int = 10_000) -> None:
        self.limit = limit
        self.window = window
        self._max_keys = max_keys
        self._events: dict[Hashable, deque[datetime]] = {}
        self._guard = threading.Lock()

    def is_limited(self, key: Hashable, now: datetime) -> bool:
        with self._guard:
            return len(self._recent(key, now)) >= self.limit

    def hit(self, key: Hashable, now: datetime) -> None:
        with self._guard:
            events = self._recent(key, now)
            events.append(now)
            self._events[key] = events
            if len(self._events) > self._max_keys:
                self._shrink(now)

    def reset(self, key: Hashable) -> None:
        with self._guard:
            self._events.pop(key, None)

    def _recent(self, key: Hashable, now: datetime) -> deque[datetime]:
        events = self._events.get(key, deque())
        while events and now - events[0] >= self.window:
            events.popleft()
        if not events:
            self._events.pop(key, None)
        return events

    def _shrink(self, now: datetime) -> None:
        for key in [k for k, v in self._events.items() if now - v[-1] >= self.window]:
            del self._events[key]
        while len(self._events) > self._max_keys:
            del self._events[next(iter(self._events))]  # dicts keep insertion order
