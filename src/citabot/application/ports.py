"""Ports: the interfaces the application needs from the outside world.

Application services depend only on these Protocols. Adapters in
`citabot.infrastructure` implement them, and `citabot.container` wires them.
Swapping SQLite for Postgres, the rule-based interpreter for an LLM, or the
simulator for the WhatsApp Cloud API means writing a new adapter, nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum
from types import TracebackType
from typing import Any, Protocol

from citabot.domain.models import (
    Appointment,
    AppointmentSource,
    Business,
    Contact,
    Conversation,
    Direction,
    KnowledgeDoc,
    Message,
    Sender,
    Service,
)

# ---------------------------------------------------------------- language


class Intent(str, Enum):
    GREETING = "greeting"
    BOOK = "book"
    CANCEL = "cancel"
    MY_APPOINTMENTS = "my_appointments"
    HOURS = "hours"
    SERVICES = "services"
    HUMAN = "human"
    THANKS = "thanks"
    CONFIRM_ATTENDANCE = "confirm_attendance"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Interpretation:
    """Structured reading of one customer message."""

    intent: Intent
    day: date | None = None
    clock_time: time | None = None
    # A message that is only a number ("10"); meaningful when a time was asked.
    bare_hour: time | None = None
    # True for "sí", False for "no", None when the message is neither.
    affirmation: bool | None = None


class MessageInterpreter(Protocol):
    def interpret(self, text: str, today: date) -> Interpretation: ...


@dataclass(frozen=True)
class Passage:
    doc_id: int
    title: str
    text: str
    score: float
    # Share of the question's informative terms found in the passage (0..1).
    confidence: float


class PassageRetriever(Protocol):
    def search(self, docs: Sequence[KnowledgeDoc], query: str, limit: int = 3) -> list[Passage]: ...


class AnswerUnavailableError(Exception):
    """The generator could not produce an answer right now (network, quota, bad output)."""


class AnswerGenerator(Protocol):
    """Turns retrieved passages into the reply text. This is the LLM seam of the RAG.

    Returns None when the passages do not actually answer the question, and raises
    `AnswerUnavailableError` when it could not try at all.
    """

    def generate(self, question: str, passages: Sequence[Passage]) -> str | None: ...


# ---------------------------------------------------------------- messaging


class MessagingGateway(Protocol):
    """Delivers an outbound message to the customer's phone."""

    def send_text(self, to_phone: str, text: str, options: Sequence[str] = ()) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


# ---------------------------------------------------------------- persistence


class UnitOfWork(Protocol):
    """`with uow:` runs the block atomically and serialises concurrent writers."""

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class BusinessRepository(Protocol):
    def get(self, business_id: int) -> Business: ...
    def save(self, business: Business) -> None: ...
    def list_services(self, business_id: int, include_inactive: bool = False) -> list[Service]: ...
    def get_service(self, business_id: int, service_id: int) -> Service: ...
    def add_service(
        self, business_id: int, name: str, duration_minutes: int, price: str | None
    ) -> Service: ...
    def save_service(self, service: Service) -> None: ...


class ContactRepository(Protocol):
    def get(self, contact_id: int) -> Contact: ...
    def find_by_phone(self, business_id: int, phone: str) -> Contact | None: ...
    def add(self, business_id: int, phone: str, name: str | None, now: datetime) -> Contact: ...
    def save(self, contact: Contact) -> None: ...


@dataclass(frozen=True)
class ConversationSummary:
    conversation: Conversation
    contact: Contact
    last_message: Message | None


class ConversationRepository(Protocol):
    def get(self, business_id: int, conversation_id: int) -> Conversation: ...
    def find_by_contact(self, contact_id: int) -> Conversation | None: ...
    def add(self, business_id: int, contact_id: int, now: datetime) -> Conversation: ...
    def save(self, conversation: Conversation) -> None: ...
    def list_summaries(self, business_id: int) -> list[ConversationSummary]: ...
    def add_message(
        self,
        conversation_id: int,
        direction: Direction,
        sender: Sender,
        text: str,
        options: Sequence[str],
        now: datetime,
    ) -> Message: ...
    def list_messages(self, conversation_id: int) -> list[Message]: ...


class AppointmentRepository(Protocol):
    def get(self, business_id: int, appointment_id: int) -> Appointment: ...
    def add(
        self,
        business_id: int,
        contact_id: int,
        service_id: int,
        starts_at: datetime,
        ends_at: datetime,
        source: AppointmentSource,
        now: datetime,
    ) -> Appointment: ...
    def save(self, appointment: Appointment) -> None: ...
    def list_between(
        self, business_id: int, start: datetime, end: datetime, only_confirmed: bool = False
    ) -> list[Appointment]: ...
    def list_upcoming_for_contact(self, contact_id: int, now: datetime) -> list[Appointment]: ...


class KnowledgeRepository(Protocol):
    def list(self, business_id: int) -> list[KnowledgeDoc]: ...
    def add(self, business_id: int, title: str, content: str, now: datetime) -> KnowledgeDoc: ...
    def delete(self, business_id: int, doc_id: int) -> None: ...


class DashboardReadModel(Protocol):
    """Read side kept apart from the write model (CQRS-lite): reporting queries only."""

    def metrics(self, business_id: int, now: datetime) -> dict[str, Any]: ...
