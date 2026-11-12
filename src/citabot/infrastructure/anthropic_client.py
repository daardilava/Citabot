"""Creates the Anthropic SDK client, imported only when an LLM adapter is enabled."""

from __future__ import annotations

import importlib
from typing import Any

TIMEOUT_SECONDS = 15.0


def create_client(ipv4_only: bool = True) -> Any:
    try:
        anthropic = importlib.import_module("anthropic")
    except ImportError as exc:
        raise RuntimeError("Los adaptadores LLM necesitan el SDK de Anthropic: pip install anthropic") from exc
    options: dict[str, Any] = {"timeout": TIMEOUT_SECONDS, "max_retries": 1}
    if ipv4_only:
        # On a network that advertises IPv6 but cannot route it, every new connection
        # waits ~20 s for the IPv6 attempt to time out before trying IPv4. Binding the
        # socket to an IPv4 address skips that attempt.
        httpx = importlib.import_module("httpx2")  # the HTTP library of anthropic 1.x+
        transport = httpx.HTTPTransport(local_address="0.0.0.0")
        options["http_client"] = anthropic.DefaultHttpxClient(transport=transport)
    # Credentials come from the environment (ANTHROPIC_API_KEY, which .env can provide).
    return anthropic.Anthropic(**options)
