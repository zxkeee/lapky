import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import repo
from ..constants import OBLAST_TITLE
from ..db import get_db
from ..deps import Actor, require_user
from ..models import Me, MeIn, SubscriptionIn

router = APIRouter(prefix="/api")


def _me(conn: sqlite3.Connection, actor: Actor) -> dict:
    u = conn.execute("SELECT * FROM users WHERE id = ?", (actor.user_id,)).fetchone()
    shelters = [dict(r) for r in conn.execute(
        """SELECT s.id, s.name, s.status, s.urgency_level FROM shelter_managers m
           JOIN shelters s ON s.id = m.shelter_id WHERE m.user_id = ? ORDER BY s.name""", (actor.user_id,))]
    return {"id": u["id"], "telegram_id": u["telegram_id"], "username": u["username"],
            "first_name": u["first_name"], "role": u["role"], "is_admin": actor.is_admin, "shelters": shelters}


@router.get("/me", response_model=Me, tags=["users"])
def get_me(actor: Actor = Depends(require_user), conn: sqlite3.Connection = Depends(get_db)):
    return _me(conn, actor)


@router.post("/me", response_model=Me, tags=["users"])
def update_me(body: MeIn, actor: Actor = Depends(require_user), conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE users SET username = ?, first_name = ? WHERE id = ?",
                 (body.username, body.first_name, actor.user_id))
    actor.user = dict(conn.execute("SELECT * FROM users WHERE id = ?", (actor.user_id,)).fetchone())
    return _me(conn, actor)


def _subs(conn: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT sub.id, sub.shelter_id, sub.oblast, sub.only_urgent, s.name AS shelter_name
           FROM subscriptions sub LEFT JOIN shelters s ON s.id = sub.shelter_id
           WHERE sub.user_id = ? ORDER BY sub.id""", (user_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["only_urgent"] = bool(d["only_urgent"])
        d["title"] = f"«{d['shelter_name']}»" if d["shelter_id"] else f"{OBLAST_TITLE.get(d['oblast'], d['oblast'])}" + \
            ("" if d["oblast"] in ("kyiv", "sevastopol", "crimea") else " обл.")
        out.append(d)
    return out


@router.get("/me/subscriptions", tags=["volunteer"])
def my_subscriptions(actor: Actor = Depends(require_user), conn: sqlite3.Connection = Depends(get_db)):
    return _subs(conn, actor.user_id)


@router.post("/me/subscriptions", status_code=201, tags=["volunteer"])
def subscribe(body: SubscriptionIn, actor: Actor = Depends(require_user), conn: sqlite3.Connection = Depends(get_db)):
    if body.shelter_id is not None:
        repo.shelter_row(conn, body.shelter_id)
    existing = conn.execute(
        "SELECT id FROM subscriptions WHERE user_id = ? AND COALESCE(shelter_id, 0) = ? AND COALESCE(oblast, '') = ?",
        (actor.user_id, body.shelter_id or 0, body.oblast or "")).fetchone()
    if existing:
        conn.execute("UPDATE subscriptions SET only_urgent = ? WHERE id = ?", (int(body.only_urgent), existing[0]))
    else:
        conn.execute("INSERT INTO subscriptions (user_id, shelter_id, oblast, only_urgent) VALUES (?, ?, ?, ?)",
                     (actor.user_id, body.shelter_id, body.oblast, int(body.only_urgent)))
    return _subs(conn, actor.user_id)


@router.delete("/me/subscriptions/{sub_id}", status_code=204, tags=["volunteer"])
def unsubscribe(sub_id: int, actor: Actor = Depends(require_user), conn: sqlite3.Connection = Depends(get_db)):
    cur = conn.execute("DELETE FROM subscriptions WHERE id = ? AND user_id = ?", (sub_id, actor.user_id))
    if cur.rowcount == 0:
        raise HTTPException(404, "Підписку не знайдено")
    return Response(status_code=204)
