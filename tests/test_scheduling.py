from __future__ import annotations

import unittest
from datetime import date, datetime, time

from citabot.domain.models import TimeRange
from citabot.domain.scheduling import available_slots

DAY = date(2026, 11, 13)
MORNING = [TimeRange(time(8), time(10))]


def at(hour: int, minute: int = 0) -> datetime:
    return datetime.combine(DAY, time(hour, minute))


class AvailableSlotsTest(unittest.TestCase):
    def test_slots_follow_the_grid_and_fit_inside_opening_hours(self) -> None:
        slots = available_slots(DAY, MORNING, 30, 30, [], now=at(0))
        self.assertEqual(slots, [at(8), at(8, 30), at(9), at(9, 30)])

    def test_long_service_must_end_before_closing(self) -> None:
        slots = available_slots(DAY, MORNING, 30, 60, [], now=at(0))
        self.assertEqual(slots, [at(8), at(8, 30), at(9)])

    def test_busy_intervals_block_overlapping_slots(self) -> None:
        slots = available_slots(DAY, MORNING, 30, 60, [(at(9), at(9, 30))], now=at(0))
        self.assertEqual(slots, [at(8)])

    def test_past_slots_are_excluded(self) -> None:
        slots = available_slots(DAY, MORNING, 30, 30, [], now=at(8, 45))
        self.assertEqual(slots, [at(9), at(9, 30)])

    def test_closed_day_has_no_slots(self) -> None:
        self.assertEqual(available_slots(DAY, [], 30, 30, [], now=at(0)), [])

    def test_split_shift_never_spans_the_lunch_break(self) -> None:
        opening = [TimeRange(time(8), time(9)), TimeRange(time(14), time(15))]
        slots = available_slots(DAY, opening, 30, 60, [], now=at(0))
        self.assertEqual(slots, [at(8), at(14)])


if __name__ == "__main__":
    unittest.main()
