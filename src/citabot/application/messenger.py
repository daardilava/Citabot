"""Records outbound messages and hands them to the messaging gateway."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from citabot.domain.models import Contact, Conversation, Direction, Message, Sender

from .ports import Clock, ConversationRepository, MessagingGateway

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reply:
    text: str
    options: list[str] = field(default_factory=list)


class ConversationMessenger:
    def __init__(
        self, conversations: ConversationRepository, gateway: MessagingGateway, clock: Clock
    ) -> None:
        self._conversations = conversations
        self._gateway = gateway
        self._clock = clock

    def record(self, conversation: Conversation, sender: Sender, replies: Sequence[Reply]) -> list[Message]:
        """Persist outbound messages. Call inside the caller's transaction."""
        now = self._clock.now()
        messages = [
            self._conversations.add_message(
                conversation.id, Direction.OUTBOUND, sender, reply.text, reply.options, now
            )
            for reply in replies
        ]
        if messages:
            conversation.updated_at = now
            self._conversations.save(conversation)
        return messages

    def deliver(self, contact: Contact, messages: Sequence[Message]) -> None:
        """Send through the gateway. Call after commit: network I/O never holds the DB lock."""
        for message in messages:
            try:
                self._gateway.send_text(contact.phone, message.text, message.options)
            except Exception:  # a provider outage must not lose the stored reply
                logger.exception("No se pudo entregar el mensaje %s", message.id)
