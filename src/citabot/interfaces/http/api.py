"""JSON API and WhatsApp webhook. Handlers stay thin: parse, call a use case, serialise."""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta
from functools import partial

from citabot.container import Container
from citabot.domain.errors import ValidationError
from citabot.domain.models import Appointment, AppointmentStatus, ConversationMode
from citabot.infrastructure.messaging.whatsapp_cloud import parse_webhook, signature_is_valid

from . import schemas as s
from .framework import HttpError, Request, Response, Router

logger = logging.getLogger(__name__)


def build_router(c: Container) -> Router:
    router = Router()

    def tenant(_request: Request) -> int:
        """Resolve the business a request acts on.

        Single-tenant MVP: always the default business. With authentication this
        reads the tenant from the session or token, and nothing else changes,
        because every use case already takes a business id.
        """
        return c.settings.default_business_id

    def appointment_json(business_id: int, appointment: Appointment) -> dict[str, object]:
        return s.appointment_out(
            appointment,
            c.contacts.get(appointment.contact_id),
            c.business.get_service(business_id, appointment.service_id),
        )

    # ------------------------------------------------------------ system

    @router.route("GET", "/api/health")
    def health(_request: Request) -> Response:
        return Response.json({"status": "ok", "messaging_provider": c.settings.messaging_provider})

    @router.route("GET", "/api/dashboard")
    def dashboard(request: Request) -> Response:
        business_id = tenant(request)
        now = c.clock.now()
        upcoming = [
            appointment_json(business_id, a)
            for a in c.booking.list_between(business_id, now, now + timedelta(days=30))
            if a.status is AppointmentStatus.CONFIRMED
        ][:6]
        return Response.json(
            {
                "business": s.business_out(c.business.get(business_id)),
                "metrics": c.dashboard.metrics(business_id, now),
                "upcoming": upcoming,
            }
        )

    @router.route("POST", "/api/demo/reset")
    def reset_demo(_request: Request) -> Response:
        c.reset_demo()
        return Response.json({"reset": True})

    # ------------------------------------------------------------ business & services

    @router.route("GET", "/api/business")
    def get_business(request: Request) -> Response:
        return Response.json(s.business_out(c.business.get(tenant(request))))

    @router.route("PUT", "/api/business")
    def update_business(request: Request) -> Response:
        body = request.json()
        business = c.business.update(
            tenant(request),
            name=s.text_field(body, "name"),
            welcome_message=s.text_field(body, "welcome_message"),
            slot_minutes=s.int_field(body, "slot_minutes"),
            opening_hours=s.parse_hours(body.get("opening_hours")),
        )
        return Response.json(s.business_out(business))

    @router.route("GET", "/api/services")
    def list_services(request: Request) -> Response:
        return Response.json([s.service_out(x) for x in c.business.list_services(tenant(request))])

    @router.route("POST", "/api/services")
    def add_service(request: Request) -> Response:
        body = request.json()
        service = c.business.add_service(
            tenant(request),
            s.text_field(body, "name"),
            s.int_field(body, "duration_minutes"),
            s.text_field(body, "price", required=False),
        )
        return Response.json(s.service_out(service), 201)

    @router.route("PUT", "/api/services/{service_id}")
    def update_service(request: Request) -> Response:
        body = request.json()
        service = c.business.update_service(
            tenant(request),
            request.params["service_id"],
            s.text_field(body, "name"),
            s.int_field(body, "duration_minutes"),
            s.text_field(body, "price", required=False),
        )
        return Response.json(s.service_out(service))

    @router.route("DELETE", "/api/services/{service_id}")
    def delete_service(request: Request) -> Response:
        c.business.remove_service(tenant(request), request.params["service_id"])
        return Response.json({"deleted": True})

    # ------------------------------------------------------------ inbox

    @router.route("GET", "/api/conversations")
    def list_conversations(request: Request) -> Response:
        return Response.json([s.summary_out(x) for x in c.inbox.list(tenant(request))])

    @router.route("GET", "/api/conversations/{conversation_id}")
    def get_conversation(request: Request) -> Response:
        thread = c.inbox.thread(tenant(request), request.params["conversation_id"])
        data = s.conversation_out(thread.conversation, thread.contact)
        data["messages"] = [s.message_out(m) for m in thread.messages]
        return Response.json(data)

    @router.route("PATCH", "/api/conversations/{conversation_id}")
    def update_conversation(request: Request) -> Response:
        body = request.json()
        mode = None
        if body.get("mode") is not None:
            try:
                mode = ConversationMode(body["mode"])
            except ValueError as exc:
                raise ValidationError("«mode» debe ser 'bot' o 'human'.") from exc
        business_id = tenant(request)
        conversation = c.inbox.update(
            business_id,
            request.params["conversation_id"],
            mode=mode,
            needs_attention=s.bool_field(body, "needs_attention"),
        )
        return Response.json(s.conversation_out(conversation, c.contacts.get(conversation.contact_id)))

    @router.route("POST", "/api/conversations/{conversation_id}/messages")
    def reply(request: Request) -> Response:
        message = c.inbox.reply_as_agent(
            tenant(request), request.params["conversation_id"], s.text_field(request.json(), "text")
        )
        return Response.json(s.message_out(message), 201)

    # ------------------------------------------------------------ appointments

    @router.route("GET", "/api/appointments")
    def list_appointments(request: Request) -> Response:
        business_id = tenant(request)
        start = s.parse_date(request.query.get("from"), "from")
        end = s.parse_date(request.query.get("to"), "to")
        if end < start or (end - start).days > 92:
            raise ValidationError("El rango de fechas debe ser de máximo 92 días.")
        appointments = c.booking.list_between(
            business_id,
            datetime.combine(start, datetime.min.time()),
            datetime.combine(end + timedelta(days=1), datetime.min.time()),
        )
        return Response.json([appointment_json(business_id, a) for a in appointments])

    @router.route("POST", "/api/appointments")
    def create_appointment(request: Request) -> Response:
        body = request.json()
        business_id = tenant(request)
        appointment = c.booking.book_from_dashboard(
            business_id,
            phone=s.text_field(body, "phone"),
            name=s.text_field(body, "name"),
            service_id=s.int_field(body, "service_id"),
            starts_at=s.parse_datetime(s.text_field(body, "starts_at"), "starts_at"),
        )
        return Response.json(appointment_json(business_id, appointment), 201)

    @router.route("PATCH", "/api/appointments/{appointment_id}")
    def update_appointment(request: Request) -> Response:
        try:
            status = AppointmentStatus(s.text_field(request.json(), "status"))
        except ValueError as exc:
            raise ValidationError("Estado de cita inválido.") from exc
        business_id = tenant(request)
        appointment = c.booking.set_status(business_id, request.params["appointment_id"], status)
        return Response.json(appointment_json(business_id, appointment))

    @router.route("GET", "/api/availability")
    def availability(request: Request) -> Response:
        business_id = tenant(request)
        service_id = request.query.get("service_id", "")
        if not service_id.isdigit():
            raise ValidationError("«service_id» es obligatorio.")
        day = s.parse_date(request.query.get("date"), "date")
        slots = c.booking.slots_for(
            c.business.get(business_id), c.business.get_service(business_id, int(service_id)), day
        )
        return Response.json({"date": day.isoformat(), "slots": [x.isoformat() for x in slots]})

    @router.route("POST", "/api/reminders/run")
    def run_reminders(request: Request) -> Response:
        return Response.json({"sent": c.reminders.send_due(tenant(request))})

    # ------------------------------------------------------------ knowledge

    @router.route("GET", "/api/knowledge")
    def list_docs(request: Request) -> Response:
        return Response.json([s.doc_out(d) for d in c.knowledge.list_docs(tenant(request))])

    @router.route("POST", "/api/knowledge")
    def add_doc(request: Request) -> Response:
        body = request.json()
        doc = c.knowledge.add_doc(tenant(request), s.text_field(body, "title"), s.text_field(body, "content"))
        return Response.json(s.doc_out(doc), 201)

    @router.route("DELETE", "/api/knowledge/{doc_id}")
    def delete_doc(request: Request) -> Response:
        c.knowledge.delete_doc(tenant(request), request.params["doc_id"])
        return Response.json({"deleted": True})

    @router.route("POST", "/api/knowledge/search")
    def search_docs(request: Request) -> Response:
        query = s.text_field(request.json(), "query")[:500]
        return Response.json([s.passage_out(p) for p in c.knowledge.search(tenant(request), query)])

    # ------------------------------------------------------------ channels

    @router.route("POST", "/api/simulator/messages")
    def simulate_inbound(request: Request) -> Response:
        """Local stand-in for the WhatsApp webhook: same use case, friendlier payload."""
        body = request.json()
        result = c.agent.handle_inbound(
            tenant(request),
            phone=s.text_field(body, "phone"),
            text=s.text_field(body, "text"),
            profile_name=s.text_field(body, "name", required=False) or None,
        )
        return Response.json(
            {
                "conversation_id": result.conversation_id,
                "replies": [s.message_out(m) for m in result.replies],
            }
        )

    @router.route("GET", "/webhooks/whatsapp")
    def verify_webhook(request: Request) -> Response:
        """Meta's subscription handshake: echo hub.challenge when the token matches."""
        expected = c.settings.whatsapp_verify_token
        token = request.query.get("hub.verify_token", "")
        if (
            expected
            and request.query.get("hub.mode") == "subscribe"
            and hmac.compare_digest(token.encode(), expected.encode())
        ):
            return Response.text(request.query.get("hub.challenge", ""))
        raise HttpError(403, "forbidden", "Token de verificación inválido.")

    @router.route("POST", "/webhooks/whatsapp")
    def receive_webhook(request: Request) -> Response:
        secret = c.settings.whatsapp_app_secret
        if secret:
            if not signature_is_valid(secret, request.body, request.headers.get("x-hub-signature-256")):
                raise HttpError(401, "invalid_signature", "Firma inválida.")
        elif c.settings.messaging_provider == "whatsapp_cloud":
            # Never accept unsigned webhooks once real messages are flowing.
            raise HttpError(503, "not_configured", "Falta WHATSAPP_APP_SECRET.")
        # Store each message now and answer it in the background: Meta redelivers
        # a webhook that is not acknowledged within a few seconds, and a reply
        # that waits for a language model can take longer than that.
        accepted = 0
        for inbound in parse_webhook(request.json()):
            try:
                received = c.agent.receive(
                    c.settings.default_business_id,
                    inbound.phone,
                    inbound.text,
                    inbound.profile_name,
                    inbound.message_id,
                )
            except Exception:  # always acknowledge, or Meta retries the batch
                logger.exception("No se pudo guardar un mensaje entrante")
                continue
            if received.duplicate:
                continue
            accepted += 1
            # Keyed by conversation, so one customer's messages are answered in order.
            c.background.submit(partial(c.agent.respond, received), key=received.conversation_id)
        return Response.json({"received": accepted})

    return router
