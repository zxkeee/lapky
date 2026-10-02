import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass(frozen=True)
class Settings:
    bot_token: str
    api_url: str
    web_url: str
    coordinator_email: str

    @property
    def web_url_is_public(self) -> bool:
        """Telegram не приймає localhost у кнопках-посиланнях."""
        p = urlparse(self.web_url)
        host = (p.hostname or "").lower()
        return p.scheme in ("http", "https") and host not in ("", "localhost", "127.0.0.1", "0.0.0.0") \
            and not host.endswith(".local")

    def shelter_url(self, shelter_id: int) -> str:
        return f"{self.web_url.rstrip('/')}/?shelter={shelter_id}"


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задано. Скопіюйте .env.example у .env і вставте токен від @BotFather.")
    return Settings(
        bot_token=token,
        api_url=os.getenv("API_URL", "http://127.0.0.1:8000"),
        web_url=os.getenv("WEB_URL", "http://127.0.0.1:8000"),
        coordinator_email=os.getenv("COORDINATOR_EMAIL", "lapky.team@example.com"),
    )
