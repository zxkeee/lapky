"""Спільні залежності: хто робить запит і що йому дозволено.

Три способи автентифікації:
* X-Admin-Token — адмінський токен з .env (скрипти, Swagger, тести);
* X-Bot-Token + X-Telegram-User-Id — бот діє від імені користувача Telegram;
* нічого — анонімне читання (вебкарта).
"""
import secrets
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Depends, Header, HTTPException, status

from . import config
from .db import get_db


@dataclass
class Actor:
    user: Optional[dict] = None          # рядок із users
    is_admin: bool = False
    is_bot: bool = False
    managed: set[int] = field(default_factory=set)  # id притулків, якими керує користувач

    @property
    def user_id(self) -> Optional[int]:
        return self.user["id"] if self.user else None

    def can_manage(self, shelter_id: int) -> bool:
        return self.is_admin or shelter_id in self.managed


def _eq(a: str, b: str) -> bool:
    return bool(a) and bool(b) and secrets.compare_digest(a.encode(), b.encode())


def ensure_user(conn: sqlite3.Connection, telegram_id: int) -> dict:
    row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if row is None:
        role = "admin" if telegram_id in config.ADMIN_TELEGRAM_IDS else "volunteer"
        conn.execute("INSERT INTO users (telegram_id, role) VALUES (?, ?)", (telegram_id, role))
        row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
    elif telegram_id in config.ADMIN_TELEGRAM_IDS and row["role"] != "admin":
        conn.execute("UPDATE users SET role = 'admin' WHERE id = ?", (row["id"],))
        row = conn.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
    return dict(row)


def get_actor(
    x_admin_token: Optional[str] = Header(None, description="Токен адміністратора з .env"),
    x_bot_token: Optional[str] = Header(None, description="Секрет бота (BOT_API_TOKEN)"),
    x_telegram_user_id: Optional[int] = Header(None, description="Telegram ID користувача, від імені якого діє бот"),
    conn: sqlite3.Connection = Depends(get_db),
) -> Actor:
    actor = Actor()
    if x_admin_token is not None:
        if not _eq(x_admin_token, config.ADMIN_TOKEN):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Невірний X-Admin-Token")
        actor.is_admin = True
    if x_bot_token is not None:
        if not _eq(x_bot_token, config.BOT_API_TOKEN):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Невірний X-Bot-Token")
        actor.is_bot = True
        if x_telegram_user_id is not None:
            actor.user = ensure_user(conn, x_telegram_user_id)
            actor.is_admin = actor.is_admin or actor.user["role"] == "admin"
            actor.managed = {r[0] for r in conn.execute(
                "SELECT shelter_id FROM shelter_managers WHERE user_id = ?", (actor.user["id"],))}
    return actor


def require_user(actor: Actor = Depends(get_actor)) -> Actor:
    if actor.user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Потрібен вхід через Telegram-бота")
    return actor


def require_admin(actor: Actor = Depends(get_actor)) -> Actor:
    if not actor.is_admin:
        code = status.HTTP_401_UNAUTHORIZED if actor.user is None else status.HTTP_403_FORBIDDEN
        raise HTTPException(code, "Потрібні права адміністратора")
    return actor


def require_bot(actor: Actor = Depends(get_actor)) -> Actor:
    if not actor.is_bot:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Лише для бота (X-Bot-Token)")
    return actor


def check_manage(actor: Actor, shelter_id: int) -> None:
    if not actor.can_manage(shelter_id):
        code = status.HTTP_401_UNAUTHORIZED if (actor.user is None and not actor.is_admin) else status.HTTP_403_FORBIDDEN
        raise HTTPException(code, "Немає прав керувати цим притулком")
