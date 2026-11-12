"""End-to-end tests: a real HTTP server on a free port, exercised with urllib."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import unittest
import urllib.error
import urllib.request
from typing import Any, ClassVar

from citabot.interfaces.http.api import build_router
from citabot.interfaces.http.server import create_server
from tests import support


class ApiTestCase(unittest.TestCase):
    settings_overrides: ClassVar[dict[str, object]] = {}

    def setUp(self) -> None:
        self.c = support.make_container(**self.settings_overrides)
        self.server = create_server("127.0.0.1", 0, build_router(self.c), self.c.settings.web_dir)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self.c.close)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.cookie: str | None = None
        if self.signed_in:
            self.call("POST", "/api/auth/demo")

    # Most tests exercise the panel, so they start signed in to the demo business.
    signed_in: ClassVar[bool] = True

    def call(
        self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None
    ) -> tuple[int, Any]:
        """Send a request, keeping the session cookie between calls like a browser."""
        data = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
        headers = dict(headers or {})
        if self.cookie:
            headers["Cookie"] = self.cookie
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                raw, status, sent = response.read(), response.status, response.headers
        except urllib.error.HTTPError as error:
            raw, status, sent = error.read(), error.code, error.headers
        if sent.get("Set-Cookie"):
            pair = sent["Set-Cookie"].split(";", 1)[0]
            self.cookie = None if pair.endswith("=") else pair
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, raw.decode()


class ApiTest(ApiTestCase):
    def test_health_and_dashboard(self) -> None:
        self.assertEqual(self.call("GET", "/api/health")[1]["status"], "ok")
        status, data = self.call("GET", "/api/dashboard")
        self.assertEqual(status, 200)
        self.assertEqual(data["business"]["name"], "Clínica Dental Sonrisa")
        self.assertEqual(data["metrics"]["conversations"], 3)
        self.assertEqual(len(data["metrics"]["appointments_by_day"]), 7)

    def test_simulator_conversation_shows_up_in_the_inbox(self) -> None:
        status, data = self.call(
            "POST", "/api/simulator/messages", {"phone": "+57 1", "name": "Ana", "text": "Hola"}
        )
        self.assertEqual(status, 200)
        self.assertIn("Agendar cita", data["replies"][0]["options"])
        _, inbox = self.call("GET", "/api/conversations")
        self.assertEqual(inbox[0]["contact"]["name"], "Ana")
        _, thread = self.call("GET", f"/api/conversations/{data['conversation_id']}")
        self.assertEqual([m["sender"] for m in thread["messages"]], ["customer", "bot"])

    def test_agent_reply_takes_over_the_conversation(self) -> None:
        _, sim = self.call("POST", "/api/simulator/messages", {"phone": "+57 1", "text": "Hola"})
        path = f"/api/conversations/{sim['conversation_id']}"
        status, message = self.call("POST", path + "/messages", {"text": "Hola, soy Marta"})
        self.assertEqual((status, message["sender"]), (201, "agent"))
        self.assertEqual(self.call("GET", path)[1]["mode"], "human")
        status, data = self.call("PATCH", path, {"mode": "bot"})
        self.assertEqual((status, data["mode"]), (200, "bot"))

    def test_booking_from_the_dashboard_and_double_booking(self) -> None:
        _, availability = self.call("GET", "/api/availability?service_id=2&date=2026-11-13")
        self.assertIn("2026-11-13T09:00:00", availability["slots"])
        self.assertNotIn("2026-11-13T10:00:00", availability["slots"])  # taken in the demo data

        body = {"phone": "+57 2", "name": "Luis", "service_id": 2, "starts_at": "2026-11-13T09:00"}
        status, created = self.call("POST", "/api/appointments", body)
        self.assertEqual((status, created["source"]), (201, "dashboard"))
        status, error = self.call("POST", "/api/appointments", body)
        self.assertEqual((status, error["error"]["code"]), (409, "slot_unavailable"))

        status, cancelled = self.call("PATCH", f"/api/appointments/{created['id']}", {"status": "cancelled"})
        self.assertEqual((status, cancelled["status"]), (200, "cancelled"))
        _, listed = self.call("GET", "/api/appointments?from=2026-11-13&to=2026-11-13")
        self.assertEqual({a["status"] for a in listed}, {"confirmed", "cancelled"})

    def test_knowledge_crud_and_search(self) -> None:
        status, doc = self.call(
            "POST", "/api/knowledge", {"title": "Wifi", "content": "La clave del wifi es sonrisa2026."}
        )
        self.assertEqual(status, 201)
        _, hits = self.call("POST", "/api/knowledge/search", {"query": "¿cuál es la clave del wifi?"})
        self.assertEqual(hits[0]["doc_id"], doc["id"])
        self.assertEqual(self.call("DELETE", f"/api/knowledge/{doc['id']}")[0], 200)
        self.assertEqual(self.call("DELETE", f"/api/knowledge/{doc['id']}")[0], 404)

    def test_business_settings_and_services(self) -> None:
        _, business = self.call("GET", "/api/business")
        business["name"] = "Sonrisa Norte"
        business["opening_hours"]["6"] = [["10:00", "12:00"]]
        status, updated = self.call("PUT", "/api/business", business)
        self.assertEqual((status, updated["name"]), (200, "Sonrisa Norte"))
        self.assertEqual(updated["opening_hours"]["6"], [["10:00", "12:00"]])

        status, service = self.call(
            "POST", "/api/services", {"name": "Resina", "duration_minutes": 45, "price": "$150.000"}
        )
        self.assertEqual(status, 201)
        self.assertEqual(self.call("DELETE", f"/api/services/{service['id']}")[0], 200)
        names = [x["name"] for x in self.call("GET", "/api/services")[1]]
        self.assertNotIn("Resina", names)

    def test_validation_and_error_shapes(self) -> None:
        cases = [
            ("POST", "/api/simulator/messages", {"phone": "+57 1"}, 400),
            ("POST", "/api/simulator/messages", b"{not json", 400),
            ("POST", "/api/services", {"name": "x" * 40, "duration_minutes": 30}, 400),
            ("PUT", "/api/business", {"name": "A", "welcome_message": "B", "slot_minutes": 7,
                                      "opening_hours": {}}, 400),
            ("GET", "/api/appointments?from=ayer&to=hoy", None, 400),
            ("GET", "/api/conversations/999", None, 404),
            ("GET", "/api/nope", None, 404),
            ("DELETE", "/api/health", None, 405),
        ]  # fmt: skip
        for method, path, body, expected in cases:
            with self.subTest(path=path):
                status, data = self.call(method, path, body)
                self.assertEqual(status, expected)
                self.assertIn("message", data["error"])

    def test_static_files_and_path_traversal(self) -> None:
        status, html = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("<title>", html)
        self.assertEqual(self.call("GET", "/../run.py")[0], 404)
        self.assertEqual(self.call("GET", "/%2e%2e/pyproject.toml")[0], 404)

    def test_public_pages_have_clean_urls(self) -> None:
        pages = {
            "/": "WhatsApp",
            "/precios": "Precios",
            "/login": "Iniciar sesión",
            "/registro": "Crear cuenta",
            "/app": "Panel",
            "/precios/": "Precios",
        }
        for path, title in pages.items():
            with self.subTest(path=path):
                status, html = self.call("GET", path)
                self.assertEqual(status, 200)
                self.assertIn(title, html.split("<title>", 1)[1].split("</title>", 1)[0])

    def test_unknown_pages_get_the_404_page(self) -> None:
        status, html = self.call("GET", "/no-existe")
        self.assertEqual(status, 404)
        self.assertIn("Esta página no existe", html)
        self.assertEqual(self.call("GET", "/js/no-existe.js")[1]["error"]["code"], "not_found")

    def test_demo_reset(self) -> None:
        self.call("POST", "/api/simulator/messages", {"phone": "+57 1", "text": "Hola"})
        self.assertEqual(self.call("POST", "/api/demo/reset")[0], 200)
        self.assertEqual(len(self.call("GET", "/api/conversations")[1]), 3)


class WebhookTest(ApiTestCase):
    settings_overrides: ClassVar[dict[str, object]] = {
        "whatsapp_verify_token": "s3cret-token",
        "whatsapp_app_secret": "app-secret",
    }

    PAYLOAD: ClassVar[dict[str, Any]] = {
        "entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": "573001112233", "profile": {"name": "Sofía"}}],
            "messages": [
                {"from": "573001112233", "id": "wamid.A", "type": "text", "text": {"body": "Hola"}},
                {"from": "573001112233", "id": "wamid.B", "type": "interactive", "interactive": {
                    "type": "button_reply", "button_reply": {"id": "opt_1", "title": "Agendar cita"}}},
                {"from": "573001112233", "type": "audio", "audio": {"id": "x"}},
            ],
        }}]}]
    }  # fmt: skip

    def test_verification_handshake(self) -> None:
        ok = "/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=s3cret-token&hub.challenge=12345"
        self.assertEqual(self.call("GET", ok), (200, 12345))
        bad = ok.replace("s3cret-token", "wrong")
        self.assertEqual(self.call("GET", bad)[0], 403)

    def post_signed(self) -> tuple[int, Any]:
        body = json.dumps(self.PAYLOAD).encode()
        signature = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()
        result = self.call("POST", "/webhooks/whatsapp", body, {"X-Hub-Signature-256": signature})
        self.assertTrue(self.c.background.wait_idle(timeout=5))  # replies are sent after the 200
        return result

    def test_signed_webhook_feeds_the_agent(self) -> None:
        self.assertEqual(self.post_signed(), (200, {"received": 2}))
        _, inbox = self.call("GET", "/api/conversations")
        self.assertEqual(
            inbox[0]["contact"], {"id": inbox[0]["contact"]["id"], "phone": "+573001112233", "name": "Sofía"}
        )
        # Both messages came in one notification and were answered in order.
        self.assertEqual(inbox[0]["last_message"]["text"], "¿Qué servicio necesitas?")

    def test_redelivered_webhook_is_answered_once(self) -> None:
        self.assertEqual(self.post_signed(), (200, {"received": 2}))
        self.assertEqual(self.post_signed(), (200, {"received": 0}))
        _, inbox = self.call("GET", "/api/conversations")
        _, thread = self.call("GET", f"/api/conversations/{inbox[0]['id']}")
        self.assertEqual(
            [m["text"] for m in thread["messages"] if m["sender"] == "customer"], ["Hola", "Agendar cita"]
        )
        self.assertEqual(len([m for m in thread["messages"] if m["sender"] == "bot"]), 2)

    def test_unsigned_webhook_is_rejected(self) -> None:
        status, _ = self.call(
            "POST", "/webhooks/whatsapp", self.PAYLOAD, {"X-Hub-Signature-256": "sha256=00"}
        )
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
