"""Answer generator that quotes the best passage verbatim.

It cannot hallucinate, which is the right default for a business bot. To get
fluent, synthesised answers, implement `AnswerGenerator` with an LLM call that
receives the question and the passages as grounded context.
"""

from __future__ import annotations

from collections.abc import Sequence

from citabot.application.ports import Passage

MAX_ANSWER_CHARS = 600


class ExtractiveAnswerGenerator:
    def generate(self, question: str, passages: Sequence[Passage]) -> str:
        text = passages[0].text
        if len(text) > MAX_ANSWER_CHARS:
            text = text[:MAX_ANSWER_CHARS].rsplit(" ", 1)[0] + "…"
        return text
