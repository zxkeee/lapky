import json
import sqlite3
from datetime import datetime, timedelta
from html import escape

from fastapi import APIRouter, Depends, Query

from .. import notify, repo
from ..db import get_db
from ..deps import Actor, require_bot
from ..models import OutboxAck

router = APIRouter(prefix="/api/internal", tags=["internal"])
MAX_ATTEMPTS = 3


@router.get("/outbox")
def outbox(limit: int = Query(50, ge=1, le=200), _: Actor = Depends(require_bot),
           conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute("SELECT id, telegram_id, text, buttons FROM outbox "
                        "WHERE sent_at IS NULL AND attempts < ? ORDER BY id LIMIT ?", (MAX_ATTEMPTS, limit)).fetchall()
    return [{**dict(r), "buttons": json.loads(r["buttons"])} for r in rows]


@router.post("/outbox/ack")
def outbox_ack(results: list[OutboxAck], _: Actor = Depends(require_bot),
               conn: sqlite3.Connection = Depends(get_db)):
    for res in results:
        if res.ok:
            conn.execute("UPDATE outbox SET sent_at = datetime('now'), attempts = attempts + 1 WHERE id = ?", (res.id,))
            continue
        attempts = MAX_ATTEMPTS if res.blocked else None
        conn.execute("UPDATE outbox SET attempts = COALESCE(?, attempts + 1), error = ? WHERE id = ?",
                     (attempts, (res.error or "")[:300], res.id))
        if res.blocked:
            row = conn.execute("SELECT telegram_id FROM outbox WHERE id = ?", (res.id,)).fetchone()
            if row:
                conn.execute("DELETE FROM subscriptions WHERE user_id = "
                             "(SELECT id FROM users WHERE telegram_id = ?)", (row[0],))
    conn.execute("DELETE FROM outbox WHERE sent_at IS NOT NULL AND sent_at < datetime('now', '-14 days')")
    return {"ok": True}


@router.post("/remind")
def remind(_: Actor = Depends(require_bot), conn: sqlite3.Connection = Depends(get_db)):
    now = datetime.now()
    rows = conn.execute(
        repo.TASK_SELECT + " WHERE t.status = 'open' AND t.reminded = 0 AND t.starts_at BETWEEN ? AND ?",
        (now.strftime("%Y-%m-%d %H:%M"), (now + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M"))).fetchall()
    sent = 0
    for r in rows:
        ids = [x[0] for x in conn.execute(
            "SELECT u.telegram_id FROM task_signups ts JOIN users u ON u.id = ts.user_id WHERE ts.task_id = ?",
            (r["id"],))]
        sent += notify.enqueue(
            conn, ids,
            f"⏰ Нагадування: «{escape(r['title'])}» у «{escape(r['shelter_name'])}» — {escape(r['starts_at'])}.",
            notify.shelter_button(r["shelter_id"]))
        conn.execute("UPDATE volunteer_tasks SET reminded = 1 WHERE id = ?", (r["id"],))
    return {"tasks": len(rows), "messages": sent}
