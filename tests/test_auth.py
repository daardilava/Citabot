"""Accounts, sessions and the isolation between businesses."""

from __future__ import annotations

import unittest
from datetime import timedelta
from typing import ClassVar

from citabot.application.auth import (
    MAX_FAILED_LOGINS,
    MAX_FAILED_LOGINS_PER_CLIENT,
    MAX_SIGNUPS_PER_CLIENT,
    SESSION_TTL,
)
from citabot.domain.errors import AuthenticationError, RateLimitedError, ValidationError
from citabot.infrastructure.clock import FixedClock
from citabot.infrastructure.security import UNUSABLE_PASSWORD, ScryptHasher
from citabot.infrastructure.seed import DEMO_EMAIL

from . import support
from .test_api import ApiTestCase

SIGNUP = {
    "business_name": "Barbería Central",
    "name": "Marta Ríos",
    "email": "Marta@Example.com",
    "password": "una-clave-larga",
}


class HasherTest(unittest.TestCase):
    def test_round_trip(self) -> None:
        hasher = ScryptHasher()
        stored = hasher.hash("correcta")
        self.assertTrue(hasher.verify("correcta", stored))
        self.assertFalse(hasher.verify("incorrecta", stored))
        self.assertNotEqual(stored, hasher.hash("correcta"))  # a fresh salt every time
        self.assertNotIn("correcta", stored)

    def test_malformed_hashes_never_verify(self) -> None:
        hasher = ScryptHasher()
        for stored in (UNUSABLE_PASSWORD, "", "scrypt$1$2", "md5$a$b$c$d$e", "scrypt$x$8$1$AA==$AA=="):
            with self.subTest(stored=stored):
                self.assertFalse(hasher.verify("", stored))
                self.assertFalse(hasher.verify(UNUSABLE_PASSWORD, stored))


class AuthServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FixedClock(support.NOW)
        self.c = support.make_container()
        self.c.auth._clock = self.clock
        self.addCleanup(self.c.close)

    def register(self) -> None:
        self.c.auth.register(**SIGNUP)

    def test_register_creates_a_separate_business(self) -> None:
        session = self.c.auth.register(**SIGNUP)
        self.assertEqual(session.user.email, "marta@example.com")  # normalised
        self.assertNotEqual(session.user.business_id, support.BUSINESS_ID)
        self.assertEqual(self.c.business.get(session.user.business_id).name, "Barbería Central")
        self.assertEqual(self.c.inbox.list(session.user.business_id), [])
        self.assertNotIn("una-clave-larga", session.user.password_hash)

    def test_register_validates_its_input(self) -> None:
        bad = [
            {"email": "sin-arroba"},
            {"password": "corta"},
            {"business_name": "  "},
            {"name": ""},
        ]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.c.auth.register(**(SIGNUP | change))
        self.register()
        with self.assertRaises(ValidationError):
            self.c.auth.register(**(SIGNUP | {"email": " MARTA@example.com "}))  # already taken

    def test_login_and_session_lifecycle(self) -> None:
        self.register()
        session = self.c.auth.login("marta@example.com", "una-clave-larga")
        user = self.c.auth.authenticate(session.token)
        assert user is not None
        self.assertEqual(user.name, "Marta Ríos")
        self.assertIsNone(self.c.auth.authenticate("not-a-token"))

        self.c.auth.logout(session.token)
        self.assertIsNone(self.c.auth.authenticate(session.token))

    def test_sessions_expire(self) -> None:
        session = self.c.auth.register(**SIGNUP)
        self.clock.moment = support.NOW + SESSION_TTL + timedelta(seconds=1)
        self.assertIsNone(self.c.auth.authenticate(session.token))

    def test_wrong_password_and_unknown_email_look_the_same(self) -> None:
        self.register()
        messages = set()
        for email, password in (("marta@example.com", "otra-clave"), ("nadie@example.com", "x")):
            with self.assertRaises(AuthenticationError) as caught:
                self.c.auth.login(email, password)
            messages.add(str(caught.exception))
        self.assertEqual(len(messages), 1)

    def fail(self, email: str, client: str, times: int) -> None:
        for _ in range(times):
            with self.assertRaises(AuthenticationError):
                self.c.auth.login(email, "otra-clave", client=client)

    def test_repeated_failures_lock_the_email_for_that_client_for_a_while(self) -> None:
        self.register()
        self.fail("marta@example.com", "10.0.0.9", MAX_FAILED_LOGINS)
        with self.assertRaises(RateLimitedError):
            self.c.auth.login("marta@example.com", "una-clave-larga", client="10.0.0.9")  # even the right one

        self.clock.moment = support.NOW + timedelta(minutes=16)
        self.assertTrue(self.c.auth.login("marta@example.com", "una-clave-larga", client="10.0.0.9").token)

    def test_a_stranger_cannot_lock_the_owner_out(self) -> None:
        self.register()
        self.fail("marta@example.com", "10.0.0.9", MAX_FAILED_LOGINS)
        session = self.c.auth.login("marta@example.com", "una-clave-larga", client="192.168.1.20")
        self.assertTrue(session.token)

    def test_a_client_spraying_many_emails_is_stopped(self) -> None:
        self.register()
        for i in range(MAX_FAILED_LOGINS_PER_CLIENT):
            self.fail(f"persona{i}@example.com", "10.0.0.9", 1)
        with self.assertRaises(RateLimitedError):
            self.c.auth.login("marta@example.com", "una-clave-larga", client="10.0.0.9")
        self.assertTrue(self.c.auth.login("marta@example.com", "una-clave-larga", client="10.0.0.1").token)

    def test_signups_per_client_are_limited(self) -> None:
        for i in range(MAX_SIGNUPS_PER_CLIENT):
            self.c.auth.register(**(SIGNUP | {"email": f"dueno{i}@example.com"}), client="10.0.0.9")
        with self.assertRaises(RateLimitedError):
            self.c.auth.register(**(SIGNUP | {"email": "otro@example.com"}), client="10.0.0.9")
        self.c.auth.register(**(SIGNUP | {"email": "otro@example.com"}), client="10.0.0.1")

    def test_the_demo_account_has_no_password(self) -> None:
        for password in ("", UNUSABLE_PASSWORD, "demo"):
            with self.subTest(password=password), self.assertRaises(AuthenticationError):
                self.c.auth.login(DEMO_EMAIL, password)


class AuthApiTest(ApiTestCase):
    signed_in: ClassVar[bool] = False

    def test_the_panel_api_requires_a_session(self) -> None:
        for method, path in (
            ("GET", "/api/dashboard"),
            ("GET", "/api/conversations"),
            ("GET", "/api/auth/me"),
            ("POST", "/api/simulator/messages"),
            ("POST", "/api/demo/reset"),
            ("POST", "/api/reminders/run"),
        ):
            with self.subTest(path=path):
                status, data = self.call(method, path, {} if method == "POST" else None)
                self.assertEqual((status, data["error"]["code"]), (401, "unauthorized"))
        self.assertEqual(self.call("GET", "/api/health")[0], 200)  # public

    def test_signup_login_and_logout(self) -> None:
        status, account = self.call("POST", "/api/auth/signup", SIGNUP)
        self.assertEqual(status, 201)
        self.assertEqual(account["business"]["name"], "Barbería Central")
        self.assertFalse(account["is_demo"])
        self.assertNotIn("password", str(account))
        self.assertEqual(self.call("GET", "/api/auth/me")[1], account)

        self.assertEqual(self.call("POST", "/api/auth/logout")[0], 200)
        self.assertEqual(self.call("GET", "/api/auth/me")[0], 401)

        bad = {"email": "marta@example.com", "password": "otra-clave"}
        self.assertEqual(self.call("POST", "/api/auth/login", bad)[0], 401)
        good = {"email": "marta@example.com", "password": "una-clave-larga"}
        self.assertEqual(self.call("POST", "/api/auth/login", good)[0], 200)
        self.assertEqual(self.call("GET", "/api/dashboard")[1]["business"]["name"], "Barbería Central")

    def test_the_session_cookie_is_http_only(self) -> None:
        import urllib.request

        request = urllib.request.Request(self.base + "/api/auth/demo", data=b"{}", method="POST")
        with urllib.request.urlopen(request, timeout=5) as response:
            cookie = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)
        self.assertNotIn("Secure", cookie)  # plain http on localhost; CITABOT_COOKIE_SECURE=1 adds it

    def test_a_business_cannot_see_or_touch_another(self) -> None:
        self.call("POST", "/api/auth/demo")
        _, demo_inbox = self.call("GET", "/api/conversations")
        _, demo_docs = self.call("GET", "/api/knowledge")
        demo_chat, demo_doc = demo_inbox[0]["id"], demo_docs[0]["id"]
        self.call("POST", "/api/auth/logout")

        self.call("POST", "/api/auth/signup", SIGNUP)
        self.assertEqual(self.call("GET", "/api/conversations")[1], [])
        self.assertEqual(self.call("GET", "/api/knowledge")[1], [])
        self.assertEqual(self.call("GET", "/api/services")[1], [])
        self.assertEqual(self.call("GET", f"/api/conversations/{demo_chat}")[0], 404)
        self.assertEqual(self.call("DELETE", f"/api/knowledge/{demo_doc}")[0], 404)
        self.assertEqual(self.call("POST", "/api/demo/reset")[0], 403)

    def test_demo_reset_keeps_other_accounts(self) -> None:
        self.call("POST", "/api/auth/signup", SIGNUP)
        self.call("POST", "/api/knowledge", {"title": "Wifi", "content": "La clave es barba2026."})
        self.call("POST", "/api/auth/logout")

        self.call("POST", "/api/auth/demo")
        self.assertTrue(self.call("GET", "/api/auth/me")[1]["is_demo"])
        self.assertEqual(self.call("POST", "/api/demo/reset")[0], 200)
        self.assertEqual(self.call("GET", "/api/auth/me")[0], 200)  # still signed in
        self.call("POST", "/api/auth/logout")

        good = {"email": "marta@example.com", "password": "una-clave-larga"}
        self.assertEqual(self.call("POST", "/api/auth/login", good)[0], 200)
        self.assertEqual(len(self.call("GET", "/api/knowledge")[1]), 1)

    def test_writes_from_another_site_are_refused(self) -> None:
        status, data = self.call("POST", "/api/auth/demo", {}, {"Origin": "https://evil.example"})
        self.assertEqual((status, data["error"]["code"]), (403, "cross_site_request"))
        self.assertEqual(self.call("POST", "/api/auth/demo", {}, {"Origin": self.base})[0], 200)


class DemoDisabledTest(ApiTestCase):
    signed_in: ClassVar[bool] = False
    settings_overrides: ClassVar[dict[str, object]] = {"demo_login": False}

    def test_demo_sign_in_can_be_turned_off(self) -> None:
        self.assertFalse(self.call("GET", "/api/health")[1]["demo_login"])
        self.assertEqual(self.call("POST", "/api/auth/demo")[0], 403)


class ClientAddressCase(ApiTestCase):
    """Login limits follow the client's address; X-Forwarded-For only counts behind a proxy."""

    signed_in = False

    def lock_from(self, forwarded_for: str) -> None:
        self.call("POST", "/api/auth/signup", SIGNUP)
        wrong = {"email": SIGNUP["email"], "password": "otra-clave"}
        for _ in range(MAX_FAILED_LOGINS):
            self.call("POST", "/api/auth/login", wrong, {"X-Forwarded-For": forwarded_for})

    def login_from(self, forwarded_for: str) -> int:
        right = {"email": SIGNUP["email"], "password": SIGNUP["password"]}
        return self.call("POST", "/api/auth/login", right, {"X-Forwarded-For": forwarded_for})[0]


class ClientAddressTest(ClientAddressCase):
    def test_the_header_is_ignored_without_a_proxy(self) -> None:
        self.lock_from("10.0.0.9")
        self.assertEqual(self.login_from("10.0.0.1"), 429)  # same socket address: still locked


class ClientAddressBehindProxyTest(ClientAddressCase):
    settings_overrides: ClassVar[dict[str, object]] = {"trust_proxy": True}

    def test_the_header_identifies_the_client(self) -> None:
        self.lock_from("10.0.0.9")
        self.assertEqual(self.login_from("10.0.0.9"), 429)
        self.assertEqual(self.login_from("203.0.113.5, 10.0.0.1"), 200)  # last entry is the client


if __name__ == "__main__":
    unittest.main()
