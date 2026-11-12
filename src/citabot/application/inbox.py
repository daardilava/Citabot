"""Team inbox use cases: read conversations, take over from the bot, reply."""

from __future__ import annotations

from dataclasses import dataclass

from citabot.domain.errors import ValidationError
from citabot.domain.models import Contact, Conversation, ConversationMode, Message, Sender

from .messenger import ConversationMessenger, Reply
from .ports import ContactRepository, ConversationRepository, ConversationSummary, UnitOfWork

MAX_REPLY_CHARS = 2000


@dataclass(frozen=True)
class Thread:
    conversation: Conversation
    contact: Contact
    messages: list[Message]


class InboxService:
    def __init__(
        self,
        uow: UnitOfWork,
        conversations: ConversationRepository,
        contacts: ContactRepository,
        messenger: ConversationMessenger,
    ) -> None:
        self._uow = uow
        self._conversations = conversations
        self._contacts = contacts
        self._messenger = messenger

    def list(self, business_id: int) -> list[ConversationSummary]:
        return self._conversations.list_summaries(business_id)

    def thread(self, business_id: int, conversation_id: int) -> Thread:
        conversation = self._conversations.get(business_id, conversation_id)
        return Thread(
            conversation=conversation,
            contact=self._contacts.get(conversation.contact_id),
            messages=self._conversations.list_messages(conversation.id),
        )

    def reply_as_agent(self, business_id: int, conversation_id: int, text: str) -> Message:
        """A teammate answers. Replying takes the chat over so the bot stays quiet."""
        text = text.strip()
        if not text or len(text) > MAX_REPLY_CHARS:
            raise ValidationError(f"Escribe un mensaje de máximo {MAX_REPLY_CHARS} caracteres.")
        with self._uow:
            conversation = self._conversations.get(business_id, conversation_id)
            contact = self._contacts.get(conversation.contact_id)
            conversation.mode = ConversationMode.HUMAN
            conversation.needs_attention = False
            conversation.state = {}
            messages = self._messenger.record(conversation, Sender.AGENT, [Reply(text)])
        self._messenger.deliver(contact, messages)
        return messages[0]

    def update(
        self,
        business_id: int,
        conversation_id: int,
        mode: ConversationMode | None = None,
        needs_attention: bool | None = None,
    ) -> Conversation:
        with self._uow:
            conversation = self._conversations.get(business_id, conversation_id)
            if mode is not None and mode is not conversation.mode:
                conversation.mode = mode
                conversation.state = {}  # never resume a half-finished flow after a handover
                if mode is ConversationMode.BOT:
                    conversation.needs_attention = False
            if needs_attention is not None:
                conversation.needs_attention = needs_attention
            self._conversations.save(conversation)
            return conversation
