import pytest
from fastapi.testclient import TestClient

from backend import config

ADMIN = {"X-Admin-Token": "test-token"}
BOT_TOKEN = "bot-secret"
ADMIN_TG = 1000  # Telegram ID адміністратора в тестах


def as_user(telegram_id: int) -> dict:
    """Заголовки запиту, ніби бот діє від імені користувача Telegram."""
    return {"X-Bot-Token": BOT_TOKEN, "X-Telegram-User-Id": str(telegram_id)}


BOT = {"X-Bot-Token": BOT_TOKEN}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "ADMIN_TOKEN", "test-token")
    monkeypatch.setattr(config, "BOT_API_TOKEN", BOT_TOKEN)
    monkeypatch.setattr(config, "ADMIN_TELEGRAM_IDS", {ADMIN_TG})
    from backend.main import app
    from backend.seed import seed
    with TestClient(app) as c:
        seed(reset=True)
        yield c


def outbox(client) -> list[dict]:
    return client.get("/api/internal/outbox?limit=200", headers=BOT).json()
