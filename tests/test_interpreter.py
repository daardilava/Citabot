from __future__ import annotations

import unittest
from datetime import date, time

from citabot.application.ports import Intent, Interpretation
from citabot.infrastructure.nlu.rules import RuleBasedInterpreter

TODAY = date(2026, 11, 12)  # Thursday


class InterpreterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.interpreter = RuleBasedInterpreter()

    def read(self, text: str) -> Interpretation:
        return self.interpreter.interpret(text, TODAY)

    def test_intents(self) -> None:
        cases = {
            "Hola, buenas tardes": Intent.GREETING,
            "Quiero agendar una cita": Intent.BOOK,
            "necesito un turno": Intent.BOOK,
            "Cancelar cita": Intent.CANCEL,
            "Ver mis citas": Intent.MY_APPOINTMENTS,
            "¿A qué hora abren?": Intent.HOURS,
            "Horarios y precios": Intent.HOURS,
            "¿Cuánto cuesta la limpieza?": Intent.SERVICES,
            "Hablar con una persona": Intent.HUMAN,
            "muchas gracias": Intent.THANKS,
            "Confirmo asistencia": Intent.CONFIRM_ATTENDANCE,
            "¿Tienen parqueadero?": Intent.UNKNOWN,
            "¿Puedo cancelar sin costo?": Intent.UNKNOWN,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertIs(self.read(text).intent, expected)

    def test_days(self) -> None:
        cases = {
            "hoy": date(2026, 11, 12),
            "mañana": date(2026, 11, 13),
            "pasado mañana": date(2026, 11, 14),
            "el lunes": date(2026, 11, 16),
            "jueves": date(2026, 11, 12),
            "Vie 13/11": date(2026, 11, 13),
            "20 de noviembre": date(2026, 11, 20),
            "5/1": date(2027, 1, 5),  # already past this year -> next year
            "a las 9 de la mañana": None,  # part of the day, not "tomorrow"
            "31/2": None,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.read(text).day, expected)

    def test_times(self) -> None:
        cases = {
            "10:30": time(10, 30),
            "a las 3": time(15, 0),  # unmarked small hours mean the afternoon
            "a las 9 de la mañana": time(9, 0),
            "4:30 pm": time(16, 30),
            "8 am": time(8, 0),
            "a las 5 de la tarde": time(17, 0),
            "mañana": None,
            "25:00": None,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.read(text).clock_time, expected)

    def test_bare_number_and_affirmation(self) -> None:
        self.assertEqual(self.read("10").bare_hour, time(10, 0))
        self.assertIsNone(self.read("10 personas").bare_hour)
        self.assertIs(self.read("Sí, confirmar").affirmation, True)
        self.assertIs(self.read("no, gracias").affirmation, False)
        self.assertIsNone(self.read("tal vez").affirmation)


if __name__ == "__main__":
    unittest.main()
