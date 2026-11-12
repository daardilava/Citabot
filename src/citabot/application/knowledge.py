"""Knowledge base use cases: the retrieval half of the RAG pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from citabot.domain.errors import ValidationError
from citabot.domain.models import KnowledgeDoc

from .ports import (
    AnswerGenerator,
    AnswerUnavailableError,
    Clock,
    KnowledgeRepository,
    Passage,
    PassageRetriever,
)

MAX_TITLE = 120
MAX_CONTENT = 20_000


@dataclass(frozen=True)
class Answer:
    text: str
    source_title: str
    confidence: float


class KnowledgeService:
    def __init__(
        self,
        docs: KnowledgeRepository,
        retriever: PassageRetriever,
        generator: AnswerGenerator,
        clock: Clock,
        min_confidence: float = 0.5,
        fallback: AnswerGenerator | None = None,
        whole_base_max_chars: int = 0,
    ) -> None:
        self._docs = docs
        self._retriever = retriever
        self._generator = generator
        self._clock = clock
        self._min_confidence = min_confidence
        # Used when `generator` raises AnswerUnavailableError.
        self._fallback = fallback
        # A knowledge base up to this size is handed whole to the generator, which
        # then finds answers that share no words with the question. 0 disables it.
        self._whole_base_max_chars = whole_base_max_chars

    def list_docs(self, business_id: int) -> list[KnowledgeDoc]:
        return self._docs.list(business_id)

    def add_doc(self, business_id: int, title: str, content: str) -> KnowledgeDoc:
        title, content = title.strip(), content.strip()
        if not title or len(title) > MAX_TITLE:
            raise ValidationError(f"El título es obligatorio (máximo {MAX_TITLE} caracteres).")
        if not content or len(content) > MAX_CONTENT:
            raise ValidationError(f"El contenido es obligatorio (máximo {MAX_CONTENT} caracteres).")
        return self._docs.add(business_id, title, content, self._clock.now())

    def delete_doc(self, business_id: int, doc_id: int) -> None:
        self._docs.delete(business_id, doc_id)

    def search(self, business_id: int, query: str, limit: int = 3) -> list[Passage]:
        return self._retriever.search(self._docs.list(business_id), query, limit)

    def answer(self, business_id: int, question: str) -> Answer | None:
        """Answer only from the knowledge base; otherwise let the caller hand off.

        The generator reads the whole base when it is small, or the passages that
        retrieval is confident about when it is not.
        """
        docs = self._docs.list(business_id)
        passages = self._retriever.search(docs, question, 3)
        confident = [p for p in passages if p.confidence >= self._min_confidence]
        context = self._whole_base(docs) or confident
        if not context:
            return None
        try:
            text = self._generator.generate(question, context)
        except AnswerUnavailableError:
            if self._fallback is None:
                raise
            # The fallback quotes a passage, so it only gets what retrieval trusts.
            text = self._fallback.generate(question, confident) if confident else None
        if text is None:
            return None
        return Answer(text=text, source_title=context[0].title, confidence=context[0].confidence)

    def _whole_base(self, docs: list[KnowledgeDoc]) -> list[Passage]:
        size = sum(len(doc.title) + len(doc.content) for doc in docs)
        if not 0 < size <= self._whole_base_max_chars:
            return []
        return [Passage(doc.id, doc.title, doc.content, score=0.0, confidence=1.0) for doc in docs]
