"""Entry point: `python run.py` or `python -m citabot`."""

from __future__ import annotations

import logging
import socket

import uvicorn

from citabot.config import Settings
from citabot.container import build_container
from citabot.interfaces.http.app import create_app

# More simultaneous requests than this get a 503 instead of piling up.
MAX_CONCURRENCY = 64


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    container = build_container(settings)
    try:
        sock = socket.create_server((settings.host, settings.port))
    except OSError as error:
        container.db.close()
        raise SystemExit(
            f"No se pudo abrir el puerto {settings.port} ({error}). "
            "Si está ocupado, elige otro con la variable CITABOT_PORT (ver .env.example)."
        ) from error
    url = f"http://{'localhost' if settings.host == '127.0.0.1' else settings.host}:{settings.port}"
    print(
        f"\n  Citabot listo en {url}\n  API: {url}/api/docs\n"
        f"  Mensajería: {settings.messaging_provider}\n  Ctrl+C para detener\n"
    )
    config = uvicorn.Config(
        create_app(container),
        limit_concurrency=MAX_CONCURRENCY,
        timeout_keep_alive=5,
        server_header=False,
        proxy_headers=False,  # the client address is resolved by the app (CITABOT_TRUST_PROXY)
        access_log=False,
        log_level="info",
    )
    try:
        uvicorn.Server(config).run(sockets=[sock])
    finally:
        sock.close()
        container.close()
        print("\nServidor detenido.")


if __name__ == "__main__":
    main()
