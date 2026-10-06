import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

_db = Path(os.getenv("DB_PATH", "data/lapky.db"))
DB_PATH = _db if _db.is_absolute() else BASE_DIR / _db
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me-please")
BOT_USERNAME = os.getenv("BOT_USERNAME", "").lstrip("@")
WEB_DIR = BASE_DIR / "web"
# секрет, яким бот підписує запити від імені користувачів Telegram (X-Bot-Token)
BOT_API_TOKEN = os.getenv("BOT_API_TOKEN", "")
# Telegram ID адміністраторів (через кому) — отримують роль admin при першому зверненні
ADMIN_TELEGRAM_IDS = {int(x) for x in os.getenv("ADMIN_TELEGRAM_IDS", "").replace(" ", "").split(",") if x.isdigit()}
