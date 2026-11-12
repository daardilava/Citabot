"""Gateway used in local development: nothing leaves the machine.

Outbound messages are already stored in the conversation, which is what the
browser simulator reads, so "sending" only needs to log.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

logger = logging.getLogger(__name__)


class SimulatorGateway:
    def send_text(self, to_phone: str, text: str, options: Sequence[str] = ()) -> None:
        logger.info("-> %s: %s %s", to_phone, text.replace("\n", " ")[:80], list(options) or "")
