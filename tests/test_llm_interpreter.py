from __future__ import annotations

import json
import unittest
from datetime import date, time
from types import SimpleNamespace
from typing import Any

from citabot.application.ports import Intent
from citabot.infrastructure.nlu.llm import LlmInterpreter, build_user_message, to_interpretation
from citabot.infrastructure.nlu.rules import RuleBasedInterpreter

TODAY = date(2026, 11, 12)  # Thursday


class FakeClient:
    """Stands in for `anthropic.Anthropic`: returns a canned reply or raises."""

    def __init__(self, reply: Any = None, stop_reason: str = "end_turn", error: Exception | None = None):
        self.calls: list[dict[str, Any]] = []
        self._reply = reply
        self._stop_reason = stop_reason
        self._error = error
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        text = self._reply if isinstance(self._reply, str) else json.dumps(self._reply)
        return SimpleNamespace(
            stop_reason=self._stop_reason,
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        )


def interpreter(client: FakeClient) -> LlmInterpreter:
    return LlmInterpreter(client, "test-model", RuleBasedInterpreter())


class LlmInterpreterTest(unittest.TestCase):
    def test_maps_the_model_reply(self) -> None:
        client = FakeClient({"intent": "book", "date": "2026-11-16", "time": "15:00", "affirmation": "none"})
        result = interpreter(client).interpret("mañana no puedo, mejor el lunes tipo 3", TODAY)
        self.assertIs(result.intent, Intent.BOOK)
        self.assertEqual(result.day, date(2026, 11, 16))
        self.assertEqual(result.clock_time, time(15, 0))
        self.assertIsNone(result.affirmation)

        request = client.calls[0]
        self.assertEqual(request["model"], "test-model")
        self.assertEqual(request["output_config"]["format"]["type"], "json_schema")
        self.assertIn("mejor el lunes", request["messages"][0]["content"])

    def test_empty_fields_and_affirmation(self) -> None:
        client = FakeClient({"intent": "unknown", "date": "", "time": "", "affirmation": "yes"})
        result = interpreter(client).interpret("de una", TODAY)
        self.assertIsNone(result.day)
        self.assertIsNone(result.clock_time)
        self.assertIs(result.affirmation, True)

    def test_falls_back_to_rules(self) -> None:
        failures = {
            "network error": FakeClient(error=ConnectionError("offline")),
            "refusal": FakeClient({}, stop_reason="refusal"),
            "not json": FakeClient("lo siento"),
            "bad date": FakeClient({"intent": "book", "date": "31/02", "time": "", "affirmation": "none"}),
            "bad intent": FakeClient({"intent": "pizza", "date": "", "time": "", "affirmation": "none"}),
        }
        for name, client in failures.items():
            with self.subTest(name), self.assertLogs("citabot.infrastructure.nlu.llm", "WARNING"):
                result = interpreter(client).interpret("Quiero agendar una cita mañana a las 9", TODAY)
                self.assertIs(result.intent, Intent.BOOK)
                self.assertEqual(result.day, date(2026, 11, 13))
                self.assertEqual(result.clock_time, time(9, 0))

    def test_bare_number_skips_the_model(self) -> None:
        client = FakeClient(error=AssertionError("must not be called"))
        result = interpreter(client).interpret(" 10 ", TODAY)
        self.assertEqual(result.bare_hour, time(10, 0))
        self.assertEqual(client.calls, [])

    def test_user_message_carries_a_calendar(self) -> None:
        message = build_user_message("el viernes", TODAY)
        self.assertIn("Hoy es jueves 2026-11-12", message)
        self.assertIn("viernes 2026-11-13", message)
        self.assertIn("jueves 2026-11-26", message)

    def test_to_interpretation_rejects_missing_fields(self) -> None:
        with self.assertRaises(KeyError):
            to_interpretation({"intent": "book"})


if __name__ == "__main__":
    unittest.main()
