"""Sliding-window rate limiter."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from citabot.application.rate_limit import SlidingWindowLimiter

T0 = datetime(2026, 11, 12, 9, 0)


class SlidingWindowLimiterTest(unittest.TestCase):
    def test_limits_within_the_window_and_forgets_after_it(self) -> None:
        limiter = SlidingWindowLimiter(limit=3, window=timedelta(minutes=1))
        for second in range(3):
            self.assertFalse(limiter.is_limited("a", T0))
            limiter.hit("a", T0 + timedelta(seconds=second))
        self.assertTrue(limiter.is_limited("a", T0 + timedelta(seconds=30)))
        self.assertFalse(limiter.is_limited("b", T0 + timedelta(seconds=30)))
        # The first hit leaves the window at 60 s, so one more is allowed.
        self.assertFalse(limiter.is_limited("a", T0 + timedelta(seconds=60)))

    def test_reset_forgets_a_key(self) -> None:
        limiter = SlidingWindowLimiter(limit=1, window=timedelta(minutes=1))
        limiter.hit("a", T0)
        limiter.reset("a")
        self.assertFalse(limiter.is_limited("a", T0))

    def test_memory_is_bounded(self) -> None:
        limiter = SlidingWindowLimiter(limit=1, window=timedelta(hours=1), max_keys=100)
        for i in range(1_000):
            limiter.hit(i, T0)
        self.assertLessEqual(len(limiter._events), 100)
        self.assertTrue(limiter.is_limited(999, T0))  # the newest keys are kept


if __name__ == "__main__":
    unittest.main()
