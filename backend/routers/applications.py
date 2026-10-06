"""Заявки: «додати мій притулок» і «це мій притулок» (claim). Модерує адміністратор."""
import json
import sqlite3
from datetime import date
from html import escape
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from .. import notify, repo
from ..db import get_db
from ..deps import Actor, require_admin, require_user
from ..models import ApplicationIn, Decision, NewShelterPayload, ShelterIn
from .shelters import create_shelter_row

router = APIRouter(prefix="/api")

MODERATE_BUTTON = [[{"text": "Переглянути заявки", "callback_data": "mod:0"}]]


def _app_out(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["payload"] = json.loads(d["payload"] or "{}")
    return d


APP_SELECT = """
    SELECT a.*, u.telegram_id, u.username, u.first_name, s.name AS shelter_name
    FROM applications a JOIN users u ON u.id = a.user_id LEFT JOIN shelters s ON s.id = a.shelter_id
"""


@router.post("/applications", status_code=201, tags=["applications"])
def submit(body: ApplicationIn, actor: Actor = Depends(require_user), conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT COUNT(*) FROM applications WHERE user_id = ? AND status = 'pending'",
                    (actor.user_id,)).fetchone()[0] >= 5:
        raise HTTPException(429, "Забагато заявок очікують розгляду")
    if body.kind == "claim":
        s = repo.shelter_row(conn, body.shelter_id)
        if body.shelter_id in actor.managed:
            raise HTTPException(409, "Ви вже керуєте цим притулком")
        if conn.execute("SELECT 1 FROM applications WHERE kind = 'claim' AND shelter_id = ? AND user_id = ? "
                        "AND status = 'pending'", (body.shelter_id, actor.user_id)).fetchone():
            raise HTTPException(409, "Заявка вже на розгляді")
        payload = {"comment": body.comment}
        summary = f"🔑 Заявка «це мій притулок» на «{escape(s['name'])}»"
    else:
        payload = body.payload.model_dump()
        summary = f"➕ Заявка на новий притулок «{escape(body.payload.name)}», {escape(body.payload.city)}"
    aid = conn.execute("INSERT INTO applications (kind, shelter_id, user_id, payload) VALUES (?, ?, ?, ?)",
                       (body.kind, body.shelter_id, actor.user_id, json.dumps(payload, ensure_ascii=False))).lastrowid
    notify.to_admins(conn, f"{summary} від {repo.user_label(actor.user)}.", MODERATE_BUTTON)
    return _app_out(conn.execute(APP_SELECT + " WHERE a.id = ?", (aid,)).fetchone())


@router.get("/applications", tags=["applications"])
def list_applications(status: Literal["pending", "approved", "rejected"] = "pending",
                      _: Actor = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(APP_SELECT + " WHERE a.status = ? ORDER BY a.id", (status,)).fetchall()
    return [_app_out(r) for r in rows]


@router.get("/me/applications", tags=["applications"])
def my_applications(actor: Actor = Depends(require_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(APP_SELECT + " WHERE a.user_id = ? ORDER BY a.id DESC LIMIT 20", (actor.user_id,)).fetchall()
    return [_app_out(r) for r in rows]


def _pending(conn: sqlite3.Connection, app_id: int) -> sqlite3.Row:
    row = conn.execute(APP_SELECT + " WHERE a.id = ?", (app_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Заявку не знайдено")
    if row["status"] != "pending":
        raise HTTPException(409, "Заявку вже розглянуто")
    return row


@router.post("/applications/{app_id}/approve", tags=["applications"])
def approve(app_id: int, body: Decision, _: Actor = Depends(require_admin),
            conn: sqlite3.Connection = Depends(get_db)):
    app = _pending(conn, app_id)
    if app["kind"] == "new_shelter":
        p = NewShelterPayload(**json.loads(app["payload"]))
        shelter = ShelterIn(name=p.name, oblast=p.oblast, city=p.city, address=p.address, lat=p.lat, lng=p.lng,
                            phone=p.phone, contact_person=p.contact_person, links=p.links,
                            verified_at=date.today().isoformat())
        shelter_id = create_shelter_row(conn, shelter, source="application")
        conn.execute("UPDATE applications SET shelter_id = ? WHERE id = ?", (shelter_id, app_id))
    else:
        shelter_id = app["shelter_id"]
    conn.execute("INSERT OR IGNORE INTO shelter_managers (user_id, shelter_id) VALUES (?, ?)",
                 (app["user_id"], shelter_id))
    conn.execute("UPDATE applications SET status = 'approved', admin_note = ?, decided_at = datetime('now') "
                 "WHERE id = ?", (body.note, app_id))
    name = conn.execute("SELECT name FROM shelters WHERE id = ?", (shelter_id,)).fetchone()[0]
    note = f"\nКоментар: {escape(body.note)}" if body.note else ""
    notify.enqueue(conn, [app["telegram_id"]],
                   f"✅ Заявку схвалено! Тепер ви керуєте притулком «{escape(name)}»: потреби, збори, соцмережі "
                   f"й завдання — у команді /my.{note}",
                   [[{"text": "Мої притулки", "callback_data": "my"}]])
    return {"status": "approved", "shelter_id": shelter_id}


@router.post("/applications/{app_id}/reject", tags=["applications"])
def reject(app_id: int, body: Decision, _: Actor = Depends(require_admin),
           conn: sqlite3.Connection = Depends(get_db)):
    app = _pending(conn, app_id)
    conn.execute("UPDATE applications SET status = 'rejected', admin_note = ?, decided_at = datetime('now') "
                 "WHERE id = ?", (body.note, app_id))
    note = f"\nПричина: {escape(body.note)}" if body.note else ""
    notify.enqueue(conn, [app["telegram_id"]], f"❌ На жаль, заявку №{app_id} відхилено.{note}")
    return {"status": "rejected"}
