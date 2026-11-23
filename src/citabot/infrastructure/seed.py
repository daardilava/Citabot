"""Demo data: a dental clinic with services, knowledge, chats and appointments.

Dates are relative to "now" so the dashboard always looks alive.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta

from citabot.domain.models import (
    AppointmentSource,
    AppointmentStatus,
    Business,
    ConversationMode,
    Direction,
    OpeningHours,
    Sender,
    TimeRange,
    User,
)

from .security import UNUSABLE_PASSWORD
from .sqlite.db import Database
from .sqlite.repositories import (
    SqliteAppointmentRepository,
    SqliteBusinessRepository,
    SqliteContactRepository,
    SqliteConversationRepository,
    SqliteKnowledgeRepository,
    SqliteUserRepository,
)

_WEEKDAY_HOURS = [TimeRange(time(8), time(12)), TimeRange(time(14), time(18))]
_SATURDAY_HOURS = [TimeRange(time(9), time(13))]

_SERVICES = [
    ("Valoración inicial", 30, "$50.000"),
    ("Limpieza dental", 30, "$120.000"),
    ("Blanqueamiento", 60, "$450.000"),
    ("Control de ortodoncia", 30, "$90.000"),
    ("Urgencia dental", 30, "Desde $80.000"),
]

_KNOWLEDGE = [
    (
        "Ubicación y parqueadero",
        "Estamos en la Calle 85 # 12-34, consultorio 402, a dos cuadras de la estación de "
        "TransMilenio Calle 85.\n\n"
        "El edificio tiene parqueadero para pacientes con entrada por la carrera 12. La primera "
        "hora es gratis presentando el sello de la clínica.",
    ),
    (
        "Formas de pago y seguros",
        "Aceptamos efectivo, tarjeta débito y crédito, transferencia, Nequi y Daviplata.\n\n"
        "Tenemos convenio con Sura, Colsanitas y Allianz. Para otras aseguradoras entregamos "
        "factura para que solicites el reembolso.\n\n"
        "Los tratamientos de más de $500.000 se pueden financiar hasta en 6 cuotas sin interés.",
    ),
    (
        "Política de cancelación",
        "Puedes cancelar o reprogramar tu cita sin costo hasta 12 horas antes. Después de ese "
        "plazo, o si no asistes, se cobra una penalidad de $20.000 en tu siguiente cita.",
    ),
    (
        "Preparación para la cita",
        "Llega 10 minutos antes con tu documento de identidad. Si es tu primera vez, trae "
        "radiografías o exámenes recientes si los tienes.\n\n"
        "Los menores de edad deben venir acompañados por un adulto responsable.",
    ),
    (
        "Blanqueamiento dental",
        "El blanqueamiento dura unos 60 minutos y se hace en una sola sesión. Puede causar "
        "sensibilidad leve durante 24 a 48 horas.\n\n"
        "No se recomienda en embarazo, lactancia ni en menores de 16 años. Antes del "
        "blanqueamiento hacemos una valoración para confirmar que tus encías están sanas.",
    ),
    (
        "Urgencias",
        "Atendemos urgencias por dolor fuerte, fracturas o sangrado el mismo día, según "
        "disponibilidad. Escribe «hablar con una persona» y el equipo te dará prioridad.",
    ),
]


def _next_open_day(start: date, offset: int) -> date:
    """`offset` open days after `start` (Sunday is closed)."""
    day = start
    remaining = offset
    while remaining > 0 or day.weekday() == 6:
        day += timedelta(days=1)
        if day.weekday() != 6:
            remaining -= 1
    return day


_NAME = "Clínica Dental Sonrisa"
_VERTICAL = "dental"
_WELCOME = (
    "¡Hola! 👋 Soy el asistente virtual de Clínica Dental Sonrisa. "
    "Puedo agendar tu cita, contarte horarios y precios o resolver tus dudas. "
    "¿Qué necesitas?"
)
_SLOT_MINUTES = 30


def _hours() -> OpeningHours:
    return dict.fromkeys(range(5), _WEEKDAY_HOURS) | {5: _SATURDAY_HOURS}


DEMO_TEAM_NAME = "Equipo Sonrisa"
# Demo accounts get an address on a domain nobody can own, so they never collide
# with a real sign-up and never receive mail.
DEMO_EMAIL_DOMAIN = "demo.citabot.invalid"


def seed_demo(db: Database, now: datetime) -> int:
    """Insert the sample business on first run. Returns its id.

    It is the business the WhatsApp webhook delivers to until each business
    connects its own number; nobody signs in to it through «Ver la demo».
    """
    with db:
        business = SqliteBusinessRepository(db).add(_NAME, _VERTICAL, _WELCOME, _SLOT_MINUTES, _hours())
        _fill(db, business, now)
        return business.id


# Before each visitor got a private demo, everyone signed in to the sample
# business through this one shared account.
LEGACY_DEMO_EMAIL = "demo@citabot.local"


def remove_legacy_demo_account(db: Database) -> None:
    """Delete the old shared demo account and its sessions, so browsers still
    holding one are signed out instead of staying in the shared business."""
    with db:
        db.execute(
            "DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE email = ?)",
            (LEGACY_DEMO_EMAIL,),
        )
        db.execute("DELETE FROM users WHERE email = ?", (LEGACY_DEMO_EMAIL,))


class SqliteDemoSeeder:
    """Every visitor of «Ver la demo» gets a private copy of the sample business."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def create(self, now: datetime, expires_at: datetime) -> User:
        with self._db:
            business = SqliteBusinessRepository(self._db).add(
                _NAME, _VERTICAL, _WELCOME, _SLOT_MINUTES, _hours(), demo_expires_at=expires_at
            )
            _fill(self._db, business, now)
            email = f"demo-{secrets.token_hex(8)}@{DEMO_EMAIL_DOMAIN}"
            # No password: the account is only reachable through the demo sign-in.
            return SqliteUserRepository(self._db).add(
                business.id, email, DEMO_TEAM_NAME, UNUSABLE_PASSWORD, now
            )

    def reset(self, business_id: int, now: datetime) -> None:
        """Put a demo business back to its first state. Its users are kept."""
        with self._db:
            self._db.clear_business(business_id)
            businesses = SqliteBusinessRepository(self._db)
            business = businesses.get(business_id)
            business.name, business.vertical, business.welcome_message = _NAME, _VERTICAL, _WELCOME
            business.slot_minutes, business.opening_hours = _SLOT_MINUTES, _hours()
            businesses.save(business)
            _fill(self._db, business, now)

    def purge_expired(self, now: datetime) -> int:
        expired = SqliteBusinessRepository(self._db).list_expired_demos(now)
        for business_id in expired:
            self._db.delete_business(business_id)
        return len(expired)


def _fill(db: Database, business: Business, now: datetime) -> None:
    businesses = SqliteBusinessRepository(db)
    contacts = SqliteContactRepository(db)
    conversations = SqliteConversationRepository(db)
    appointments = SqliteAppointmentRepository(db)
    knowledge = SqliteKnowledgeRepository(db)

    with db:
        services = [businesses.add_service(business.id, *spec) for spec in _SERVICES]
        for title, content in _KNOWLEDGE:
            knowledge.add(business.id, title, content, now)

        def chat(phone: str, name: str, minutes_ago: int, lines: list[tuple[Sender, str]]) -> tuple[int, int]:
            started = now - timedelta(minutes=minutes_ago)
            contact = contacts.add(business.id, phone, name, started)
            conversation = conversations.add(business.id, contact.id, started)
            for index, (sender, text) in enumerate(lines):
                direction = Direction.INBOUND if sender is Sender.CUSTOMER else Direction.OUTBOUND
                moment = started + timedelta(minutes=index)
                conversations.add_message(conversation.id, direction, sender, text, [], moment)
                conversation.updated_at = moment
            conversations.save(conversation)
            return contact.id, conversation.id

        def book(contact_id: int, service_index: int, day: date, hour: int, minute: int = 0) -> None:
            service = services[service_index]
            starts = datetime.combine(day, time(hour, minute))
            appointment = appointments.add(
                business.id,
                contact_id,
                service.id,
                starts,
                starts + timedelta(minutes=service.duration_minutes),
                AppointmentSource.WHATSAPP,
                now - timedelta(days=1),
            )
            if starts < now:
                appointment.status = AppointmentStatus.COMPLETED
                appointments.save(appointment)

        today = now.date()
        day0 = _next_open_day(today, 0)
        day1 = _next_open_day(today, 1)
        day2 = _next_open_day(today, 2)

        laura, _ = chat(
            "+57 300 555 0101",
            "Laura Gómez",
            180,
            [
                (Sender.CUSTOMER, "Hola, quiero agendar una limpieza"),
                (Sender.BOT, "¿Qué día prefieres para tu limpieza dental?"),
                (Sender.CUSTOMER, f"{day1.day}/{day1.month} a las 10"),
                (Sender.BOT, "✅ ¡Listo, Laura! Tu cita quedó confirmada."),
            ],
        )
        book(laura, 1, day1, 10)

        andres, andres_chat = chat(
            "+57 310 555 0102",
            "Andrés Ruiz",
            45,
            [
                (Sender.CUSTOMER, "Buenas, ¿hacen diseño de sonrisa con carillas?"),
                (
                    Sender.BOT,
                    "No tengo esa información a la mano 🤔. Puedo pasarte con una persona "
                    "del equipo o ayudarte a agendar una cita.",
                ),
                (Sender.CUSTOMER, "Hablar con una persona"),
                (Sender.BOT, "Claro, te paso con una persona del equipo. 🙌"),
            ],
        )
        conversation = conversations.get(business.id, andres_chat)
        conversation.mode = ConversationMode.HUMAN
        conversation.needs_attention = True
        conversations.save(conversation)
        book(andres, 0, day2, 10, 30)

        camila, _ = chat(
            "+57 320 555 0103",
            "Camila Torres",
            1500,
            [
                (Sender.CUSTOMER, "¿Tienen parqueadero?"),
                (Sender.BOT, "El edificio tiene parqueadero para pacientes con entrada por la carrera 12."),
                (Sender.CUSTOMER, "Gracias!"),
                (Sender.BOT, "¡Con mucho gusto! Si necesitas algo más, aquí estoy."),
            ],
        )
        book(camila, 2, day0, 11)
        book(camila, 3, day2, 9, 30)
