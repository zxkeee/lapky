import sqlite3
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import notify, repo
from ..db import get_db
from ..deps import Actor, check_manage, get_actor, require_user
from ..models import OblastKey, Task, TaskIn, TaskPatch

router = APIRouter(prefix="/api")


def _task(conn: sqlite3.Connection, task_id: int) -> dict:
    row = conn.execute(repo.TASK_SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Завдання не знайдено")
    return repo.task_dict(row)


@router.get("/tasks", response_model=list[Task], tags=["read"])
def list_tasks(
    oblast: Optional[OblastKey] = None,
    shelter_id: Optional[int] = None,
    near: Optional[str] = Query(None, description="lat,lng"),
    radius_km: float = Query(50, gt=0, le=300),
    limit: int = Query(50, ge=1, le=200),
    conn: sqlite3.Connection = Depends(get_db),
):
    where, params = ["t.status = 'open'", "t.starts_at >= ?", "s.status = 'published'"], [repo.now_local()]
    if oblast:
        where.append("s.oblast = ?")
        params.append(oblast)
    if shelter_id:
        where.append("t.shelter_id = ?")
        params.append(shelter_id)
    rows = conn.execute(repo.TASK_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY t.starts_at",
                        params).fetchall()
    tasks = []
    if near:
        try:
            lat, lng = (float(x) for x in near.split(","))
        except ValueError:
            raise HTTPException(422, "near: очікується lat,lng")
        for r in rows:
            d = repo.haversine_km(lat, lng, r["lat"], r["lng"])
            if d <= radius_km:
                tasks.append({**repo.task_dict(r), "distance_km": round(d, 1)})
        tasks.sort(key=lambda t: (t["distance_km"], t["starts_at"]))
    else:
        tasks = [repo.task_dict(r) for r in rows]
    return tasks[:limit]


@router.get("/tasks/{task_id}", response_model=Task, tags=["read"])
def get_task(task_id: int, conn: sqlite3.Connection = Depends(get_db)):
    return _task(conn, task_id)


@router.post("/shelters/{shelter_id}/tasks", response_model=Task, status_code=201, tags=["manage"])
def create_task(shelter_id: int, body: TaskIn, actor: Actor = Depends(get_actor),
                conn: sqlite3.Connection = Depends(get_db)):
    repo.shelter_row(conn, shelter_id)
    check_manage(actor, shelter_id)
    if body.starts_at < repo.now_local():
        raise HTTPException(422, "Дата завдання вже минула")
    tid = conn.execute(
        "INSERT INTO volunteer_tasks (shelter_id, title, description, starts_at, slots) VALUES (?, ?, ?, ?, ?)",
        (shelter_id, body.title.strip(), body.description, body.starts_at, body.slots)).lastrowid
    task = _task(conn, tid)
    notify.new_task(conn, shelter_id, task, exclude=actor.user["telegram_id"] if actor.user else None)
    return task


@router.patch("/tasks/{task_id}", response_model=Task, tags=["manage"])
def update_task(task_id: int, body: TaskPatch, actor: Actor = Depends(get_actor),
                conn: sqlite3.Connection = Depends(get_db)):
    task = _task(conn, task_id)
    check_manage(actor, task["shelter_id"])
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "description"}
    if data.get("slots") is not None and data["slots"] < task["taken"]:
        raise HTTPException(409, f"Уже записалося {task['taken']} — менше місць зробити не можна")
    if data:
        if "starts_at" in data:
            data["reminded"] = 0
        conn.execute(f"UPDATE volunteer_tasks SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                     [*data.values(), task_id])
    if data.get("status") == "closed" and task["status"] == "open":
        _notify_signups(conn, task_id, f"ℹ️ Завдання «{escape(task['title'])}» у «{escape(task['shelter_name'])}» "
                                       "скасовано або вже виконано. Дякуємо, що відгукнулися!")
    return _task(conn, task_id)


@router.delete("/tasks/{task_id}", status_code=204, tags=["manage"])
def delete_task(task_id: int, actor: Actor = Depends(get_actor), conn: sqlite3.Connection = Depends(get_db)):
    task = _task(conn, task_id)
    check_manage(actor, task["shelter_id"])
    _notify_signups(conn, task_id, f"ℹ️ Завдання «{escape(task['title'])}» у «{escape(task['shelter_name'])}» "
                                   "скасовано.")
    conn.execute("DELETE FROM volunteer_tasks WHERE id = ?", (task_id,))
    return Response(status_code=204)


def _notify_signups(conn: sqlite3.Connection, task_id: int, text: str) -> None:
    ids = [r[0] for r in conn.execute(
        "SELECT u.telegram_id FROM task_signups ts JOIN users u ON u.id = ts.user_id WHERE ts.task_id = ?",
        (task_id,))]
    notify.enqueue(conn, ids, text)


@router.post("/tasks/{task_id}/signup", response_model=Task, status_code=201, tags=["volunteer"])
def signup(task_id: int, actor: Actor = Depends(require_user), conn: sqlite3.Connection = Depends(get_db)):
    task = _task(conn, task_id)
    if task["status"] != "open" or task["starts_at"] < repo.now_local():
        raise HTTPException(409, "Запис на це завдання закрито")
    if conn.execute("SELECT 1 FROM task_signups WHERE task_id = ? AND user_id = ?",
                    (task_id, actor.user_id)).fetchone():
        raise HTTPException(409, "Ви вже записані")
    if task["taken"] >= task["slots"]:
        raise HTTPException(409, "Усі місця вже зайняті")
    conn.execute("INSERT INTO task_signups (task_id, user_id) VALUES (?, ?)", (task_id, actor.user_id))
    task = _task(conn, task_id)
    notify.to_managers(conn, task["shelter_id"],
                       f"📋 {repo.user_label(actor.user)} записався(лася) на «{escape(task['title'])}» "
                       f"({escape(task['starts_at'])}). Зайнято {task['taken']}/{task['slots']}.")
    return task


@router.delete("/tasks/{task_id}/signup", status_code=204, tags=["volunteer"])
def cancel_signup(task_id: int, actor: Actor = Depends(require_user), conn: sqlite3.Connection = Depends(get_db)):
    task = _task(conn, task_id)
    cur = conn.execute("DELETE FROM task_signups WHERE task_id = ? AND user_id = ?", (task_id, actor.user_id))
    if cur.rowcount == 0:
        raise HTTPException(404, "Ви не записані на це завдання")
    notify.to_managers(conn, task["shelter_id"],
                       f"❌ {repo.user_label(actor.user)} скасував(ла) запис на «{escape(task['title'])}» "
                       f"({escape(task['starts_at'])}).")
    return Response(status_code=204)


@router.get("/tasks/{task_id}/signups", tags=["manage"])
def task_signups(task_id: int, actor: Actor = Depends(get_actor), conn: sqlite3.Connection = Depends(get_db)):
    task = _task(conn, task_id)
    check_manage(actor, task["shelter_id"])
    rows = conn.execute(
        """SELECT u.telegram_id, u.username, u.first_name, ts.created_at
           FROM task_signups ts JOIN users u ON u.id = ts.user_id WHERE ts.task_id = ? ORDER BY ts.created_at""",
        (task_id,)).fetchall()
    return [dict(r) for r in rows]


@router.get("/me/tasks", response_model=list[Task], tags=["volunteer"])
def my_tasks(actor: Actor = Depends(require_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        repo.TASK_SELECT + " JOIN task_signups ts ON ts.task_id = t.id "
                           "WHERE ts.user_id = ? AND t.starts_at >= ? ORDER BY t.starts_at",
        (actor.user_id, repo.now_local())).fetchall()
    return [repo.task_dict(r) for r in rows]
