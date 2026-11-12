"""Input parsing and output serialisation for the JSON API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

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


def text_field(body: dict[str, Any], name: str, required: bool = True) -> str:
    value = body.get(name)
    if value is None or value == "":
        if required:
            raise ValidationError(f"El campo «{name}» es obligatorio.")
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"El campo «{name}» debe ser texto.")
    return value


def int_field(body: dict[str, Any], name: str) -> int:
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"El campo «{name}» debe ser un número entero.")
    return value


def bool_field(body: dict[str, Any], name: str) -> bool | None:
    value = body.get(name)
    if value is not None and not isinstance(value, bool):
        raise ValidationError(f"El campo «{name}» debe ser verdadero o falso.")
    return value


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


def parse_hours(raw: Any) -> dict[int, list[tuple[str, str]]]:
    """{"0": [["08:00", "12:00"]], …} -> {0: [("08:00", "12:00")], …}"""
    error = ValidationError("«opening_hours» debe ser {día: [[inicio, fin], …]}.")
    if not isinstance(raw, dict):
        raise error
    hours: dict[int, list[tuple[str, str]]] = {}
    for key, ranges in raw.items():
        if not str(key).isdigit() or not isinstance(ranges, list):
            raise error
        parsed = []
        for item in ranges:
            if not (isinstance(item, list) and len(item) == 2 and all(isinstance(x, str) for x in item)):
                raise error
            parsed.append((item[0], item[1]))
        hours[int(key)] = parsed
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
