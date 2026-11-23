"""JSON API and WhatsApp webhook. Handlers stay thin: parse, call a use case, serialise.

Handlers are plain `def`: FastAPI runs them in a thread pool, which suits the
synchronous services and the SQLite unit of work underneath.

No `from __future__ import annotations` here: FastAPI reads the parameter
annotations at runtime, and the dependency aliases are local to build_api.
"""

import hmac
import json
import logging
from datetime import datetime, timedelta
from functools import partial
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from citabot.application.auth import Session
from citabot.container import Container
from citabot.domain.errors import AuthenticationError, ValidationError
from citabot.domain.models import Appointment, AppointmentStatus, ConversationMode, User
from citabot.infrastructure.messaging.whatsapp_cloud import parse_webhook, signature_is_valid

from . import schemas as s
from .errors import HttpError

logger = logging.getLogger(__name__)

SESSION_COOKIE = "citabot_session"
# Ids are positive and fit SQLite's integer; anything else is simply not found.
Id = Annotated[int, Path(ge=1, le=10**12)]


def build_api(c: Container) -> APIRouter:
    router = APIRouter()

    # ------------------------------------------------------------ dependencies

    def client_address(request: Request) -> str:
        """The caller's IP, for rate limiting. Behind a reverse proxy the socket only
        shows the proxy, so with CITABOT_TRUST_PROXY the last X-Forwarded-For entry
        (the one our proxy appended) is used. Never trust that header without a
        proxy: any client can send it."""
        forwarded = request.headers.get("x-forwarded-for") if c.settings.trust_proxy else None
        if forwarded:
            return forwarded.rsplit(",", 1)[-1].strip()
        return request.client.host if request.client else ""

    def current_user(request: Request) -> User:
        token = request.cookies.get(SESSION_COOKIE)
        user = c.auth.authenticate(token) if token else None
        if user is None:
            raise AuthenticationError("Inicia sesión para continuar.")
        return user

    def tenant(user: Annotated[User, Depends(current_user)]) -> int:
        """The business a request acts on: the one the signed-in user belongs to.

        Every panel route depends on this, so none of them answers without a
        session and none can reach another business's data.
        """
        return user.business_id

    async def raw_body(request: Request) -> bytes:
        return await request.body()

    Client = Annotated[str, Depends(client_address)]  # noqa: N806 (type aliases)
    CurrentUser = Annotated[User, Depends(current_user)]  # noqa: N806
    Tenant = Annotated[int, Depends(tenant)]  # noqa: N806

    # ------------------------------------------------------------ helpers

    def session_cookie(response: JSONResponse, value: str, max_age: int) -> JSONResponse:
        """Unreadable by scripts and not sent on cross-site requests."""
        attributes = [f"{SESSION_COOKIE}={value}", "Path=/", f"Max-Age={max_age}", "HttpOnly", "SameSite=Lax"]
        if c.settings.cookie_secure:
            attributes.append("Secure")
        response.headers.append("set-cookie", "; ".join(attributes))
        return response

    def signed_in(session: Session, status: int = 200) -> JSONResponse:
        max_age = int((session.expires_at - c.clock.now()).total_seconds())
        return session_cookie(JSONResponse(account_json(session.user), status), session.token, max_age)

    def account_json(user: User) -> dict[str, Any]:
        business = c.business.get(user.business_id)
        return {
            "user": {"name": user.name, "email": user.email},
            "business": {"id": business.id, "name": business.name},
            "is_demo": business.is_demo,
        }

    def appointment_json(business_id: int, appointment: Appointment) -> dict[str, Any]:
        return s.appointment_out(
            appointment,
            c.contacts.get(appointment.contact_id),
            c.business.get_service(business_id, appointment.service_id),
        )

    # ------------------------------------------------------------ system

    @router.get("/api/health", tags=["sistema"])
    def health() -> dict[str, Any]:
        # Public: only what the login page needs. Configuration stays private.
        return {"status": "ok", "demo_login": c.settings.demo_login}

    # ------------------------------------------------------------ accounts

    @router.post("/api/auth/signup", status_code=201, tags=["cuentas"])
    def signup(body: s.SignupIn, client: Client) -> JSONResponse:
        session = c.auth.register(body.business_name, body.name, body.email, body.password, client=client)
        return signed_in(session, 201)

    @router.post("/api/auth/login", tags=["cuentas"])
    def login(body: s.LoginIn, client: Client) -> JSONResponse:
        return signed_in(c.auth.login(body.email, body.password, client=client))

    @router.post("/api/auth/demo", tags=["cuentas"])
    def login_demo(client: Client) -> JSONResponse:
        if not c.settings.demo_login:
            raise HttpError(403, "demo_disabled", "La demostración no está disponible.")
        return signed_in(c.demo.start(client=client))

    @router.post("/api/auth/logout", tags=["cuentas"])
    def logout(request: Request) -> JSONResponse:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            c.auth.logout(token)
        return session_cookie(JSONResponse({"signed_out": True}), "", 0)

    @router.get("/api/auth/me", tags=["cuentas"])
    def me(user: CurrentUser) -> dict[str, Any]:
        return account_json(user)

    @router.get("/api/dashboard", tags=["panel"])
    def dashboard(business_id: Tenant) -> dict[str, Any]:
        now = c.clock.now()
        upcoming = [
            appointment_json(business_id, a)
            for a in c.booking.list_between(business_id, now, now + timedelta(days=30))
            if a.status is AppointmentStatus.CONFIRMED
        ][:6]
        return {
            "business": s.business_out(c.business.get(business_id)),
            "metrics": c.dashboard.metrics(business_id, now),
            "upcoming": upcoming,
        }

    @router.post("/api/demo/reset", tags=["panel"])
    def reset_demo(business_id: Tenant) -> dict[str, Any]:
        if not c.business.get(business_id).is_demo:
            raise HttpError(403, "not_demo", "Solo un negocio de demostración se puede reiniciar.")
        c.demo.reset(business_id)
        return {"reset": True}

    # ------------------------------------------------------------ business & services

    @router.get("/api/business", tags=["negocio"])
    def get_business(business_id: Tenant) -> dict[str, Any]:
        return s.business_out(c.business.get(business_id))

    @router.put("/api/business", tags=["negocio"])
    def update_business(body: s.BusinessIn, business_id: Tenant) -> dict[str, Any]:
        business = c.business.update(
            business_id,
            name=body.name,
            welcome_message=body.welcome_message,
            slot_minutes=body.slot_minutes,
            opening_hours=s.parse_hours(body.opening_hours),
        )
        return s.business_out(business)

    @router.get("/api/services", tags=["negocio"])
    def list_services(business_id: Tenant) -> list[dict[str, Any]]:
        return [s.service_out(x) for x in c.business.list_services(business_id)]

    @router.post("/api/services", status_code=201, tags=["negocio"])
    def add_service(body: s.ServiceIn, business_id: Tenant) -> dict[str, Any]:
        service = c.business.add_service(business_id, body.name, body.duration_minutes, body.price or "")
        return s.service_out(service)

    @router.put("/api/services/{service_id}", tags=["negocio"])
    def update_service(service_id: Id, body: s.ServiceIn, business_id: Tenant) -> dict[str, Any]:
        service = c.business.update_service(
            business_id, service_id, body.name, body.duration_minutes, body.price or ""
        )
        return s.service_out(service)

    @router.delete("/api/services/{service_id}", tags=["negocio"])
    def delete_service(service_id: Id, business_id: Tenant) -> dict[str, Any]:
        c.business.remove_service(business_id, service_id)
        return {"deleted": True}

    # ------------------------------------------------------------ inbox

    @router.get("/api/conversations", tags=["conversaciones"])
    def list_conversations(business_id: Tenant) -> list[dict[str, Any]]:
        return [s.summary_out(x) for x in c.inbox.list(business_id)]

    @router.get("/api/conversations/{conversation_id}", tags=["conversaciones"])
    def get_conversation(conversation_id: Id, business_id: Tenant) -> dict[str, Any]:
        thread = c.inbox.thread(business_id, conversation_id)
        data = s.conversation_out(thread.conversation, thread.contact)
        data["messages"] = [s.message_out(m) for m in thread.messages]
        return data

    @router.patch("/api/conversations/{conversation_id}", tags=["conversaciones"])
    def update_conversation(
        conversation_id: Id, body: s.ConversationPatch, business_id: Tenant
    ) -> dict[str, Any]:
        mode = None
        if body.mode is not None:
            try:
                mode = ConversationMode(body.mode)
            except ValueError as exc:
                raise ValidationError("«mode» debe ser 'bot' o 'human'.") from exc
        conversation = c.inbox.update(
            business_id, conversation_id, mode=mode, needs_attention=body.needs_attention
        )
        return s.conversation_out(conversation, c.contacts.get(conversation.contact_id))

    @router.post("/api/conversations/{conversation_id}/messages", status_code=201, tags=["conversaciones"])
    def reply(conversation_id: Id, body: s.ReplyIn, business_id: Tenant) -> dict[str, Any]:
        return s.message_out(c.inbox.reply_as_agent(business_id, conversation_id, body.text))

    # ------------------------------------------------------------ appointments

    @router.get("/api/appointments", tags=["agenda"])
    def list_appointments(
        business_id: Tenant,
        start: Annotated[str | None, Query(alias="from")] = None,
        end: Annotated[str | None, Query(alias="to")] = None,
    ) -> list[dict[str, Any]]:
        first = s.parse_date(start, "from")
        last = s.parse_date(end, "to")
        if last < first or (last - first).days > 92:
            raise ValidationError("El rango de fechas debe ser de máximo 92 días.")
        appointments = c.booking.list_between(
            business_id,
            datetime.combine(first, datetime.min.time()),
            datetime.combine(last + timedelta(days=1), datetime.min.time()),
        )
        return [appointment_json(business_id, a) for a in appointments]

    @router.post("/api/appointments", status_code=201, tags=["agenda"])
    def create_appointment(body: s.AppointmentIn, business_id: Tenant) -> dict[str, Any]:
        appointment = c.booking.book_from_dashboard(
            business_id,
            phone=body.phone,
            name=body.name,
            service_id=body.service_id,
            starts_at=s.parse_datetime(body.starts_at, "starts_at"),
        )
        return appointment_json(business_id, appointment)

    @router.patch("/api/appointments/{appointment_id}", tags=["agenda"])
    def update_appointment(
        appointment_id: Id, body: s.AppointmentPatch, business_id: Tenant
    ) -> dict[str, Any]:
        try:
            status = AppointmentStatus(body.status)
        except ValueError as exc:
            raise ValidationError("Estado de cita inválido.") from exc
        return appointment_json(business_id, c.booking.set_status(business_id, appointment_id, status))

    @router.get("/api/availability", tags=["agenda"])
    def availability(business_id: Tenant, service_id: str = "", date: str | None = None) -> dict[str, Any]:
        if not service_id.isdigit():
            raise ValidationError("«service_id» es obligatorio.")
        day = s.parse_date(date, "date")
        slots = c.booking.slots_for(
            c.business.get(business_id), c.business.get_service(business_id, int(service_id)), day
        )
        return {"date": day.isoformat(), "slots": [x.isoformat() for x in slots]}

    @router.post("/api/reminders/run", tags=["agenda"])
    def run_reminders(business_id: Tenant) -> dict[str, Any]:
        return {"sent": c.reminders.send_due(business_id)}

    # ------------------------------------------------------------ knowledge

    @router.get("/api/knowledge", tags=["conocimiento"])
    def list_docs(business_id: Tenant) -> list[dict[str, Any]]:
        return [s.doc_out(d) for d in c.knowledge.list_docs(business_id)]

    @router.post("/api/knowledge", status_code=201, tags=["conocimiento"])
    def add_doc(body: s.DocIn, business_id: Tenant) -> dict[str, Any]:
        return s.doc_out(c.knowledge.add_doc(business_id, body.title, body.content))

    @router.delete("/api/knowledge/{doc_id}", tags=["conocimiento"])
    def delete_doc(doc_id: Id, business_id: Tenant) -> dict[str, Any]:
        c.knowledge.delete_doc(business_id, doc_id)
        return {"deleted": True}

    @router.post("/api/knowledge/search", tags=["conocimiento"])
    def search_docs(body: s.SearchIn, business_id: Tenant) -> list[dict[str, Any]]:
        return [s.passage_out(p) for p in c.knowledge.search(business_id, body.query[:500])]

    # ------------------------------------------------------------ channels

    @router.post("/api/simulator/messages", tags=["canales"])
    def simulate_inbound(body: s.SimulatorIn, business_id: Tenant) -> dict[str, Any]:
        """Local stand-in for the WhatsApp webhook: same use case, friendlier payload."""
        result = c.agent.handle_inbound(
            business_id, phone=body.phone, text=body.text, profile_name=body.name or None
        )
        return {
            "conversation_id": result.conversation_id,
            "replies": [s.message_out(m) for m in result.replies],
        }

    @router.get("/webhooks/whatsapp", tags=["canales"])
    def verify_webhook(request: Request) -> PlainTextResponse:
        """Meta's subscription handshake: echo hub.challenge when the token matches."""
        expected = c.settings.whatsapp_verify_token
        query = request.query_params
        token = query.get("hub.verify_token", "")
        if (
            expected
            and query.get("hub.mode") == "subscribe"
            and hmac.compare_digest(token.encode(), expected.encode())
        ):
            return PlainTextResponse(query.get("hub.challenge", ""))
        raise HttpError(403, "forbidden", "Token de verificación inválido.")

    @router.post("/webhooks/whatsapp", tags=["canales"])
    def receive_webhook(request: Request, body: Annotated[bytes, Depends(raw_body)]) -> dict[str, Any]:
        # Only Meta may post here. Without the app secret there is no way to tell
        # Meta from anyone else, so the endpoint stays closed (the simulator does
        # not need it: it has its own route behind the session).
        secret = c.settings.whatsapp_app_secret
        if not secret:
            raise HttpError(503, "not_configured", "Falta WHATSAPP_APP_SECRET.")
        if not signature_is_valid(secret, body, request.headers.get("x-hub-signature-256")):
            raise HttpError(401, "invalid_signature", "Firma inválida.")
        try:
            payload = json.loads(body or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HttpError(400, "invalid_json", "El cuerpo debe ser JSON válido.") from exc
        if not isinstance(payload, dict):
            raise HttpError(400, "invalid_json", "El cuerpo debe ser un objeto JSON.")
        # Store each message now and answer it in the background: Meta redelivers
        # a webhook that is not acknowledged within a few seconds, and a reply
        # that waits for a language model can take longer than that.
        accepted = 0
        for inbound in parse_webhook(payload):
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
        return {"received": accepted}

    return router
