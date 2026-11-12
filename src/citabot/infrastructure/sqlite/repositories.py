"""SQLite adapters for the repository ports. All SQL lives in this package."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import Any

from citabot.application.ports import ConversationSummary
from citabot.domain.errors import NotFoundError
from citabot.domain.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    Business,
    Contact,
    Conversation,
    ConversationMode,
    Direction,
    KnowledgeDoc,
    Message,
    OpeningHours,
    Sender,
    Service,
    TimeRange,
)

from .db import Database


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat()


def _dump_hours(hours: OpeningHours) -> str:
    return json.dumps(
        {str(day): [[f"{r.start:%H:%M}", f"{r.end:%H:%M}"] for r in ranges] for day, ranges in hours.items()}
    )


def _load_hours(raw: str) -> OpeningHours:
    return {
        int(day): [TimeRange(time.fromisoformat(a), time.fromisoformat(b)) for a, b in ranges]
        for day, ranges in json.loads(raw).items()
    }


def _business(row: sqlite3.Row) -> Business:
    return Business(
        id=row["id"],
        name=row["name"],
        vertical=row["vertical"],
        welcome_message=row["welcome_message"],
        slot_minutes=row["slot_minutes"],
        opening_hours=_load_hours(row["opening_hours"]),
    )


def _service(row: sqlite3.Row) -> Service:
    return Service(
        id=row["id"],
        business_id=row["business_id"],
        name=row["name"],
        duration_minutes=row["duration_minutes"],
        price=row["price"],
        active=bool(row["active"]),
    )


def _contact(row: sqlite3.Row) -> Contact:
    return Contact(id=row["id"], business_id=row["business_id"], phone=row["phone"], name=row["name"])


def _conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=row["id"],
        business_id=row["business_id"],
        contact_id=row["contact_id"],
        mode=ConversationMode(row["mode"]),
        needs_attention=bool(row["needs_attention"]),
        state=json.loads(row["state"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"],
        conversation_id=row["conversation_id"],
        direction=Direction(row["direction"]),
        sender=Sender(row["sender"]),
        text=row["text"],
        created_at=datetime.fromisoformat(row["created_at"]),
        options=json.loads(row["options"]),
    )


def _appointment(row: sqlite3.Row) -> Appointment:
    return Appointment(
        id=row["id"],
        business_id=row["business_id"],
        contact_id=row["contact_id"],
        service_id=row["service_id"],
        starts_at=datetime.fromisoformat(row["starts_at"]),
        ends_at=datetime.fromisoformat(row["ends_at"]),
        status=AppointmentStatus(row["status"]),
        source=AppointmentSource(row["source"]),
        reminder_sent=bool(row["reminder_sent"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _doc(row: sqlite3.Row) -> KnowledgeDoc:
    return KnowledgeDoc(
        id=row["id"],
        business_id=row["business_id"],
        title=row["title"],
        content=row["content"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class SqliteBusinessRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, business_id: int) -> Business:
        row = self._db.query_one("SELECT * FROM businesses WHERE id = ?", (business_id,))
        if row is None:
            raise NotFoundError("Negocio no encontrado.")
        return _business(row)

    def add(
        self, name: str, vertical: str, welcome_message: str, slot_minutes: int, hours: OpeningHours
    ) -> Business:
        business_id = self._db.execute(
            "INSERT INTO businesses (name, vertical, welcome_message, slot_minutes, opening_hours) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, vertical, welcome_message, slot_minutes, _dump_hours(hours)),
        )
        return self.get(business_id)

    def exists_any(self) -> bool:
        return self._db.query_one("SELECT 1 FROM businesses LIMIT 1") is not None

    def save(self, business: Business) -> None:
        self._db.execute(
            "UPDATE businesses SET name = ?, vertical = ?, welcome_message = ?, slot_minutes = ?, "
            "opening_hours = ? WHERE id = ?",
            (
                business.name,
                business.vertical,
                business.welcome_message,
                business.slot_minutes,
                _dump_hours(business.opening_hours),
                business.id,
            ),
        )

    def list_services(self, business_id: int, include_inactive: bool = False) -> list[Service]:
        sql = "SELECT * FROM services WHERE business_id = ?"
        if not include_inactive:
            sql += " AND active = 1"
        return [_service(r) for r in self._db.query(sql + " ORDER BY id", (business_id,))]

    def get_service(self, business_id: int, service_id: int) -> Service:
        row = self._db.query_one(
            "SELECT * FROM services WHERE id = ? AND business_id = ?", (service_id, business_id)
        )
        if row is None:
            raise NotFoundError("Servicio no encontrado.")
        return _service(row)

    def add_service(self, business_id: int, name: str, duration_minutes: int, price: str | None) -> Service:
        service_id = self._db.execute(
            "INSERT INTO services (business_id, name, duration_minutes, price) VALUES (?, ?, ?, ?)",
            (business_id, name, duration_minutes, price),
        )
        return self.get_service(business_id, service_id)

    def save_service(self, service: Service) -> None:
        self._db.execute(
            "UPDATE services SET name = ?, duration_minutes = ?, price = ?, active = ? WHERE id = ?",
            (service.name, service.duration_minutes, service.price, int(service.active), service.id),
        )


class SqliteContactRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, contact_id: int) -> Contact:
        row = self._db.query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        if row is None:
            raise NotFoundError("Contacto no encontrado.")
        return _contact(row)

    def find_by_phone(self, business_id: int, phone: str) -> Contact | None:
        row = self._db.query_one(
            "SELECT * FROM contacts WHERE business_id = ? AND phone = ?", (business_id, phone)
        )
        return _contact(row) if row else None

    def add(self, business_id: int, phone: str, name: str | None, now: datetime) -> Contact:
        contact_id = self._db.execute(
            "INSERT INTO contacts (business_id, phone, name, created_at) VALUES (?, ?, ?, ?)",
            (business_id, phone, name, _iso(now)),
        )
        return Contact(id=contact_id, business_id=business_id, phone=phone, name=name)

    def save(self, contact: Contact) -> None:
        self._db.execute("UPDATE contacts SET name = ? WHERE id = ?", (contact.name, contact.id))


class SqliteConversationRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, business_id: int, conversation_id: int) -> Conversation:
        row = self._db.query_one(
            "SELECT * FROM conversations WHERE id = ? AND business_id = ?",
            (conversation_id, business_id),
        )
        if row is None:
            raise NotFoundError("Conversación no encontrada.")
        return _conversation(row)

    def find_by_contact(self, contact_id: int) -> Conversation | None:
        row = self._db.query_one("SELECT * FROM conversations WHERE contact_id = ?", (contact_id,))
        return _conversation(row) if row else None

    def add(self, business_id: int, contact_id: int, now: datetime) -> Conversation:
        conversation_id = self._db.execute(
            "INSERT INTO conversations (business_id, contact_id, mode, created_at, updated_at) "
            "VALUES (?, ?, 'bot', ?, ?)",
            (business_id, contact_id, _iso(now), _iso(now)),
        )
        return self.get(business_id, conversation_id)

    def save(self, conversation: Conversation) -> None:
        self._db.execute(
            "UPDATE conversations SET mode = ?, needs_attention = ?, state = ?, updated_at = ? WHERE id = ?",
            (
                conversation.mode.value,
                int(conversation.needs_attention),
                json.dumps(conversation.state),
                _iso(conversation.updated_at),
                conversation.id,
            ),
        )

    def list_summaries(self, business_id: int) -> list[ConversationSummary]:
        rows = self._db.query(
            "SELECT * FROM conversations WHERE business_id = ? ORDER BY updated_at DESC, id DESC",
            (business_id,),
        )
        summaries = []
        for row in rows:
            contact = self._db.query_one("SELECT * FROM contacts WHERE id = ?", (row["contact_id"],))
            last = self._db.query_one(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
                (row["id"],),
            )
            assert contact is not None  # guaranteed by the foreign key
            summaries.append(
                ConversationSummary(
                    conversation=_conversation(row),
                    contact=_contact(contact),
                    last_message=_message(last) if last else None,
                )
            )
        return summaries

    def add_message(
        self,
        conversation_id: int,
        direction: Direction,
        sender: Sender,
        text: str,
        options: Sequence[str],
        now: datetime,
        external_id: str | None = None,
    ) -> Message:
        message_id = self._db.execute(
            "INSERT INTO messages "
            "(conversation_id, direction, sender, text, options, created_at, external_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                conversation_id,
                direction.value,
                sender.value,
                text,
                json.dumps(list(options)),
                _iso(now),
                external_id,
            ),
        )
        return Message(
            id=message_id,
            conversation_id=conversation_id,
            direction=direction,
            sender=sender,
            text=text,
            created_at=now.replace(microsecond=0),
            options=list(options),
        )

    def has_message(self, external_id: str) -> bool:
        row = self._db.query_one("SELECT 1 FROM messages WHERE external_id = ?", (external_id,))
        return row is not None

    def list_messages(self, conversation_id: int) -> list[Message]:
        rows = self._db.query(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id", (conversation_id,)
        )
        return [_message(r) for r in rows]


class SqliteAppointmentRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, business_id: int, appointment_id: int) -> Appointment:
        row = self._db.query_one(
            "SELECT * FROM appointments WHERE id = ? AND business_id = ?",
            (appointment_id, business_id),
        )
        if row is None:
            raise NotFoundError("Cita no encontrada.")
        return _appointment(row)

    def add(
        self,
        business_id: int,
        contact_id: int,
        service_id: int,
        starts_at: datetime,
        ends_at: datetime,
        source: AppointmentSource,
        now: datetime,
    ) -> Appointment:
        appointment_id = self._db.execute(
            "INSERT INTO appointments (business_id, contact_id, service_id, starts_at, ends_at, "
            "status, source, created_at) VALUES (?, ?, ?, ?, ?, 'confirmed', ?, ?)",
            (business_id, contact_id, service_id, _iso(starts_at), _iso(ends_at), source.value, _iso(now)),
        )
        return self.get(business_id, appointment_id)

    def save(self, appointment: Appointment) -> None:
        self._db.execute(
            "UPDATE appointments SET status = ?, reminder_sent = ? WHERE id = ?",
            (appointment.status.value, int(appointment.reminder_sent), appointment.id),
        )

    def list_between(
        self, business_id: int, start: datetime, end: datetime, only_confirmed: bool = False
    ) -> list[Appointment]:
        sql = "SELECT * FROM appointments WHERE business_id = ? AND starts_at >= ? AND starts_at < ?"
        if only_confirmed:
            sql += " AND status = 'confirmed'"
        rows = self._db.query(sql + " ORDER BY starts_at", (business_id, _iso(start), _iso(end)))
        return [_appointment(r) for r in rows]

    def list_upcoming_for_contact(self, contact_id: int, now: datetime) -> list[Appointment]:
        rows = self._db.query(
            "SELECT * FROM appointments WHERE contact_id = ? AND status = 'confirmed' "
            "AND starts_at > ? ORDER BY starts_at",
            (contact_id, _iso(now)),
        )
        return [_appointment(r) for r in rows]


class SqliteKnowledgeRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self, business_id: int) -> list[KnowledgeDoc]:
        rows = self._db.query(
            "SELECT * FROM knowledge_docs WHERE business_id = ? ORDER BY id", (business_id,)
        )
        return [_doc(r) for r in rows]

    def add(self, business_id: int, title: str, content: str, now: datetime) -> KnowledgeDoc:
        doc_id = self._db.execute(
            "INSERT INTO knowledge_docs (business_id, title, content, created_at) VALUES (?, ?, ?, ?)",
            (business_id, title, content, _iso(now)),
        )
        return KnowledgeDoc(doc_id, business_id, title, content, now.replace(microsecond=0))

    def delete(self, business_id: int, doc_id: int) -> None:
        row = self._db.query_one(
            "SELECT 1 FROM knowledge_docs WHERE id = ? AND business_id = ?", (doc_id, business_id)
        )
        if row is None:
            raise NotFoundError("Documento no encontrado.")
        self._db.execute("DELETE FROM knowledge_docs WHERE id = ?", (doc_id,))


class SqliteDashboardReadModel:
    """Reporting queries. Read-only, so it talks to SQL directly instead of via entities."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def _count(self, sql: str, params: Sequence[Any]) -> int:
        row = self._db.query_one(sql, params)
        return int(row[0]) if row else 0

    def metrics(self, business_id: int, now: datetime) -> dict[str, Any]:
        today = datetime.combine(now.date(), time.min)
        week_ago = today - timedelta(days=6)
        in_conv = "conversation_id IN (SELECT id FROM conversations WHERE business_id = ?)"

        bot = self._count(
            f"SELECT COUNT(*) FROM messages WHERE sender = 'bot' AND created_at >= ? AND {in_conv}",
            (_iso(week_ago), business_id),
        )
        agent = self._count(
            f"SELECT COUNT(*) FROM messages WHERE sender = 'agent' AND created_at >= ? AND {in_conv}",
            (_iso(week_ago), business_id),
        )
        by_day = []
        for offset in range(7):
            start = today + timedelta(days=offset)
            by_day.append(
                {
                    "date": start.date().isoformat(),
                    "count": self._count(
                        "SELECT COUNT(*) FROM appointments WHERE business_id = ? "
                        "AND status != 'cancelled' AND starts_at >= ? AND starts_at < ?",
                        (business_id, _iso(start), _iso(start + timedelta(days=1))),
                    ),
                }
            )
        return {
            "conversations": self._count(
                "SELECT COUNT(*) FROM conversations WHERE business_id = ?", (business_id,)
            ),
            "needs_attention": self._count(
                "SELECT COUNT(*) FROM conversations WHERE business_id = ? AND needs_attention = 1",
                (business_id,),
            ),
            "appointments_today": by_day[0]["count"],
            "appointments_next_7_days": sum(d["count"] for d in by_day),
            "booked_by_bot": self._count(
                "SELECT COUNT(*) FROM appointments WHERE business_id = ? AND source = 'whatsapp' "
                "AND status != 'cancelled'",
                (business_id,),
            ),
            "messages_last_7_days": self._count(
                f"SELECT COUNT(*) FROM messages WHERE created_at >= ? AND {in_conv}",
                (_iso(week_ago), business_id),
            ),
            # Share of outbound messages the bot sent without a human.
            "automation_rate": round(bot / (bot + agent), 2) if bot + agent else None,
            "appointments_by_day": by_day,
        }
