"""Shared test fixtures: an in-memory app with a frozen clock."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

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
