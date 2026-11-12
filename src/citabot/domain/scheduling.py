"""Slot computation. Pure functions so the rules are trivial to unit-test."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from .models import TimeRange

Interval = tuple[datetime, datetime]


def available_slots(
    day: date,
    opening: Iterable[TimeRange],
    slot_minutes: int,
    duration_minutes: int,
    busy: Iterable[Interval],
    now: datetime,
) -> list[datetime]:
    """Return every start time on `day` where an appointment of `duration_minutes` fits.

    A slot is valid when it starts on the slot grid, ends inside the same opening
    range, is still in the future and does not overlap a busy interval.
    """
    if slot_minutes <= 0 or duration_minutes <= 0:
        raise ValueError("slot_minutes and duration_minutes must be positive")

    busy_list = list(busy)
    step = timedelta(minutes=slot_minutes)
    duration = timedelta(minutes=duration_minutes)
    slots: list[datetime] = []

    for rng in sorted(opening, key=lambda r: r.start):
        cursor = datetime.combine(day, rng.start)
        closes = datetime.combine(day, rng.end)
        while cursor + duration <= closes:
            end = cursor + duration
            is_future = cursor > now
            is_free = all(not (start < end and cursor < finish) for start, finish in busy_list)
            if is_future and is_free:
                slots.append(cursor)
            cursor += step
    return slots
