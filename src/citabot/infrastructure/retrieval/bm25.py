"""Lexical retrieval (BM25) over the business knowledge base.

Good enough for a few dozen short documents and has zero dependencies. The
`PassageRetriever` port is where an embedding search (pgvector, Qdrant…) or a
hybrid retriever plugs in once the corpus grows.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from citabot.application.ports import Passage
from citabot.application.text import words
from citabot.domain.models import KnowledgeDoc

_K1 = 1.5
_B = 0.75

_STOPWORDS = frozenset(
    """
    a al algo algun alguna ante aqui asi aun cada como con cual cuales cuando cuanto de del
    desde donde dos el ella ellos en entre era eres es esa ese eso esta estan estar este esto
    estos fue ha hace hacen hacer han hasta hay la las le les lo los mas me mi mis mucho muy
    necesito ni no nos o os otra otro para pero poco por porque puede pueden puedo que quiero
    quisiera saber se ser si sin sobre son su sus tambien tanto te tengo tiene tienen todo
    todos tu tus un una uno unos usted ustedes va y ya yo hola buenas buenos dias tardes
    gracias favor debo deben
    """.split()  # noqa: SIM905 - a word list reads better as text
)


# Longest first. Crude on purpose: it only has to make "aceptan" meet "aceptamos"
# and "tarjetas" meet "tarjeta" inside one small knowledge base.
_SUFFIXES = (
    "amientos", "imientos", "amiento", "imiento", "aciones", "acion", "adores", "ador",
    "amos", "emos", "imos", "ando", "iendo", "aron", "ieron", "aban", "ados", "adas",
    "idos", "idas", "ado", "ada", "ido", "ida", "an", "en", "ar", "er", "ir", "as", "es",
    "os", "a", "e", "o", "s",
)  # fmt: skip
_MIN_STEM = 3


def _stem(token: str) -> str:
    """Light Spanish suffix stripping."""
    if token.isdigit():
        return token
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= _MIN_STEM:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in words(text) if t not in _STOPWORDS and len(t) > 1]


@dataclass(frozen=True)
class _Chunk:
    doc_id: int
    title: str
    text: str
    terms: Counter[str]
    length: int


def _chunks(docs: Sequence[KnowledgeDoc]) -> list[_Chunk]:
    """One passage per paragraph; the title is indexed with each one."""
    chunks = []
    for doc in docs:
        for paragraph in re.split(r"\n\s*\n", doc.content):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            tokens = tokenize(doc.title) + tokenize(paragraph)
            chunks.append(_Chunk(doc.id, doc.title, paragraph, Counter(tokens), len(tokens)))
    return chunks


class Bm25Retriever:
    def search(self, docs: Sequence[KnowledgeDoc], query: str, limit: int = 3) -> list[Passage]:
        chunks = _chunks(docs)
        terms = list(dict.fromkeys(tokenize(query)))
        if not chunks or not terms:
            return []

        total = len(chunks)
        average_length = sum(c.length for c in chunks) / total
        document_frequency = Counter(term for c in chunks for term in c.terms)

        def idf(term: str) -> float:
            df = document_frequency.get(term, 0)
            return math.log(1 + (total - df + 0.5) / (df + 0.5))

        query_weight = sum(idf(t) for t in terms)
        results = []
        for chunk in chunks:
            score = 0.0
            matched_weight = 0.0
            for term in terms:
                frequency = chunk.terms.get(term, 0)
                if not frequency:
                    continue
                norm = frequency + _K1 * (1 - _B + _B * chunk.length / average_length)
                score += idf(term) * frequency * (_K1 + 1) / norm
                matched_weight += idf(term)
            if score > 0:
                results.append(
                    Passage(
                        doc_id=chunk.doc_id,
                        title=chunk.title,
                        text=chunk.text,
                        score=round(score, 4),
                        confidence=round(matched_weight / query_weight, 2),
                    )
                )
        results.sort(key=lambda p: p.score, reverse=True)
        return results[:limit]
