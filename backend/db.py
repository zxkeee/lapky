import sqlite3
from pathlib import Path
from typing import Iterator

from . import config

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def _py_lower(value):
    # SQLite LOWER() не знає кирилиці — реєструємо свою функцію для пошуку
    return value.lower() if isinstance(value, str) else value


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.create_function("py_lower", 1, _py_lower, deterministic=True)
    return conn


def init_db(path: Path | None = None) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI-залежність: одне з'єднання на запит."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
