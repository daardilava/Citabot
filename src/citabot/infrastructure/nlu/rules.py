"""Rule-based Spanish interpreter: intent, date and time from a short message.

Deterministic, free and fast, which suits an MVP and makes the agent testable.
An LLM adapter (structured output -> `Interpretation`) can replace it by
implementing the same `MessageInterpreter` port.
"""

from __future__ import annotations

import re
from datetime import date, time, timedelta

from citabot.application.ports import Intent, Interpretation
from citabot.application.text import fold, words

_WEEKDAYS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]
_MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
_MONTH_ALIASES = {"set": 9}

_YES = {"si", "claro", "confirmo", "confirmar", "dale", "ok", "okay", "listo", "correcto",
        "perfecto", "vale", "afirmativo"}  # fmt: skip
_GREETINGS = {"hola", "buenas", "buenos", "buen", "hi", "hello", "saludos", "ola"}

_NUMERIC_DATE = re.compile(r"\b(\d{1,2})\s*[/-]\s*(\d{1,2})(?:\s*[/-]\s*(\d{2,4}))?\b")
_NAMED_DATE = re.compile(
    r"\b(\d{1,2})\s*(?:de\s+)?(ene|feb|mar|abr|may|jun|jul|ago|sep|set|oct|nov|dic)[a-z]*\b"
)
_CLOCK = re.compile(r"\b(\d{1,2})\s*[:h.]\s*(\d{2})\b\s*(am|pm|a\.?\s?m\.?|p\.?\s?m\.?)?")
_HOUR_MERIDIEM = re.compile(r"\b(\d{1,2})\s*(am|pm|a\.\s?m\.?|p\.\s?m\.?)(?![a-z])")
_AT_HOUR = re.compile(r"\ba\s+las?\s+(\d{1,2})\b")
_BARE_NUMBER = re.compile(r"^\s*(\d{1,2})\s*$")


class RuleBasedInterpreter:
    def interpret(self, text: str, today: date) -> Interpretation:
        folded = fold(text)
        tokens = words(text)
        return Interpretation(
            intent=_intent(folded, tokens),
            day=parse_day(folded, today),
            clock_time=parse_time(folded),
            bare_hour=_bare_hour(folded),
            affirmation=_affirmation(folded, tokens),
        )


def _has(folded: str, *stems: str) -> bool:
    return any(stem in folded for stem in stems)


def _intent(folded: str, tokens: list[str]) -> Intent:
    appointment_word = _has(folded, "cita", "turno", "reserva")
    if _has(folded, "persona", "humano", "asesor", "recepcion", "alguien del equipo"):
        return Intent.HUMAN
    if _has(folded, "confirmo asistencia", "confirmo mi asistencia", "confirmar asistencia"):
        return Intent.CONFIRM_ATTENDANCE
    if _has(folded, "cancel", "anular") and (appointment_word or len(tokens) <= 2):
        return Intent.CANCEL
    if _has(folded, "mis citas", "mi cita", "tengo cita", "tengo una cita", "proxima cita"):
        return Intent.MY_APPOINTMENTS
    if _has(folded, "agendar", "agenda", "reservar", "apartar", "programar", "turno") or (
        appointment_word and _has(folded, "quiero", "necesito", "pedir", "sacar", "quisiera", "nueva")
    ):
        return Intent.BOOK
    if _has(folded, "horario", "abren", "cierran", "abierto"):
        return Intent.HOURS
    if _has(folded, "servicio", "precio", "cuanto cuesta", "cuanto vale", "tarifa"):
        return Intent.SERVICES
    if _has(folded, "gracias"):
        return Intent.THANKS
    if tokens and tokens[0] in _GREETINGS and len(tokens) <= 4:
        return Intent.GREETING
    return Intent.UNKNOWN


def _affirmation(folded: str, tokens: list[str]) -> bool | None:
    if not tokens:
        return None
    if tokens[0] in _YES:
        return True
    if tokens[0] == "no":
        return False
    return None


def parse_day(folded: str, today: date) -> date | None:
    """Understands hoy, mañana, pasado mañana, weekdays, 13/11 and '13 de noviembre'."""
    if re.search(r"\bpasado manana\b", folded):
        return today + timedelta(days=2)
    # "por la mañana" is a part of the day, not tomorrow.
    if re.search(r"(?<!\bla )\bmanana\b", folded):
        return today + timedelta(days=1)
    if re.search(r"\bhoy\b", folded):
        return today

    match = _NUMERIC_DATE.search(folded)
    if match:
        year = int(match.group(3)) if match.group(3) else None
        if year is not None and year < 100:
            year += 2000
        return _build_date(int(match.group(1)), int(match.group(2)), year, today)

    match = _NAMED_DATE.search(folded)
    if match:
        key = match.group(2)
        month = _MONTH_ALIASES.get(key) or _MONTHS.index(key) + 1
        return _build_date(int(match.group(1)), month, None, today)

    for index, name in enumerate(_WEEKDAYS):
        if re.search(rf"\b{name}\b", folded):
            return today + timedelta(days=(index - today.weekday()) % 7)
    return None


def _build_date(day: int, month: int, year: int | None, today: date) -> date | None:
    try:
        candidate = date(year or today.year, month, day)
    except ValueError:
        return None
    if year is None and candidate < today:
        # "5/1" said in December means next January.
        try:
            candidate = date(today.year + 1, month, day)
        except ValueError:
            return None
    return candidate


def parse_time(folded: str) -> time | None:
    """Understands 10:30, 10h30, 3 pm, 'a las 3', 'a las 3 de la tarde'."""
    hour: int
    minute = 0
    meridiem: str | None = None

    match = _CLOCK.search(folded)
    if match:
        hour, minute, meridiem = int(match.group(1)), int(match.group(2)), match.group(3)
    else:
        match = _HOUR_MERIDIEM.search(folded)
        if match:
            hour, meridiem = int(match.group(1)), match.group(2)
        else:
            match = _AT_HOUR.search(folded)
            if not match:
                return None
            hour = int(match.group(1))

    marker = (meridiem or "").replace(".", "").replace(" ", "")
    if not marker:
        if _has(folded, "de la tarde", "de la noche", "en la tarde", "por la tarde"):
            marker = "pm"
        elif _has(folded, "de la manana", "en la manana", "por la manana"):
            marker = "am"
    return _to_time(hour, minute, marker)


def _bare_hour(folded: str) -> time | None:
    match = _BARE_NUMBER.match(folded)
    return _to_time(int(match.group(1)), 0, "") if match else None


def _to_time(hour: int, minute: int, marker: str) -> time | None:
    if marker == "pm" and hour < 12:
        hour += 12
    elif marker == "am" and hour == 12:
        hour = 0
    elif not marker and 1 <= hour <= 7:
        hour += 12  # nobody books a dentist at 3 a.m.: "a las 3" means 15:00
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)
