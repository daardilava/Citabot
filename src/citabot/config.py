"""Configuration from environment variables (twelve-factor), with an optional .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines; real environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    db_path: str
    web_dir: Path
    messaging_provider: str  # "simulator" | "whatsapp_cloud"
    whatsapp_access_token: str
    whatsapp_phone_number_id: str
    whatsapp_verify_token: str
    whatsapp_app_secret: str
    whatsapp_api_version: str
    # Single-tenant MVP: every request acts on this business. With authentication,
    # the tenant comes from the session instead (see interfaces/http/api.py).
    default_business_id: int = 1
    nlu_provider: str = "rules"  # "rules" | "llm"
    llm_model: str = "claude-opus-5-5"
    answer_provider: str = "extractive"  # "extractive" | "llm"
    # With the LLM writing answers, a knowledge base up to this many characters is
    # read whole on every question instead of searched (about 3,000 tokens).
    whole_base_max_chars: int = 12_000
    llm_ipv4_only: bool = True

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv(PROJECT_ROOT / ".env")
        env = os.environ.get
        provider = env("MESSAGING_PROVIDER", "simulator")
        if provider not in {"simulator", "whatsapp_cloud"}:
            raise ValueError("MESSAGING_PROVIDER must be 'simulator' or 'whatsapp_cloud'")
        nlu_provider = env("NLU_PROVIDER", "rules")
        if nlu_provider not in {"rules", "llm"}:
            raise ValueError("NLU_PROVIDER must be 'rules' or 'llm'")
        answer_provider = env("ANSWER_PROVIDER", "extractive")
        if answer_provider not in {"extractive", "llm"}:
            raise ValueError("ANSWER_PROVIDER must be 'extractive' or 'llm'")
        return cls(
            host=env("CITABOT_HOST", "127.0.0.1"),
            port=int(env("CITABOT_PORT", "8000")),
            db_path=env("CITABOT_DB_PATH", str(PROJECT_ROOT / "data" / "citabot.db")),
            web_dir=PROJECT_ROOT / "web",
            messaging_provider=provider,
            whatsapp_access_token=env("WHATSAPP_ACCESS_TOKEN", ""),
            whatsapp_phone_number_id=env("WHATSAPP_PHONE_NUMBER_ID", ""),
            whatsapp_verify_token=env("WHATSAPP_VERIFY_TOKEN", ""),
            whatsapp_app_secret=env("WHATSAPP_APP_SECRET", ""),
            whatsapp_api_version=env("WHATSAPP_API_VERSION", "v21.0"),
            nlu_provider=nlu_provider,
            llm_model=env("CITABOT_LLM_MODEL", "claude-opus-5-5"),
            answer_provider=answer_provider,
            whole_base_max_chars=int(env("CITABOT_WHOLE_BASE_MAX_CHARS", "12000")),
            llm_ipv4_only=env("CITABOT_LLM_IPV4_ONLY", "1") != "0",
        )
