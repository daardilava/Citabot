"""How inbound messages are stored, deduplicated and answered without blocking others."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from citabot.application.ports import Interpretation, Passage
from citabot.domain.models import ConversationMode, Sender
from citabot.infrastructure.background import BackgroundRunner
from citabot.infrastructure.nlu.rules import RuleBasedInterpreter
from citabot.infrastructure.sqlite.db import Database

from . import support

B = support.BUSINESS_ID
PHONE = "+573009998877"


class InboundTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.c = support.make_container()
        self.addCleanup(self.c.close)

    def texts(self, conversation_id: int, sender: Sender) -> list[str]:
        thread = self.c.inbox.thread(B, conversation_id)
        return [m.text for m in thread.messages if m.sender is sender]


class DeduplicationTest(InboundTestCase):
    def test_a_redelivered_message_is_stored_and_answered_once(self) -> None:
        first = self.c.agent.handle_inbound(B, PHONE, "Hola", "Ana", message_id="wamid.1")
        again = self.c.agent.handle_inbound(B, PHONE, "Hola", "Ana", message_id="wamid.1")

        self.assertFalse(first.duplicate)
        self.assertEqual(len(first.replies), 1)
        self.assertTrue(again.duplicate)
        self.assertEqual(again.replies, [])
        self.assertEqual(self.texts(first.conversation_id, Sender.CUSTOMER), ["Hola"])
        self.assertEqual(len(self.texts(first.conversation_id, Sender.BOT)), 1)

    def test_messages_without_an_id_are_never_duplicates(self) -> None:
        first = self.c.agent.handle_inbound(B, PHONE, "Hola")
        again = self.c.agent.handle_inbound(B, PHONE, "Hola")
        self.assertFalse(again.duplicate)
        self.assertEqual(self.texts(first.conversation_id, Sender.CUSTOMER), ["Hola", "Hola"])


class TwoPhaseTest(InboundTestCase):
    def test_receive_stores_the_message_before_any_reply(self) -> None:
        received = self.c.agent.receive(B, PHONE, "Hola", "Ana")
        self.assertEqual(self.texts(received.conversation_id, Sender.CUSTOMER), ["Hola"])
        self.assertEqual(self.texts(received.conversation_id, Sender.BOT), [])

        result = self.c.agent.respond(received)
        self.assertEqual(len(result.replies), 1)

    def test_no_reply_when_a_teammate_took_over_in_between(self) -> None:
        received = self.c.agent.receive(B, PHONE, "Hola", "Ana")
        self.c.inbox.update(B, received.conversation_id, mode=ConversationMode.HUMAN, needs_attention=None)

        self.assertEqual(self.c.agent.respond(received).replies, [])
        self.assertEqual(self.texts(received.conversation_id, Sender.BOT), [])

    def test_a_message_to_a_human_owned_chat_flags_it(self) -> None:
        first = self.c.agent.handle_inbound(B, PHONE, "Hablar con una persona", "Ana")
        self.c.inbox.update(B, first.conversation_id, mode=None, needs_attention=False)

        result = self.c.agent.handle_inbound(B, PHONE, "¿Siguen ahí?")
        self.assertEqual(result.replies, [])
        self.assertTrue(self.c.inbox.thread(B, first.conversation_id).conversation.needs_attention)

    def test_a_question_inside_the_booking_flow_is_recorded_once(self) -> None:
        """The dialogue runs twice (before and after the knowledge lookup); only one run commits."""
        self.c.agent.handle_inbound(B, PHONE, "Quiero agendar una cita", "Ana")
        result = self.c.agent.handle_inbound(B, PHONE, "¿Tienen parqueadero?")

        self.assertEqual(len(result.replies), 2)  # the answer, then the pending question again
        self.assertEqual(
            self.texts(result.conversation_id, Sender.CUSTOMER),
            ["Quiero agendar una cita", "¿Tienen parqueadero?"],
        )
        self.assertEqual(len(self.texts(result.conversation_id, Sender.BOT)), 3)


class LanguageOutsideTransactionTest(InboundTestCase):
    """Slow model calls must never hold the database lock."""

    def test_interpreter_and_knowledge_run_without_a_transaction(self) -> None:
        db = self.c.db
        depths: dict[str, int] = {}

        class SpyInterpreter(RuleBasedInterpreter):
            def interpret(self, text: str, today: date) -> Interpretation:
                depths["interpreter"] = db._depth
                return super().interpret(text, today)

        quoter = self.c.knowledge._generator

        class SpyGenerator:
            def generate(self, question: str, passages: Sequence[Passage]) -> str | None:
                depths["generator"] = db._depth
                return quoter.generate(question, passages)

        self.c.agent._interpreter = SpyInterpreter()
        self.c.knowledge._generator = SpyGenerator()
        result = self.c.agent.handle_inbound(B, PHONE, "¿Tienen parqueadero?", "Ana")

        self.assertIn("parqueadero", result.replies[0].text)
        self.assertEqual(depths, {"interpreter": 0, "generator": 0})

    def test_a_slow_reply_does_not_block_another_customer(self) -> None:
        entered, release = threading.Event(), threading.Event()

        class SlowForOne(RuleBasedInterpreter):
            def interpret(self, text: str, today: date) -> Interpretation:
                if text == "lento":
                    entered.set()
                    release.wait(timeout=5)
                return super().interpret(text, today)

        self.c.agent._interpreter = SlowForOne()
        slow = threading.Thread(target=self.c.agent.handle_inbound, args=(B, "+573000000001", "lento"))
        slow.start()
        self.addCleanup(slow.join)
        self.addCleanup(release.set)
        self.assertTrue(entered.wait(timeout=5))

        done = threading.Event()

        def other_customer() -> None:
            self.c.agent.handle_inbound(B, "+573000000002", "Hola")
            done.set()

        threading.Thread(target=other_customer, daemon=True).start()
        self.assertTrue(done.wait(timeout=5), "the second customer waited for the first one's model call")


class BackgroundRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = BackgroundRunner()
        self.addCleanup(self.runner.shutdown)

    def test_same_key_runs_in_order_and_survives_a_failure(self) -> None:
        seen: list[int] = []

        def task(number: int) -> None:
            if number == 2:
                raise ValueError("boom")
            seen.append(number)

        with self.assertLogs("citabot.infrastructure.background", "ERROR"):
            for number in range(50):
                self.runner.submit(lambda n=number: task(n), key="chat")  # type: ignore[misc]
            self.assertTrue(self.runner.wait_idle(timeout=5))
        self.assertEqual(seen, [n for n in range(50) if n != 2])

    def test_different_keys_run_in_parallel(self) -> None:
        release, finished = threading.Event(), threading.Event()
        self.runner.submit(lambda: release.wait(timeout=5), key="a")
        self.runner.submit(finished.set, key="b")
        self.assertTrue(finished.wait(timeout=5))
        release.set()
        self.assertTrue(self.runner.wait_idle(timeout=5))


class MigrationTest(unittest.TestCase):
    def test_an_older_database_gains_the_external_id_column(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "old.db")
            old = sqlite3.connect(path)
            old.execute(
                "CREATE TABLE messages (id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL, "
                "direction TEXT NOT NULL, sender TEXT NOT NULL, text TEXT NOT NULL, "
                "options TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL)"
            )
            old.commit()
            old.close()

            db = Database(path)
            try:
                columns = {row["name"] for row in db.query("PRAGMA table_info(messages)")}
                self.assertIn("external_id", columns)
                Database(path).close()  # opening it again is a no-op
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
