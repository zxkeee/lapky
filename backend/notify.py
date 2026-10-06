"""Черга сповіщень (таблиця outbox). Сервер лише кладе повідомлення — бот забирає й надсилає їх."""
import json
import sqlite3
from html import escape
from typing import Iterable, Optional

Buttons = list[list[dict]]


def enqueue(conn: sqlite3.Connection, telegram_ids: Iterable[int], text: str,
            buttons: Optional[Buttons] = None, exclude: Optional[int] = None) -> int:
    payload = json.dumps(buttons or [], ensure_ascii=False)
    sent = 0
    for tid in dict.fromkeys(telegram_ids):  # без дублів, зі збереженням порядку
        if tid == exclude:
            continue
        conn.execute("INSERT INTO outbox (telegram_id, text, buttons) VALUES (?, ?, ?)", (tid, text, payload))
        sent += 1
    return sent


def shelter_button(shelter_id: int, text: str = "Відкрити притулок") -> Buttons:
    return [[{"text": text, "callback_data": f"sh:{shelter_id}:all:0"}]]


def subscribers(conn: sqlite3.Connection, shelter_id: int, urgent: bool) -> list[int]:
    """Підписники притулку + підписники його області; only_urgent отримують лише термінове."""
    rows = conn.execute(
        """SELECT DISTINCT u.telegram_id FROM subscriptions sub
           JOIN users u ON u.id = sub.user_id
           JOIN shelters s ON s.id = ?
           WHERE (sub.shelter_id = s.id OR (sub.oblast IS NOT NULL AND sub.oblast = s.oblast))
             AND (sub.only_urgent = 0 OR ?)""",
        (shelter_id, 1 if urgent else 0),
    ).fetchall()
    return [r[0] for r in rows]


def managers(conn: sqlite3.Connection, shelter_id: int) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT u.telegram_id FROM shelter_managers m JOIN users u ON u.id = m.user_id WHERE m.shelter_id = ?",
        (shelter_id,))]


def admins(conn: sqlite3.Connection) -> list[int]:
    return [r[0] for r in conn.execute("SELECT telegram_id FROM users WHERE role = 'admin'")]


def _shelter(conn: sqlite3.Connection, shelter_id: int) -> sqlite3.Row:
    return conn.execute("SELECT id, name, urgency_level, status FROM shelters WHERE id = ?", (shelter_id,)).fetchone()


def new_need(conn, shelter_id: int, need_text: str, exclude: Optional[int] = None) -> int:
    s = _shelter(conn, shelter_id)
    if s is None or s["status"] != "published":
        return 0
    urgent = s["urgency_level"] == "red"
    head = "🔴 <b>Термінова потреба</b>" if urgent else "🆕 <b>Нова потреба</b>"
    text = f"{head} у притулку «{escape(s['name'])}»:\n{escape(need_text)}"
    return enqueue(conn, subscribers(conn, shelter_id, urgent), text, shelter_button(shelter_id), exclude)


def became_urgent(conn, shelter_id: int, exclude: Optional[int] = None) -> int:
    s = _shelter(conn, shelter_id)
    if s is None or s["status"] != "published":
        return 0
    text = f"🔴 Притулок «{escape(s['name'])}» перейшов у <b>критичний рівень</b> — потрібна допомога зараз."
    return enqueue(conn, subscribers(conn, shelter_id, True), text, shelter_button(shelter_id), exclude)


def new_task(conn, shelter_id: int, task: dict, exclude: Optional[int] = None) -> int:
    s = _shelter(conn, shelter_id)
    if s is None or s["status"] != "published":
        return 0
    text = (f"📋 <b>Нове волонтерське завдання</b> у «{escape(s['name'])}»:\n"
            f"{escape(task['title'])} — {escape(task['starts_at'])}, місць: {task['slots']}")
    buttons = [[{"text": "Записатися", "callback_data": f"task:{task['id']}"}]]
    return enqueue(conn, subscribers(conn, shelter_id, s["urgency_level"] == "red"), text, buttons, exclude)


def to_managers(conn, shelter_id: int, text: str, buttons: Optional[Buttons] = None) -> int:
    return enqueue(conn, managers(conn, shelter_id), text, buttons)


def to_admins(conn, text: str, buttons: Optional[Buttons] = None) -> int:
    return enqueue(conn, admins(conn), text, buttons)
