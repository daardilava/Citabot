"""Input parsing and output serialisation for the JSON API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

from citabot.application.ports import ConversationSummary, Passage
from citabot.domain.errors import ValidationError
from citabot.domain.models import (
    Appointment,
    Business,
    Contact,
    Conversation,
    KnowledgeDoc,
    Message,
    Service,
)

# ---------------------------------------------------------------- input
#
# Request bodies are strict: "30" is not a number and 1 is not true, as before.
# An empty string counts as missing for required text.

Text = Annotated[str, StringConstraints(min_length=1)]


class Body(BaseModel):
    model_config = ConfigDict(strict=True)


class SignupIn(Body):
    business_name: Text
    name: Text
    email: Text
    password: Text


class LoginIn(Body):
    email: Text
    password: Text


class BusinessIn(Body):
    name: Text
    welcome_message: Text
    slot_minutes: int
    # {"0": [["08:00", "12:00"]], ...}: weekday (0 = Monday) to opening ranges.
    opening_hours: dict[str, list[list[str]]]


class ServiceIn(Body):
    name: Text
    duration_minutes: int
    price: str | None = None


class ConversationPatch(Body):
    mode: str | None = None
    needs_attention: bool | None = None


class ReplyIn(Body):
    text: Text


class AppointmentIn(Body):
    phone: Text
    name: Text
    service_id: int
    starts_at: Text  # ISO 8601; parsed with parse_datetime


class AppointmentPatch(Body):
    status: Text


class DocIn(Body):
    title: Text
    content: Text


class SearchIn(Body):
    query: Text


class SimulatorIn(Body):
    phone: Text
    text: Text
    name: str | None = None


def parse_date(value: str | None, name: str) -> date:
    try:
        return date.fromisoformat(value or "")
    except ValueError as exc:
        raise ValidationError(f"«{name}» debe ser una fecha AAAA-MM-DD.") from exc


def parse_datetime(value: str, name: str) -> datetime:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=None, second=0, microsecond=0)
    except ValueError as exc:
        raise ValidationError(f"«{name}» debe ser una fecha y hora ISO 8601.") from exc


def parse_hours(raw: dict[str, list[list[str]]]) -> dict[int, list[tuple[str, str]]]:
    """{"0": [["08:00", "12:00"]], …} -> {0: [("08:00", "12:00")], …}"""
    error = ValidationError("«opening_hours» debe ser {día: [[inicio, fin], …]}.")
    hours: dict[int, list[tuple[str, str]]] = {}
    for key, ranges in raw.items():
        if not key.isdigit() or any(len(item) != 2 for item in ranges):
            raise error
        hours[int(key)] = [(item[0], item[1]) for item in ranges]
    return hours


# ---------------------------------------------------------------- output


def business_out(business: Business) -> dict[str, Any]:
    return {
        "id": business.id,
        "name": business.name,
        "vertical": business.vertical,
        "welcome_message": business.welcome_message,
        "slot_minutes": business.slot_minutes,
        "opening_hours": {
            str(day): [[f"{r.start:%H:%M}", f"{r.end:%H:%M}"] for r in ranges]
            for day, ranges in sorted(business.opening_hours.items())
        },
    }


def service_out(service: Service) -> dict[str, Any]:
    return {
        "id": service.id,
        "name": service.name,
        "duration_minutes": service.duration_minutes,
        "price": service.price,
    }


def contact_out(contact: Contact) -> dict[str, Any]:
    return {"id": contact.id, "phone": contact.phone, "name": contact.name}


def message_out(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "direction": message.direction.value,
        "sender": message.sender.value,
        "text": message.text,
        "options": message.options,
        "created_at": message.created_at.isoformat(),
    }


def conversation_out(conversation: Conversation, contact: Contact) -> dict[str, Any]:
    return {
        "id": conversation.id,
        "mode": conversation.mode.value,
        "needs_attention": conversation.needs_attention,
        "updated_at": conversation.updated_at.isoformat(),
        "contact": contact_out(contact),
    }


def summary_out(summary: ConversationSummary) -> dict[str, Any]:
    data = conversation_out(summary.conversation, summary.contact)
    data["last_message"] = message_out(summary.last_message) if summary.last_message else None
    return data


def appointment_out(appointment: Appointment, contact: Contact, service: Service) -> dict[str, Any]:
    return {
        "id": appointment.id,
        "starts_at": appointment.starts_at.isoformat(),
        "ends_at": appointment.ends_at.isoformat(),
        "status": appointment.status.value,
        "source": appointment.source.value,
        "reminder_sent": appointment.reminder_sent,
        "contact": contact_out(contact),
        "service": service_out(service),
    }


def doc_out(doc: KnowledgeDoc) -> dict[str, Any]:
    return {
        "id": doc.id,
        "title": doc.title,
        "content": doc.content,
        "created_at": doc.created_at.isoformat(),
    }


def passage_out(passage: Passage) -> dict[str, Any]:
    return {
        "doc_id": passage.doc_id,
        "title": passage.title,
        "text": passage.text,
        "score": passage.score,
        "confidence": passage.confidence,
    }
