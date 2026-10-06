import importlib.util
import sqlite3
from pathlib import Path
from typing import Iterator

from . import config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


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


def _migrations() -> list[tuple[int, Path]]:
    """Файли NNN_назва.sql / NNN_назва.py у порядку номерів."""
    found = []
    for f in MIGRATIONS_DIR.iterdir():
        if f.suffix in (".sql", ".py") and f.stem[:3].isdigit():
            found.append((int(f.stem[:3]), f))
    return sorted(found)


def _run_py_migration(conn: sqlite3.Connection, path: Path) -> None:
    spec = importlib.util.spec_from_file_location(f"lapky_migration_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.migrate(conn)


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Накатує ще не застосовані міграції; кожна — в окремій транзакції. Повертає їхні номери."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version ("
                 "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now')))")
    conn.commit()
    done = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
    applied = []
    for version, path in _migrations():
        if version in done:
            continue
        try:
            conn.execute("BEGIN")
            if path.suffix == ".sql":
                for stmt in _split_sql(path.read_text(encoding="utf-8")):
                    conn.execute(stmt)
            else:
                _run_py_migration(conn, path)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        applied.append(version)
    return applied


def _split_sql(script: str) -> list[str]:
    """Ділить SQL-скрипт на оператори (без executescript, щоб не ламати транзакцію)."""
    stmts, buf = [], []
    for line in script.splitlines():
        line = line.split("--", 1)[0]
        if not line.strip():
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip()
            if sqlite3.complete_statement(stmt):
                stmts.append(stmt)
                buf = []
    if "".join(buf).strip():
        stmts.append("\n".join(buf))
    return stmts


def init_db(path: Path | None = None) -> None:
    conn = connect(path)
    try:
        migrate(conn)
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
