"""Small text helpers shared by the application and its adapters (Spanish)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip

_WORD = re.compile(r"[a-z0-9]+")


def fold(text: str) -> str:
    """Lowercase and strip accents: 'Mañana, ¿sí?' -> 'manana, ¿si?'."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").strip()


def words(text: str) -> list[str]:
    """Accent-folded alphanumeric tokens."""
    return _WORD.findall(fold(text))


def day_long(day: date) -> str:
    """'viernes 13 de noviembre'."""
    return f"{WEEKDAYS[day.weekday()]} {day.day} de {MONTHS[day.month - 1]}"


def day_short(day: date) -> str:
    """'Vie 13/11' — short enough for a WhatsApp button and parseable back."""
    return f"{WEEKDAYS[day.weekday()][:3].capitalize()} {day.day}/{day.month}"


def hhmm(moment: datetime) -> str:
    return moment.strftime("%H:%M")
