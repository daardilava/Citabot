"""Entry point: `python run.py` or `python -m citabot`."""

from __future__ import annotations

import logging

from citabot.config import Settings
from citabot.container import build_container
from citabot.interfaces.http.api import build_router
from citabot.interfaces.http.server import create_server


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    container = build_container(settings)
    try:
        server = create_server(settings.host, settings.port, build_router(container), settings.web_dir)
    except OSError as error:
        container.db.close()
        raise SystemExit(
            f"No se pudo abrir el puerto {settings.port} ({error}). "
            "Si está ocupado, elige otro con la variable CITABOT_PORT (ver .env.example)."
        ) from error
    url = f"http://{'localhost' if settings.host == '127.0.0.1' else settings.host}:{settings.port}"
    print(f"\n  Citabot listo en {url}\n  Mensajería: {settings.messaging_provider}\n  Ctrl+C para detener\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()
        container.db.close()


if __name__ == "__main__":
    main()
