"""Domain entities and value objects. Pure Python: no I/O, no framework imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from typing import Any


class ConversationMode(str, Enum):
    """Who answers the customer: the automated agent or a human teammate."""

    BOT = "bot"
    HUMAN = "human"


class Direction(str, Enum):
    INBOUND = "in"
    OUTBOUND = "out"


class Sender(str, Enum):
    CUSTOMER = "customer"
    BOT = "bot"
    AGENT = "agent"


class AppointmentStatus(str, Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class AppointmentSource(str, Enum):
    WHATSAPP = "whatsapp"
    DASHBOARD = "dashboard"


@dataclass(frozen=True)
class TimeRange:
    """A half-open interval [start, end) inside one day."""

    start: time
    end: time

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError("TimeRange start must be before end")


# Weekday (0 = Monday … 6 = Sunday) -> opening ranges for that day.
OpeningHours = dict[int, list[TimeRange]]


@dataclass
class Business:
    """A tenant. Every other record hangs off a business id."""

    id: int
    name: str
    vertical: str
    welcome_message: str
    slot_minutes: int
    opening_hours: OpeningHours

    def ranges_for(self, weekday: int) -> list[TimeRange]:
        return self.opening_hours.get(weekday, [])


@dataclass
class Service:
    id: int
    business_id: int
    name: str
    duration_minutes: int
    price: str | None = None
    active: bool = True


@dataclass
class Contact:
    id: int
    business_id: int
    phone: str
    name: str | None = None


@dataclass
class Conversation:
    id: int
    business_id: int
    contact_id: int
    mode: ConversationMode
    needs_attention: bool
    # Dialogue state of the agent (current flow and collected slots).
    state: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Message:
    id: int
    conversation_id: int
    direction: Direction
    sender: Sender
    text: str
    created_at: datetime
    # Quick replies offered with the message (WhatsApp buttons / list rows).
    options: list[str] = field(default_factory=list)


@dataclass
class Appointment:
    id: int
    business_id: int
    contact_id: int
    service_id: int
    starts_at: datetime
    ends_at: datetime
    status: AppointmentStatus
    source: AppointmentSource
    reminder_sent: bool
    created_at: datetime

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.starts_at < end and start < self.ends_at


@dataclass(frozen=True)
class KnowledgeDoc:
    id: int
    business_id: int
    title: str
    content: str
    created_at: datetime
