"""The server survives clients that connect and then stall, and answers what it refuses."""

from __future__ import annotations

import contextlib
import json
import socket
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from citabot.interfaces.http import guard
from citabot.interfaces.http.app import create_app
from tests import support


class ServerTestCase(unittest.TestCase):
    def start(self, limit_concurrency: int | None = None) -> str:
        c = support.make_container()
        self.addCleanup(c.close)
        base, stop = support.serve(create_app(c), limit_concurrency=limit_concurrency)
        self.addCleanup(stop)
        self.port = int(base.rsplit(":", 1)[1])
        return base

    def stall(self) -> socket.socket:
        """Announce a body and never send it."""
        sock = socket.create_connection(("127.0.0.1", self.port))
        self.addCleanup(sock.close)
        sock.sendall(
            b"POST /api/auth/login HTTP/1.1\r\nHost: x\r\n"
            b"Content-Type: application/json\r\nContent-Length: 100\r\n\r\n"
        )
        return sock


class StalledClientTest(ServerTestCase):
    def test_a_stalled_body_times_out_with_408(self) -> None:
        self.start()
        with mock.patch.object(guard, "REQUEST_TIMEOUT_SECONDS", 0.5):
            sock = self.stall()
            sock.settimeout(5)
            reply = sock.recv(4096).decode()
        self.assertIn(" 408 ", reply.splitlines()[0])

    def test_a_stalled_client_does_not_hold_up_anyone_else(self) -> None:
        base = self.start()
        self.stall()
        started = time.monotonic()
        with urllib.request.urlopen(base + "/api/health", timeout=5) as response:
            self.assertEqual(json.loads(response.read())["status"], "ok")
        self.assertLess(time.monotonic() - started, 2)

    def test_past_the_concurrency_limit_requests_get_503(self) -> None:
        base = self.start(limit_concurrency=1)
        self.stall()  # holds the only slot while it waits for its body
        time.sleep(0.2)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(base + "/api/health", timeout=5)
        self.assertEqual(caught.exception.code, 503)


class RejectedRequestTest(ServerTestCase):
    """A request refused before its handler runs still gets its error response.

    Closing a socket with unread data makes the OS reset the connection, which
    can discard the response before the client reads it. The server has to
    read the body even when it is about to refuse the request.
    """

    def test_the_403_for_a_cross_site_write_always_arrives(self) -> None:
        self.start()
        body = b"x" * 256_000
        head = (
            "POST /api/auth/login HTTP/1.1\r\n"
            "Host: 127.0.0.1\r\n"
            "Origin: https://evil.example\r\n"
            f"Content-Length: {len(body)}\r\n\r\n"
        )
        for attempt in range(30):
            with self.subTest(attempt=attempt), socket.create_connection(("127.0.0.1", self.port)) as sock:
                sock.settimeout(5)
                # Like urllib: headers first, body a moment later, after the server
                # may already have answered.
                sock.sendall(head.encode())
                time.sleep(0.02)
                with contextlib.suppress(OSError):  # the server may have closed already
                    sock.sendall(body)
                status_line = sock.recv(4096).split(b"\r\n", 1)[0]
                self.assertIn(b" 403 ", status_line)

    def test_a_body_over_the_limit_is_refused_with_413(self) -> None:
        base = self.start()
        request = urllib.request.Request(
            base + "/api/auth/login", data=b"x" * (guard.MAX_BODY_BYTES + 1), method="POST"
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 413)


if __name__ == "__main__":
    unittest.main()
