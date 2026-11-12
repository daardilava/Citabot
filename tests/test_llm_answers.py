from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from typing import Any

from citabot.application.knowledge import KnowledgeService
from citabot.application.ports import AnswerUnavailableError, Passage
from citabot.infrastructure.retrieval.bm25 import Bm25Retriever
from citabot.infrastructure.retrieval.extractive import ExtractiveAnswerGenerator
from citabot.infrastructure.retrieval.llm import LlmAnswerGenerator

from .support import BUSINESS_ID, make_container

PASSAGES = [Passage(1, "Parqueadero", "Contamos con parqueadero gratuito para pacientes.", 2.0, 1.0)]
MODULE = "citabot.infrastructure.retrieval.llm"
ANSWERED = {"answered": True, "answer": "Sí, hay parqueadero en el edificio."}
DECLINED = {"answered": False, "answer": ""}


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
            stop_reason=self._stop_reason, content=[SimpleNamespace(type="text", text=text)]
        )

    @property
    def prompt(self) -> str:
        return str(self.calls[-1]["messages"][0]["content"])


class LlmAnswerGeneratorTest(unittest.TestCase):
    def test_returns_the_written_answer(self) -> None:
        client = FakeClient({"answered": True, "answer": " Sí, el parqueadero es gratis para pacientes. "})
        answer = LlmAnswerGenerator(client, "test-model").generate("¿Tienen parqueadero?", PASSAGES)
        self.assertEqual(answer, "Sí, el parqueadero es gratis para pacientes.")
        self.assertIn("parqueadero gratuito", client.prompt)
        self.assertIn("¿Tienen parqueadero?", client.prompt)

    def test_returns_none_when_the_passages_do_not_answer(self) -> None:
        generator = LlmAnswerGenerator(FakeClient(DECLINED), "test-model")
        self.assertIsNone(generator.generate("¿El parqueadero tiene cargador eléctrico?", PASSAGES))

    def test_failures_raise_answer_unavailable(self) -> None:
        failures = {
            "network error": FakeClient(error=ConnectionError("offline")),
            "refusal": FakeClient({}, stop_reason="refusal"),
            "not json": FakeClient("claro que sí"),
            "empty answer": FakeClient({"answered": True, "answer": "  "}),
            "missing field": FakeClient({"answer": "Sí"}),
        }
        for name, client in failures.items():
            with (
                self.subTest(name),
                self.assertLogs(MODULE, "WARNING"),
                self.assertRaises(AnswerUnavailableError),
            ):
                LlmAnswerGenerator(client, "test-model").generate("¿Tienen parqueadero?", PASSAGES)


class KnowledgeWithLlmTest(unittest.TestCase):
    """KnowledgeService wired the way the container does it with ANSWER_PROVIDER=llm."""

    def service(self, client: FakeClient, whole_base_max_chars: int = 50_000) -> KnowledgeService:
        base = make_container().knowledge
        return KnowledgeService(
            base._docs,
            Bm25Retriever(),
            LlmAnswerGenerator(client, "test-model"),
            base._clock,
            fallback=ExtractiveAnswerGenerator(),
            whole_base_max_chars=whole_base_max_chars,
        )

    def test_small_base_is_read_whole(self) -> None:
        client = FakeClient(ANSWERED)
        # No word in common with the parking document, so BM25 alone finds nothing.
        answer = self.service(client).answer(BUSINESS_ID, "¿Dónde dejo el carro?")
        assert answer is not None
        self.assertEqual(answer.text, ANSWERED["answer"])
        self.assertIn("parqueadero", client.prompt)
        self.assertIn("Nequi", client.prompt)  # every document is there, not only the best match

    def test_large_base_uses_retrieval(self) -> None:
        client = FakeClient(ANSWERED)
        service = self.service(client, whole_base_max_chars=10)
        self.assertIsNone(service.answer(BUSINESS_ID, "¿Dónde dejo el carro?"))
        self.assertEqual(client.calls, [])  # nothing confident to show the model

        self.assertIsNotNone(service.answer(BUSINESS_ID, "¿Tienen parqueadero?"))
        self.assertIn("parqueadero", client.prompt)
        self.assertNotIn("Nequi", client.prompt)

    def test_hands_off_when_the_model_declines(self) -> None:
        self.assertIsNone(self.service(FakeClient(DECLINED)).answer(BUSINESS_ID, "¿Tienen parqueadero?"))

    def test_quotes_the_confident_passage_when_the_model_is_down(self) -> None:
        service = self.service(FakeClient(error=ConnectionError("offline")))
        with self.assertLogs(MODULE, "WARNING"):
            answer = service.answer(BUSINESS_ID, "¿Tienen parqueadero?")
            nothing = service.answer(BUSINESS_ID, "¿Dónde dejo el carro?")
        assert answer is not None
        self.assertIn("parqueadero", answer.text)
        self.assertIsNone(nothing)  # never quotes a document retrieval does not trust


if __name__ == "__main__":
    unittest.main()
