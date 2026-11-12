from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from citabot.domain.errors import SlotUnavailableError, ValidationError
from citabot.domain.models import Appointment, AppointmentSource, AppointmentStatus, ConversationMode
from tests import support

PHONE = "+57 300 000 0000"
B = support.BUSINESS_ID


class AgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.c = support.make_container()
        self.addCleanup(self.c.db.close)

    def say(self, text: str, phone: str = PHONE, name: str | None = "Diego Abril") -> list[str]:
        self.last = self.c.agent.handle_inbound(B, phone, text, name)
        return [m.text for m in self.last.replies]

    def options(self) -> list[str]:
        return self.last.replies[-1].options

    def appointments(self, phone: str = PHONE) -> list[Appointment]:
        contact = self.c.contacts.find_by_phone(B, phone)
        assert contact is not None
        return self.c.booking.upcoming_for_contact(contact.id)


class BookingFlowTest(AgentTestCase):
    def test_step_by_step_booking_with_buttons(self) -> None:
        self.say("Hola")
        self.assertIn("Agendar cita", self.options())
        self.say("Agendar cita")
        self.assertIn("Limpieza dental", self.options())
        self.say("Limpieza dental")
        self.assertEqual(self.options()[0], "Vie 13/11")
        self.say("Vie 13/11")
        self.assertIn("09:00", self.options())
        self.say("09:00")
        self.assertEqual(self.options(), ["Sí, confirmar", "Cambiar hora", "Cancelar"])
        (reply,) = self.say("Sí, confirmar")
        self.assertIn("confirmada", reply)

        (appointment,) = self.appointments()
        self.assertEqual(appointment.starts_at, datetime(2026, 11, 13, 9, 0))
        self.assertIs(appointment.source, AppointmentSource.WHATSAPP)

    def test_one_message_fills_service_day_and_time(self) -> None:
        (reply,) = self.say("Quiero agendar un blanqueamiento el sábado a las 11")
        self.assertIn("Blanqueamiento", reply)
        self.assertIn("Sábado 14 de noviembre", reply)
        self.say("si")
        (appointment,) = self.appointments()
        self.assertEqual(appointment.ends_at - appointment.starts_at, timedelta(minutes=60))

    def test_numeric_reply_selects_the_offered_option(self) -> None:
        self.say("agendar")
        (reply,) = self.say("2")  # second service in the list
        self.assertIn("limpieza dental", reply)

    def test_taken_slot_is_rejected_and_alternatives_offered(self) -> None:
        # The demo data already has an appointment on Friday at 10:00.
        (reply,) = self.say("Quiero agendar una limpieza mañana a las 10")
        self.assertIn("A las 10:00 no tengo disponibilidad", reply)
        self.assertNotIn("10:00", self.options())

    def test_closed_day_is_explained(self) -> None:
        (reply,) = self.say("Quiero agendar una limpieza el domingo")
        self.assertIn("no atendemos", reply)

    def test_question_in_the_middle_of_booking_is_answered_then_resumed(self) -> None:
        self.say("Quiero agendar una limpieza mañana")
        answer, prompt = self.say("¿Tienen parqueadero?")
        self.assertIn("parqueadero", answer)
        self.assertIn("horarios", prompt)

    def test_unknown_customer_is_asked_for_a_name(self) -> None:
        (reply,) = self.say("Quiero agendar una limpieza mañana a las 9", name=None)
        self.assertIn("nombre", reply)
        (reply,) = self.say("pedro pérez", name=None)
        self.assertIn("Perfecto, Pedro", reply)

    def test_customer_can_abort(self) -> None:
        self.say("Quiero agendar una limpieza mañana a las 9")
        self.say("Cancelar")
        self.assertEqual(self.appointments(), [])
        self.assertNotIn("flow", self.c.inbox.thread(B, self.last.conversation_id).conversation.state)

    def test_race_for_the_same_slot_has_one_winner(self) -> None:
        self.say("Quiero agendar una limpieza mañana a las 9")
        other = self.c.contacts.add(B, "+57 999", "Otra Persona", support.NOW)
        self.c.booking.book(B, other.id, 2, datetime(2026, 11, 13, 9, 0), AppointmentSource.DASHBOARD)
        (reply,) = self.say("si")
        self.assertIn("A las 09:00 no tengo disponibilidad", reply)
        self.assertEqual(self.appointments(), [])
        with self.assertRaises(SlotUnavailableError):
            self.c.booking.book(B, other.id, 2, datetime(2026, 11, 13, 9, 0), AppointmentSource.DASHBOARD)


class OtherIntentsTest(AgentTestCase):
    def test_cancel_flow(self) -> None:
        self.say("Quiero agendar una limpieza mañana a las 9")
        self.say("si")
        (reply,) = self.say("Cancelar cita")
        self.assertIn("¿Cancelo tu cita", reply)
        self.say("Sí, cancelar")
        self.assertEqual(self.appointments(), [])

    def test_faq_is_answered_from_the_knowledge_base(self) -> None:
        (reply,) = self.say("aceptan tarjeta?")
        self.assertIn("tarjeta débito", reply)

    def test_unknown_question_flags_the_conversation(self) -> None:
        (reply,) = self.say("¿Hacen carillas de porcelana?")
        self.assertIn("No tengo esa información", reply)
        thread = self.c.inbox.thread(B, self.last.conversation_id)
        self.assertTrue(thread.conversation.needs_attention)

    def test_handoff_silences_the_bot_until_it_is_switched_back(self) -> None:
        self.say("Hablar con una persona")
        self.assertEqual(self.say("¿hola?"), [])
        conversation_id = self.last.conversation_id
        self.assertIs(self.c.inbox.thread(B, conversation_id).conversation.mode, ConversationMode.HUMAN)

        self.c.inbox.reply_as_agent(B, conversation_id, "Hola, soy Marta. ¿En qué te ayudo?")
        self.c.inbox.update(B, conversation_id, mode=ConversationMode.BOT)
        self.assertEqual(len(self.say("Hola")), 1)

    def test_hours_and_services(self) -> None:
        (reply,) = self.say("¿A qué hora abren?")
        self.assertIn("Lunes a viernes: 08:00–12:00 y 14:00–18:00", reply)
        self.assertIn("Domingo: cerrado", reply)
        (reply,) = self.say("precios")
        self.assertIn("Limpieza dental (30 min) — $120.000", reply)


class RemindersTest(AgentTestCase):
    def test_reminders_are_sent_once_for_tomorrow(self) -> None:
        self.say("Quiero agendar una limpieza mañana a las 9")
        self.say("si")
        self.assertEqual(self.c.reminders.send_due(B), 2)  # this one + Laura's demo appointment
        self.assertEqual(self.c.reminders.send_due(B), 0)
        last = self.c.inbox.thread(B, self.last.conversation_id).messages[-1]
        self.assertIn("te recordamos tu cita", last.text)
        (reply,) = self.say("Confirmo asistencia")
        self.assertIn("confirmada tu asistencia", reply)

    def test_cancelled_appointment_cannot_be_reactivated(self) -> None:
        self.say("Quiero agendar una limpieza mañana a las 9")
        self.say("si")
        (appointment,) = self.appointments()
        self.c.booking.set_status(B, appointment.id, AppointmentStatus.CANCELLED)
        with self.assertRaises(ValidationError):
            self.c.booking.set_status(B, appointment.id, AppointmentStatus.CONFIRMED)


if __name__ == "__main__":
    unittest.main()
