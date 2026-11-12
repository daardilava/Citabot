"""The conversational agent: turns one inbound WhatsApp message into replies.

The agent is a small dialogue manager. Language understanding (intent, date,
time) comes from the `MessageInterpreter` port and knowledge answers from
`KnowledgeService`, so either can be replaced by an LLM without touching the
booking rules, which stay deterministic on purpose: a model should never be
the thing that decides whether a slot is free.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from citabot.domain.errors import SlotUnavailableError, ValidationError
from citabot.domain.models import (
    Appointment,
    AppointmentSource,
    AppointmentStatus,
    Business,
    Contact,
    Conversation,
    ConversationMode,
    Direction,
    Message,
    Sender,
    Service,
)

from .booking import BookingService
from .knowledge import KnowledgeService
from .messenger import ConversationMessenger, Reply
from .ports import (
    BusinessRepository,
    Clock,
    ContactRepository,
    ConversationRepository,
    Intent,
    Interpretation,
    MessageInterpreter,
    UnitOfWork,
)
from .text import WEEKDAYS, day_long, day_short, fold, hhmm, words

MAX_INBOUND_CHARS = 2000
MAX_BOOKING_DAYS_AHEAD = 60
MAX_SLOT_OPTIONS = 10  # WhatsApp list messages allow up to 10 rows

MENU = ["Agendar cita", "Ver mis citas", "Horarios y precios", "Hablar con una persona"]
_ABORT_PHRASES = {"cancelar", "salir", "no gracias", "olvidalo", "ya no", "cancelar proceso"}
_GENERIC_SERVICE_WORDS = {"dental", "cita", "consulta", "control", "inicial", "general"}


@dataclass(frozen=True)
class InboundResult:
    conversation_id: int
    replies: list[Message]


class AgentService:
    def __init__(
        self,
        uow: UnitOfWork,
        businesses: BusinessRepository,
        contacts: ContactRepository,
        conversations: ConversationRepository,
        booking: BookingService,
        knowledge: KnowledgeService,
        interpreter: MessageInterpreter,
        messenger: ConversationMessenger,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._businesses = businesses
        self._contacts = contacts
        self._conversations = conversations
        self._booking = booking
        self._knowledge = knowledge
        self._interpreter = interpreter
        self._messenger = messenger
        self._clock = clock

    # ------------------------------------------------------------ entry point

    def handle_inbound(
        self, business_id: int, phone: str, text: str, profile_name: str | None = None
    ) -> InboundResult:
        text = text.strip()[:MAX_INBOUND_CHARS]
        phone = phone.strip()
        if not text or not phone:
            raise ValidationError("El mensaje y el teléfono son obligatorios.")

        with self._uow:
            now = self._clock.now()
            business = self._businesses.get(business_id)
            contact = self._contact_for(business_id, phone, profile_name, now)
            conversation = self._conversations.find_by_contact(contact.id) or (
                self._conversations.add(business_id, contact.id, now)
            )
            self._conversations.add_message(
                conversation.id, Direction.INBOUND, Sender.CUSTOMER, text, [], now
            )
            conversation.updated_at = now

            replies: list[Reply] = []
            if conversation.mode is ConversationMode.HUMAN:
                conversation.needs_attention = True  # a teammate owns this chat
            else:
                replies = self._respond(business, contact, conversation, text, now)
                conversation.state["options"] = replies[-1].options if replies else []
            self._conversations.save(conversation)
            outbound = self._messenger.record(conversation, Sender.BOT, replies)

        self._messenger.deliver(contact, outbound)
        return InboundResult(conversation.id, outbound)

    # ------------------------------------------------------------ routing

    def _respond(
        self, business: Business, contact: Contact, conv: Conversation, text: str, now: datetime
    ) -> list[Reply]:
        text = self._resolve_option(text, conv.state)
        intr = self._interpreter.interpret(text, now.date())
        folded = fold(text)
        flow = conv.state.get("flow")

        if intr.intent is Intent.HUMAN:
            conv.mode = ConversationMode.HUMAN
            conv.needs_attention = True
            conv.state = {}
            return [
                Reply(
                    "Claro, te paso con una persona del equipo. "
                    "Te responderá por este mismo chat lo antes posible. 🙌"
                )
            ]

        if flow == "booking":
            if folded in _ABORT_PHRASES:
                conv.state = {}
                return [Reply("Listo, no agendé nada. ¿Te ayudo con algo más?", MENU)]
            return self._booking_step(business, contact, conv, intr, text, now)
        if flow == "cancel":
            return self._cancel_step(business, conv, intr, text)

        if intr.intent is Intent.BOOK:
            conv.state = {"flow": "booking"}
            return self._booking_step(business, contact, conv, intr, text, now, entering=True)
        if intr.intent is Intent.CANCEL:
            return self._start_cancel(business, contact, conv)
        if intr.intent is Intent.MY_APPOINTMENTS:
            return self._list_appointments(business, contact)
        if intr.intent is Intent.HOURS:
            replies = [Reply(self._hours_text(business))]
            if "precio" in folded or "servicio" in folded:
                replies.append(Reply(self._services_text(business)))
            replies[-1] = Reply(replies[-1].text, ["Agendar cita"])
            return replies
        if intr.intent is Intent.SERVICES:
            return [Reply(self._services_text(business), ["Agendar cita"])]
        if intr.intent is Intent.CONFIRM_ATTENDANCE:
            return [Reply("¡Perfecto, quedó confirmada tu asistencia! Te esperamos. 😊")]
        if intr.intent is Intent.THANKS:
            return [Reply("¡Con mucho gusto! Si necesitas algo más, aquí estoy.")]
        if intr.intent is Intent.GREETING:
            return [Reply(business.welcome_message, MENU)]

        answer = self._knowledge.answer(business.id, text)
        if answer is not None:
            return [Reply(answer.text, ["Agendar cita", "Hablar con una persona"])]

        conv.needs_attention = True  # surface the unanswered question to the team
        return [
            Reply(
                "No tengo esa información a la mano 🤔. Puedo pasarte con una persona "
                "del equipo o ayudarte a agendar una cita.",
                ["Hablar con una persona", "Agendar cita"],
            )
        ]

    # ------------------------------------------------------------ booking flow

    def _booking_step(
        self,
        business: Business,
        contact: Contact,
        conv: Conversation,
        intr: Interpretation,
        text: str,
        now: datetime,
        entering: bool = False,
    ) -> list[Reply]:
        """Fill whatever the message provides, then ask for the first missing piece.

        Order: service -> day -> time -> name -> confirmation. A single message
        such as "quiero una limpieza mañana a las 10" fills three at once.
        """
        st = conv.state
        folded = fold(text)
        today = now.date()
        progressed = entering
        notes: list[str] = []
        wants_confirm = False

        services = self._businesses.list_services(business.id)
        if not services:
            conv.state = {}
            return [Reply("Por ahora no tenemos servicios disponibles para agendar por aquí.")]

        if st.get("awaiting_name"):
            name = _clean_name(text, intr)
            if name:
                contact.name = name
                self._contacts.save(contact)
                st.pop("awaiting_name")
                progressed = True

        # Naming a service always wins, so "mejor un blanqueamiento" switches mid-flow.
        matched = _match_service(folded, services)
        if matched is not None and matched.id != st.get("service_id"):
            st["service_id"] = matched.id
            st.pop("awaiting_confirm", None)
            progressed = True

        time_candidate = intr.clock_time
        if time_candidate is None and st.get("date") and not st.get("time") and not intr.day:
            time_candidate = intr.bare_hour

        if st.get("awaiting_confirm"):
            if "hora" in folded and ("cambiar" in folded or "otra" in folded):
                st.pop("time", None)
                st.pop("awaiting_confirm")
                progressed = True
            elif any(w in folded for w in ("fecha", "dia")) and (
                "cambiar" in folded or "otro" in folded or "otra" in folded
            ):
                st.pop("date", None)
                st.pop("time", None)
                st.pop("awaiting_confirm")
                progressed = True
            elif intr.day is None and time_candidate is None:
                if intr.affirmation is True:
                    wants_confirm = True
                    progressed = True
                elif intr.affirmation is False:
                    conv.state = {}
                    return [Reply("Sin problema, no agendé nada. ¿Te ayudo con algo más?", MENU)]

        if intr.day is not None:
            st["date"] = intr.day.isoformat()
            st.pop("time", None)
            st.pop("awaiting_confirm", None)
            progressed = True
        if time_candidate is not None:
            st["time"] = time_candidate.strftime("%H:%M")
            st.pop("awaiting_confirm", None)
            progressed = True

        # --- service
        service = next((s for s in services if s.id == st.get("service_id")), None)
        if service is None:
            st.pop("service_id", None)
            prompt = Reply("¿Qué servicio necesitas?", [s.name for s in services])
            return self._ask(business, text, intr, progressed, notes, prompt)

        # --- day
        day = date.fromisoformat(st["date"]) if st.get("date") else None
        slots: list[datetime] = []
        if day is not None:
            if day < today:
                notes.append("Esa fecha ya pasó.")
                day = None
            elif day > today + timedelta(days=MAX_BOOKING_DAYS_AHEAD):
                notes.append(f"Agendamos con máximo {MAX_BOOKING_DAYS_AHEAD} días de anticipación.")
                day = None
            else:
                slots = self._booking.slots_for(business, service, day)
                if not slots:
                    closed = not business.ranges_for(day.weekday())
                    reason = "no atendemos" if closed else "ya no quedan horarios disponibles"
                    notes.append(f"El {day_long(day)} {reason}.")
                    day = None
            if day is None:
                st.pop("date", None)
                st.pop("time", None)
        if day is None:
            days = self._booking.next_days_with_slots(business, service)
            if not days:
                conv.state = {}
                conv.needs_attention = True
                return [
                    Reply(
                        "No veo disponibilidad en las próximas semanas. "
                        "Le aviso al equipo para que te contacte.",
                        ["Hablar con una persona"],
                    )
                ]
            prompt = Reply(
                f"¿Qué día prefieres para tu {service.name.lower()}? "
                "Estos son los más próximos con disponibilidad (también puedes escribir otra fecha):",
                [day_short(d) for d in days],
            )
            return self._ask(business, text, intr, progressed, notes, prompt)

        # --- time
        chosen: datetime | None = None
        if st.get("time"):
            chosen = datetime.combine(day, time.fromisoformat(st["time"]))
            if chosen not in slots:
                notes.append(f"A las {st['time']} no tengo disponibilidad.")
                st.pop("time")
                chosen = None
        if chosen is None:
            prompt = Reply(
                f"Para el {day_long(day)} tengo estos horarios. ¿Cuál te sirve?",
                [hhmm(s) for s in _spread(slots, MAX_SLOT_OPTIONS)],
            )
            return self._ask(business, text, intr, progressed, notes, prompt)

        # --- name
        if not contact.name:
            st["awaiting_name"] = True
            prompt = Reply("¿A nombre de quién agendo la cita?")
            return self._ask(business, text, intr, progressed, notes, prompt)

        # --- confirmation
        if wants_confirm:
            try:
                self._booking.book(business.id, contact.id, service.id, chosen, AppointmentSource.WHATSAPP)
            except SlotUnavailableError:
                st.pop("time", None)
                st.pop("awaiting_confirm", None)
                remaining = self._booking.slots_for(business, service, day)
                prompt = Reply(
                    "Ese horario se acaba de ocupar 😕. Estos siguen libres:",
                    [hhmm(s) for s in _spread(remaining, MAX_SLOT_OPTIONS)],
                )
                return [prompt]
            conv.state = {}
            return [
                Reply(
                    f"✅ ¡Listo, {contact.name.split()[0]}! Tu cita quedó confirmada:\n\n"
                    f"• {service.name}\n• {day_long(day).capitalize()}\n• {hhmm(chosen)}\n\n"
                    "Te enviaré un recordatorio el día anterior. "
                    "Si necesitas cancelarla, escribe «cancelar cita»."
                )
            ]

        st["awaiting_confirm"] = True
        prompt = Reply(
            f"Perfecto, {contact.name.split()[0]}. Te agendo:\n\n"
            f"• {service.name}\n• {day_long(day).capitalize()}\n• {hhmm(chosen)}\n\n¿Confirmas?",
            ["Sí, confirmar", "Cambiar hora", "Cancelar"],
        )
        return self._ask(business, text, intr, progressed, notes, prompt)

    def _ask(
        self,
        business: Business,
        text: str,
        intr: Interpretation,
        progressed: bool,
        notes: list[str],
        prompt: Reply,
    ) -> list[Reply]:
        """Prefix the next question with a correction, an FAQ answer or a nudge."""
        if notes:
            return [Reply(" ".join(notes) + "\n\n" + prompt.text, prompt.options)]
        if progressed:
            return [prompt]
        # The customer said something that did not move the booking forward.
        # It may be a question ("¿tienen parqueadero?"): answer it, then resume.
        answer = None if intr.affirmation is not None else self._knowledge.answer(business.id, text)
        if answer is not None:
            return [Reply(answer.text), prompt]
        return [Reply("No te entendí bien 😅. " + prompt.text, prompt.options)]

    # ------------------------------------------------------------ cancel flow

    def _start_cancel(self, business: Business, contact: Contact, conv: Conversation) -> list[Reply]:
        upcoming = self._booking.upcoming_for_contact(contact.id)
        if not upcoming:
            return [Reply("No encuentro citas próximas a tu nombre. ¿Quieres agendar una?", ["Agendar cita"])]
        if len(upcoming) == 1:
            conv.state = {"flow": "cancel", "appointment_id": upcoming[0].id}
            return [self._cancel_prompt(business, upcoming[0])]
        choices = {f"{day_short(a.starts_at.date())} {hhmm(a.starts_at)}": a.id for a in upcoming}
        conv.state = {"flow": "cancel", "choices": choices}
        return [Reply("Tienes varias citas. ¿Cuál quieres cancelar?", list(choices))]

    def _cancel_step(
        self, business: Business, conv: Conversation, intr: Interpretation, text: str
    ) -> list[Reply]:
        st = conv.state
        if "appointment_id" not in st:
            choices: dict[str, int] = st.get("choices", {})
            appointment_id = choices.get(text.strip())
            if appointment_id is None:
                if intr.affirmation is False or fold(text) in _ABORT_PHRASES:
                    conv.state = {}
                    return [Reply("De acuerdo, no cancelé nada.")]
                return [Reply("Elige la cita que quieres cancelar:", list(choices))]
            st["appointment_id"] = appointment_id
            st.pop("choices", None)
            appointment = self._booking.get(business.id, appointment_id)
            return [self._cancel_prompt(business, appointment)]

        if intr.affirmation is True:
            self._booking.set_status(business.id, st["appointment_id"], AppointmentStatus.CANCELLED)
            conv.state = {}
            return [Reply("Tu cita fue cancelada. Cuando quieras agendamos otra.", ["Agendar cita"])]
        if intr.affirmation is False or "conservar" in fold(text):
            conv.state = {}
            return [Reply("Perfecto, tu cita sigue en pie. ¡Te esperamos!")]
        appointment = self._booking.get(business.id, st["appointment_id"])
        return [self._cancel_prompt(business, appointment)]

    def _cancel_prompt(self, business: Business, appointment: Appointment) -> Reply:
        service = self._businesses.get_service(business.id, appointment.service_id)
        return Reply(
            f"¿Cancelo tu cita de {service.name.lower()} del "
            f"{day_long(appointment.starts_at.date())} a las {hhmm(appointment.starts_at)}?",
            ["Sí, cancelar", "No, conservar"],
        )

    # ------------------------------------------------------------ informational replies

    def _list_appointments(self, business: Business, contact: Contact) -> list[Reply]:
        upcoming = self._booking.upcoming_for_contact(contact.id)
        if not upcoming:
            return [Reply("No tienes citas próximas. ¿Agendamos una?", ["Agendar cita"])]
        lines = []
        for a in upcoming:
            service = self._businesses.get_service(business.id, a.service_id)
            lines.append(f"• {service.name} — {day_long(a.starts_at.date())}, {hhmm(a.starts_at)}")
        return [
            Reply("Estas son tus próximas citas:\n\n" + "\n".join(lines), ["Agendar cita", "Cancelar cita"])
        ]

    def _hours_text(self, business: Business) -> str:
        def describe(weekday: int) -> str:
            ranges = business.ranges_for(weekday)
            if not ranges:
                return "cerrado"
            return " y ".join(f"{r.start:%H:%M}–{r.end:%H:%M}" for r in ranges)

        # Group consecutive days that share the same hours: "Lunes a viernes: …".
        groups: list[tuple[int, int, str]] = []
        for weekday in range(7):
            text = describe(weekday)
            if groups and groups[-1][2] == text:
                groups[-1] = (groups[-1][0], weekday, text)
            else:
                groups.append((weekday, weekday, text))
        lines = []
        for first, last, text in groups:
            label = WEEKDAYS[first] if first == last else f"{WEEKDAYS[first]} a {WEEKDAYS[last]}"
            lines.append(f"• {label.capitalize()}: {text}")
        return "🕐 Nuestro horario de atención:\n\n" + "\n".join(lines)

    def _services_text(self, business: Business) -> str:
        services = self._businesses.list_services(business.id)
        if not services:
            return "Todavía no tenemos servicios publicados."
        lines = [
            f"• {s.name} ({s.duration_minutes} min)" + (f" — {s.price}" if s.price else "") for s in services
        ]
        return "Estos son nuestros servicios:\n\n" + "\n".join(lines)

    # ------------------------------------------------------------ helpers

    def _contact_for(self, business_id: int, phone: str, profile_name: str | None, now: datetime) -> Contact:
        name = (profile_name or "").strip()[:80] or None
        contact = self._contacts.find_by_phone(business_id, phone)
        if contact is None:
            return self._contacts.add(business_id, phone, name, now)
        if not contact.name and name:
            contact.name = name
            self._contacts.save(contact)
        return contact

    @staticmethod
    def _resolve_option(text: str, state: dict[str, object]) -> str:
        """Map a numeric reply ("2") to the option offered in the previous message."""
        options = state.get("options")
        stripped = text.strip()
        if not isinstance(options, list) or not stripped.isdigit():
            return text
        asking_time = state.get("flow") == "booking" and state.get("date") and not state.get("time")
        if asking_time:
            return text  # here "10" means ten o'clock, not the tenth option
        index = int(stripped)
        return str(options[index - 1]) if 1 <= index <= len(options) else text


def _match_service(folded_text: str, services: list[Service]) -> Service | None:
    """Find the service a message refers to: full name first, then a distinctive word."""
    for service in services:
        if fold(service.name) in folded_text:
            return service
    tokens = words(folded_text)
    matches = [
        service
        for service in services
        if any(
            len(word) >= 5
            and word not in _GENERIC_SERVICE_WORDS
            and any(token.startswith(word[:5]) for token in tokens)
            for word in words(service.name)
        )
    ]
    return matches[0] if len(matches) == 1 else None


def _clean_name(text: str, intr: Interpretation) -> str | None:
    candidate = " ".join(text.split())
    looks_like_name = (
        2 <= len(candidate) <= 60
        and len(candidate.split()) <= 5
        and not any(ch.isdigit() for ch in candidate)
        and intr.day is None
        and intr.affirmation is None
    )
    return candidate.title() if looks_like_name else None


def _spread(slots: list[datetime], limit: int) -> list[datetime]:
    """Pick up to `limit` slots spread across the day instead of only the earliest."""
    if len(slots) <= limit:
        return slots
    step = (len(slots) - 1) / (limit - 1)
    return [slots[round(i * step)] for i in range(limit)]
