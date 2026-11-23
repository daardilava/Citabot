"""Shared test fixtures: an in-memory app with a frozen clock."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import uvicorn

from citabot.config import Settings
from citabot.container import Container, build_container
from citabot.infrastructure.clock import FixedClock

ROOT = Path(__file__).resolve().parents[1]

# Thursday evening: the clinic is closed, so "today" has no slots left.
NOW = datetime(2026, 11, 12, 19, 30)
BUSINESS_ID = 1


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "host": "127.0.0.1",
        "port": 0,
        "db_path": ":memory:",
        "web_dir": ROOT / "web",
        "messaging_provider": "simulator",
        "whatsapp_access_token": "",
        "whatsapp_phone_number_id": "",
        "whatsapp_verify_token": "",
        "whatsapp_app_secret": "",
        "whatsapp_api_version": "v21.0",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def make_container(now: datetime = NOW, **overrides: object) -> Container:
    return build_container(make_settings(**overrides), clock=FixedClock(now))


def serve(app: Any, limit_concurrency: int | None = None) -> tuple[str, Callable[[], None]]:
    """Run an ASGI app with uvicorn on a free local port, in a background thread.

    Returns the base URL and a function that stops the server.
    """
    sock = socket.create_server(("127.0.0.1", 0))
    config = uvicorn.Config(
        app,
        log_level="warning",
        access_log=False,
        lifespan="off",
        limit_concurrency=limit_concurrency,
        proxy_headers=False,  # as in production: the app resolves the client address itself
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.01)

    def stop() -> None:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()

    return f"http://127.0.0.1:{sock.getsockname()[1]}", stop
