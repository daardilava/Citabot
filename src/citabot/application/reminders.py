"""Appointment reminders for the next day.

In production a scheduler (cron, a queue worker) calls `send_due` every few
minutes. Outside WhatsApp's 24-hour service window the message must be an
approved *utility template*; the gateway adapter is where that mapping lives.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from citabot.domain.models import AppointmentStatus, Contact, Message, Sender

from .messenger import ConversationMessenger, Reply
from .ports import (
    AppointmentRepository,
    BusinessRepository,
    Clock,
    ContactRepository,
    ConversationRepository,
    UnitOfWork,
)
from .text import hhmm

REMINDER_OPTIONS = ["Confirmo asistencia", "Cancelar cita"]


class ReminderService:
    def __init__(
        self,
        uow: UnitOfWork,
        businesses: BusinessRepository,
        appointments: AppointmentRepository,
        contacts: ContactRepository,
        conversations: ConversationRepository,
        messenger: ConversationMessenger,
        clock: Clock,
    ) -> None:
        self._uow = uow
        self._businesses = businesses
        self._appointments = appointments
        self._contacts = contacts
        self._conversations = conversations
        self._messenger = messenger
        self._clock = clock

    def send_due(self, business_id: int) -> int:
        """Remind every confirmed appointment happening tomorrow. Idempotent."""
        outbox: list[tuple[Contact, list[Message]]] = []
        with self._uow:
            now = self._clock.now()
            business = self._businesses.get(business_id)
            tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
            due = [
                a
                for a in self._appointments.list_between(
                    business_id, tomorrow, tomorrow + timedelta(days=1), only_confirmed=True
                )
                if not a.reminder_sent and a.status is AppointmentStatus.CONFIRMED
            ]
            for appointment in due:
                contact = self._contacts.get(appointment.contact_id)
                service = self._businesses.get_service(business_id, appointment.service_id)
                conversation = self._conversations.find_by_contact(contact.id) or (
                    self._conversations.add(business_id, contact.id, now)
                )
                greeting = f"Hola {contact.name.split()[0]}" if contact.name else "Hola"
                reply = Reply(
                    f"{greeting} 👋, te recordamos tu cita de {service.name.lower()} "
                    f"mañana a las {hhmm(appointment.starts_at)} en {business.name}.",
                    REMINDER_OPTIONS,
                )
                conversation.state["options"] = reply.options
                messages = self._messenger.record(conversation, Sender.BOT, [reply])
                appointment.reminder_sent = True
                self._appointments.save(appointment)
                outbox.append((contact, messages))
        for contact, messages in outbox:
            self._messenger.deliver(contact, messages)
        return len(outbox)
