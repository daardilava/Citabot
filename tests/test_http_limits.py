"""The server survives clients that connect and then stall."""

from __future__ import annotations

import json
import socket
import threading
import time
import unittest
import urllib.request
from unittest import mock

from citabot.interfaces.http import server as http_server
from citabot.interfaces.http.api import build_router
from tests import support


class StalledClientTest(unittest.TestCase):
    def start(self, max_connections: int) -> str:
        c = support.make_container()
        with mock.patch.object(http_server, "REQUEST_TIMEOUT_SECONDS", 0.5):
            server = http_server.create_server(
                "127.0.0.1", 0, build_router(c), c.settings.web_dir, max_connections=max_connections
            )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(c.close)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]
        return f"http://127.0.0.1:{self.port}"

    def stall(self) -> socket.socket:
        """Announce a body and never send it."""
        sock = socket.create_connection(("127.0.0.1", self.port))
        self.addCleanup(sock.close)
        sock.sendall(
            b"POST /api/auth/login HTTP/1.1\r\nHost: x\r\n"
            b"Content-Type: application/json\r\nContent-Length: 100\r\n\r\n"
        )
        return sock

    def test_a_stalled_body_times_out_with_408(self) -> None:
        self.start(max_connections=4)
        sock = self.stall()
        sock.settimeout(5)
        reply = sock.recv(4096).decode()
        self.assertIn(" 408 ", reply.splitlines()[0])

    def test_a_stalled_client_does_not_block_the_server_for_good(self) -> None:
        base = self.start(max_connections=1)
        self.stall()  # takes the only slot until it times out
        started = time.monotonic()
        with urllib.request.urlopen(base + "/api/health", timeout=5) as response:
            self.assertEqual(json.loads(response.read())["status"], "ok")
        self.assertGreater(time.monotonic() - started, 0.3)  # it waited for the slot


if __name__ == "__main__":
    unittest.main()
