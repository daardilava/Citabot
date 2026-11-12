"""Composition root: the only module that knows which adapter backs each port."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass

from citabot.application.agent import AgentService
from citabot.application.auth import AuthService
from citabot.application.booking import BookingService
from citabot.application.business import BusinessService
from citabot.application.inbox import InboxService
from citabot.application.knowledge import KnowledgeService
from citabot.application.messenger import ConversationMessenger
from citabot.application.ports import (
    AnswerGenerator,
    Clock,
    DashboardReadModel,
    MessageInterpreter,
    MessagingGateway,
)
from citabot.application.reminders import ReminderService
from citabot.config import Settings
from citabot.domain.errors import NotFoundError
from citabot.infrastructure.anthropic_client import create_client
from citabot.infrastructure.background import BackgroundRunner
from citabot.infrastructure.clock import SystemClock
from citabot.infrastructure.messaging.simulator import SimulatorGateway
from citabot.infrastructure.messaging.whatsapp_cloud import WhatsAppCloudGateway
from citabot.infrastructure.nlu.llm import LlmInterpreter
from citabot.infrastructure.nlu.rules import RuleBasedInterpreter
from citabot.infrastructure.retrieval.bm25 import Bm25Retriever
from citabot.infrastructure.retrieval.extractive import ExtractiveAnswerGenerator
from citabot.infrastructure.retrieval.llm import LlmAnswerGenerator
from citabot.infrastructure.security import ScryptHasher
from citabot.infrastructure.seed import ensure_demo_user, reset_demo, seed_demo
from citabot.infrastructure.sqlite.db import Database
from citabot.infrastructure.sqlite.repositories import (
    SqliteAppointmentRepository,
    SqliteBusinessRepository,
    SqliteContactRepository,
    SqliteConversationRepository,
    SqliteDashboardReadModel,
    SqliteKnowledgeRepository,
    SqliteSessionRepository,
    SqliteUserRepository,
)


@dataclass
class Container:
    settings: Settings
    db: Database
    clock: Clock
    agent: AgentService
    booking: BookingService
    business: BusinessService
    inbox: InboxService
    knowledge: KnowledgeService
    reminders: ReminderService
    dashboard: DashboardReadModel
    contacts: SqliteContactRepository
    background: BackgroundRunner
    auth: AuthService

    def close(self) -> None:
        """Finish the replies in progress, then release the database."""
        self.background.shutdown()
        self.db.close()

    def reset_demo(self) -> None:
        """Load the demo data again. Other businesses and all accounts are untouched."""
        reset_demo(self.db, self.settings.default_business_id, self.clock.now())


def _gateway(settings: Settings) -> MessagingGateway:
    if settings.messaging_provider == "whatsapp_cloud":
        return WhatsAppCloudGateway(
            settings.whatsapp_access_token,
            settings.whatsapp_phone_number_id,
            settings.whatsapp_api_version,
        )
    return SimulatorGateway()


def _language(settings: Settings) -> tuple[MessageInterpreter, AnswerGenerator | None]:
    """Rules and quoting by default; each port can be switched to the LLM on its own.

    Returns the interpreter and the LLM answer generator, or None when answers are quoted.
    """
    interpreter: MessageInterpreter = RuleBasedInterpreter()
    writer: AnswerGenerator | None = None
    if "llm" in (settings.nlu_provider, settings.answer_provider):
        client = create_client(ipv4_only=settings.llm_ipv4_only)
        if settings.nlu_provider == "llm":
            interpreter = LlmInterpreter(client, settings.llm_model, fallback=interpreter)
        if settings.answer_provider == "llm":
            writer = LlmAnswerGenerator(client, settings.llm_model)
    return interpreter, writer


def build_container(
    settings: Settings, clock: Clock | None = None, gateway: MessagingGateway | None = None
) -> Container:
    clock = clock or SystemClock()
    db = Database(settings.db_path)

    businesses = SqliteBusinessRepository(db)
    contacts = SqliteContactRepository(db)
    conversations = SqliteConversationRepository(db)
    appointments = SqliteAppointmentRepository(db)
    docs = SqliteKnowledgeRepository(db)

    if not businesses.exists_any():
        seed_demo(db, clock.now())
    else:
        # A database from before accounts existed has the demo business but no demo user.
        with contextlib.suppress(NotFoundError):
            businesses.get(settings.default_business_id)
            ensure_demo_user(db, settings.default_business_id, clock.now())

    messenger = ConversationMessenger(conversations, gateway or _gateway(settings), clock)
    booking = BookingService(db, businesses, appointments, contacts, clock)
    interpreter, writer = _language(settings)
    quoter = ExtractiveAnswerGenerator()
    if writer is None:
        knowledge = KnowledgeService(docs, Bm25Retriever(), quoter, clock)
    else:
        knowledge = KnowledgeService(
            docs,
            Bm25Retriever(),
            writer,
            clock,
            fallback=quoter,
            whole_base_max_chars=settings.whole_base_max_chars,
        )

    return Container(
        settings=settings,
        db=db,
        clock=clock,
        agent=AgentService(
            uow=db,
            businesses=businesses,
            contacts=contacts,
            conversations=conversations,
            booking=booking,
            knowledge=knowledge,
            interpreter=interpreter,
            messenger=messenger,
            clock=clock,
        ),
        booking=booking,
        business=BusinessService(db, businesses),
        inbox=InboxService(db, conversations, contacts, messenger),
        knowledge=knowledge,
        reminders=ReminderService(db, businesses, appointments, contacts, conversations, messenger, clock),
        dashboard=SqliteDashboardReadModel(db),
        contacts=contacts,
        background=BackgroundRunner(),
        auth=AuthService(
            db, SqliteUserRepository(db), SqliteSessionRepository(db), businesses, ScryptHasher(), clock
        ),
    )
