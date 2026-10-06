"""Потреби притулку і «беру потребу» (обіцянки волонтерів)."""
import sqlite3
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import notify, repo
from ..db import get_db
from ..deps import Actor, check_manage, get_actor, require_user
from ..models import Need, NeedIn, NeedPatch, PledgeIn, PledgePatch, check_sub

router = APIRouter(prefix="/api")


def _need(conn: sqlite3.Connection, need_id: int) -> dict:
    row = conn.execute(
        """SELECT n.*, (SELECT COUNT(*) FROM need_pledges p WHERE p.need_id = n.id AND p.status = 'active')
                  AS pledges_active
           FROM needs n WHERE n.id = ?""", (need_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Потребу не знайдено")
    return dict(row)


@router.post("/shelters/{shelter_id}/needs", response_model=Need, status_code=201, tags=["manage"])
def add_need(shelter_id: int, body: NeedIn, actor: Actor = Depends(get_actor),
             conn: sqlite3.Connection = Depends(get_db)):
    repo.shelter_row(conn, shelter_id)
    check_manage(actor, shelter_id)
    need_id = repo.insert_need(conn, shelter_id, body.category, body.subcategory, body.text)
    repo.touch(conn, shelter_id)
    notify.new_need(conn, shelter_id, body.text, exclude=actor.user["telegram_id"] if actor.user else None)
    return _need(conn, need_id)


@router.patch("/needs/{need_id}", response_model=Need, tags=["manage"])
def update_need(need_id: int, body: NeedPatch, actor: Actor = Depends(get_actor),
                conn: sqlite3.Connection = Depends(get_db)):
    row = _need(conn, need_id)
    check_manage(actor, row["shelter_id"])
    merged = {**row, **body.model_dump(exclude_unset=True)}
    if merged.get("category") is None or not merged.get("text"):
        raise HTTPException(422, "category і text обов'язкові")
    if merged["category"] != "food":
        merged["subcategory"] = None
    try:
        check_sub(merged["category"], merged["subcategory"])
    except ValueError as e:
        raise HTTPException(422, str(e))
    conn.execute(
        "UPDATE needs SET category = ?, subcategory = ?, text = ?, updated_at = datetime('now') WHERE id = ?",
        (merged["category"], merged["subcategory"], merged["text"].strip(), need_id),
    )
    repo.touch(conn, row["shelter_id"])
    return _need(conn, need_id)


@router.delete("/needs/{need_id}", status_code=204, tags=["manage"])
def delete_need(need_id: int, actor: Actor = Depends(get_actor), conn: sqlite3.Connection = Depends(get_db)):
    row = _need(conn, need_id)
    check_manage(actor, row["shelter_id"])
    # волонтерів, які вже везуть це, попереджаємо
    for p in conn.execute("""SELECT u.telegram_id FROM need_pledges p JOIN users u ON u.id = p.user_id
                             WHERE p.need_id = ? AND p.status = 'active'""", (need_id,)).fetchall():
        notify.enqueue(conn, [p[0]], f"ℹ️ Притулок закрив потребу «{escape(row['text'])}», яку ви взяли. "
                                     "Дякуємо! Уточніть у притулку, чи ще актуально.")
    conn.execute("DELETE FROM needs WHERE id = ?", (need_id,))
    repo.touch(conn, row["shelter_id"])
    return Response(status_code=204)


# ---------- «Беру потребу» ----------

def _pledge_out(r: sqlite3.Row) -> dict:
    return {k: r[k] for k in r.keys()}


@router.post("/needs/{need_id}/pledges", status_code=201, tags=["volunteer"])
def pledge(need_id: int, body: PledgeIn, actor: Actor = Depends(require_user),
           conn: sqlite3.Connection = Depends(get_db)):
    need = _need(conn, need_id)
    s = repo.shelter_row(conn, need["shelter_id"])
    if conn.execute("SELECT 1 FROM need_pledges WHERE need_id = ? AND user_id = ? AND status = 'active'",
                    (need_id, actor.user_id)).fetchone():
        raise HTTPException(409, "Ви вже взяли цю потребу")
    pid = conn.execute("INSERT INTO need_pledges (need_id, user_id, note) VALUES (?, ?, ?)",
                       (need_id, actor.user_id, body.note)).lastrowid
    note = f"\nКоментар: {escape(body.note)}" if body.note else ""
    notify.to_managers(conn, s["id"],
                       f"🙋 {repo.user_label(actor.user)} бере потребу «{escape(need['text'])}» "
                       f"для «{escape(s['name'])}».{note}\nЗв'яжіться з волонтером, щоб домовитися.")
    return {"id": pid, "need_id": need_id, "status": "active"}


def _pledge(conn: sqlite3.Connection, pid: int) -> sqlite3.Row:
    row = conn.execute(
        """SELECT p.*, n.text AS need_text, n.shelter_id, s.name AS shelter_name
           FROM need_pledges p JOIN needs n ON n.id = p.need_id JOIN shelters s ON s.id = n.shelter_id
           WHERE p.id = ?""", (pid,)).fetchone()
    if row is None:
        raise HTTPException(404, "Обіцянку не знайдено")
    return row


@router.patch("/pledges/{pid}", tags=["volunteer"])
def update_pledge(pid: int, body: PledgePatch, actor: Actor = Depends(require_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    p = _pledge(conn, pid)
    is_owner = p["user_id"] == actor.user_id
    if not (is_owner or actor.can_manage(p["shelter_id"])):
        raise HTTPException(403, "Це не ваша обіцянка")
    if p["status"] != "active":
        raise HTTPException(409, "Обіцянка вже закрита")
    conn.execute("UPDATE need_pledges SET status = ?, updated_at = datetime('now') WHERE id = ?", (body.status, pid))
    if is_owner:
        verb = "привіз(ла) ✅" if body.status == "done" else "скасував(ла) ❌"
        notify.to_managers(conn, p["shelter_id"],
                           f"{repo.user_label(actor.user)} {verb} «{escape(p['need_text'])}» "
                           f"для «{escape(p['shelter_name'])}».")
    return _pledge_out(_pledge(conn, pid))


@router.get("/me/pledges", tags=["volunteer"])
def my_pledges(actor: Actor = Depends(require_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        """SELECT p.id, p.status, p.note, p.created_at, n.id AS need_id, n.text AS need_text,
                  s.id AS shelter_id, s.name AS shelter_name
           FROM need_pledges p JOIN needs n ON n.id = p.need_id JOIN shelters s ON s.id = n.shelter_id
           WHERE p.user_id = ? AND p.status = 'active' ORDER BY p.id DESC""", (actor.user_id,)).fetchall()
    return [dict(r) for r in rows]


@router.get("/shelters/{shelter_id}/pledges", tags=["manage"])
def shelter_pledges(shelter_id: int, actor: Actor = Depends(get_actor), conn: sqlite3.Connection = Depends(get_db)):
    """Активні обіцянки волонтерів — лише для менеджера (тут контакти волонтерів)."""
    repo.shelter_row(conn, shelter_id)
    check_manage(actor, shelter_id)
    rows = conn.execute(
        """SELECT p.id, p.note, p.created_at, n.id AS need_id, n.text AS need_text,
                  u.telegram_id, u.username, u.first_name
           FROM need_pledges p JOIN needs n ON n.id = p.need_id JOIN users u ON u.id = p.user_id
           WHERE n.shelter_id = ? AND p.status = 'active' ORDER BY p.id DESC""", (shelter_id,)).fetchall()
    return [dict(r) for r in rows]
