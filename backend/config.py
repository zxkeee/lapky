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
