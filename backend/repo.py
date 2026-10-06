import math
import sqlite3
from datetime import datetime

from fastapi import HTTPException, status

from .constants import CATEGORY_ORDER

EARTH_KM = 6371.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p = math.radians
    a = math.sin(p(lat2 - lat1) / 2) ** 2 + \
        math.cos(p(lat1)) * math.cos(p(lat2)) * math.sin(p(lng2 - lng1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def bbox_around(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    dlat = radius_km / 111.0
    dlng = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lng - dlng, lat + dlat, lng + dlng


def now_local() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _marks(ids: list[int]) -> str:
    return ",".join("?" * len(ids))


def needs_for(conn: sqlite3.Connection, shelter_ids: list[int]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {sid: [] for sid in shelter_ids}
    if not shelter_ids:
        return result
    rows = conn.execute(
        f"""SELECT n.*, (SELECT COUNT(*) FROM need_pledges p
                         WHERE p.need_id = n.id AND p.status = 'active') AS pledges_active
            FROM needs n WHERE n.shelter_id IN ({_marks(shelter_ids)}) ORDER BY n.id""",
        shelter_ids,
    ).fetchall()
    for r in rows:
        result[r["shelter_id"]].append({
            "id": r["id"], "category": r["category"], "subcategory": r["subcategory"],
            "text": r["text"], "updated_at": r["updated_at"], "pledges_active": r["pledges_active"],
        })
    for needs in result.values():
        needs.sort(key=lambda n: CATEGORY_ORDER[n["category"]])
    return result


def links_for(conn: sqlite3.Connection, shelter_ids: list[int]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {sid: [] for sid in shelter_ids}
    if shelter_ids:
        for r in conn.execute(f"SELECT * FROM shelter_links WHERE shelter_id IN ({_marks(shelter_ids)}) "
                              "ORDER BY position, id", shelter_ids):
            result[r["shelter_id"]].append({"id": r["id"], "kind": r["kind"], "url": r["url"]})
    return result


def fundraisers_for(conn: sqlite3.Connection, shelter_ids: list[int],
                    include_inactive: bool = False) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {sid: [] for sid in shelter_ids}
    if shelter_ids:
        sql = f"SELECT * FROM fundraisers WHERE shelter_id IN ({_marks(shelter_ids)})"
        if not include_inactive:
            sql += " AND active = 1"
        for r in conn.execute(sql + " ORDER BY id", shelter_ids):
            result[r["shelter_id"]].append({
                "id": r["id"], "title": r["title"], "kind": r["kind"], "value": r["value"],
                "note": r["note"], "active": bool(r["active"]),
            })
    return result


TASK_SELECT = """
    SELECT t.*, s.name AS shelter_name, s.lat, s.lng, s.oblast,
           (SELECT COUNT(*) FROM task_signups ts WHERE ts.task_id = t.id) AS taken
    FROM volunteer_tasks t JOIN shelters s ON s.id = t.shelter_id
"""


def task_dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "shelter_id": r["shelter_id"], "shelter_name": r["shelter_name"],
        "title": r["title"], "description": r["description"], "starts_at": r["starts_at"],
        "slots": r["slots"], "taken": r["taken"], "status": r["status"],
    }


def open_tasks_for(conn: sqlite3.Connection, shelter_ids: list[int]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {sid: [] for sid in shelter_ids}
    if shelter_ids:
        rows = conn.execute(
            TASK_SELECT + f" WHERE t.shelter_id IN ({_marks(shelter_ids)}) AND t.status = 'open' "
                          "AND t.starts_at >= ? ORDER BY t.starts_at",
            [*shelter_ids, now_local()],
        )
        for r in rows:
            result[r["shelter_id"]].append(task_dict(r))
    return result


def managed_ids(conn: sqlite3.Connection, shelter_ids: list[int]) -> set[int]:
    if not shelter_ids:
        return set()
    return {r[0] for r in conn.execute(
        f"SELECT DISTINCT shelter_id FROM shelter_managers WHERE shelter_id IN ({_marks(shelter_ids)})",
        shelter_ids)}


PUBLIC_FIELDS = ("id", "name", "urgency_level", "oblast", "city", "district", "address", "lat", "lng",
                 "phone", "contact_person", "source_url", "verified_at", "status", "source", "updated_at")


def assemble(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict]:
    ids = [r["id"] for r in rows]
    needs, links, funds = needs_for(conn, ids), links_for(conn, ids), fundraisers_for(conn, ids)
    tasks, managed = open_tasks_for(conn, ids), managed_ids(conn, ids)
    out = []
    for r in rows:
        d = {f: r[f] for f in PUBLIC_FIELDS}
        d.update(needs=needs[r["id"]], links=links[r["id"]], fundraisers=funds[r["id"]],
                 tasks=tasks[r["id"]], has_manager=r["id"] in managed)
        out.append(d)
    return out


def get_shelter(conn: sqlite3.Connection, shelter_id: int, published_only: bool = False) -> dict:
    row = conn.execute("SELECT * FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
    if row is None or (published_only and row["status"] != "published"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Притулок не знайдено")
    return assemble(conn, [row])[0]


def shelter_row(conn: sqlite3.Connection, shelter_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Притулок не знайдено")
    return row


def touch(conn: sqlite3.Connection, shelter_id: int, manual: bool = True) -> None:
    extra = ", edited_at = datetime('now')" if manual else ""
    conn.execute(f"UPDATE shelters SET updated_at = datetime('now'){extra} WHERE id = ?", (shelter_id,))


def insert_need(conn: sqlite3.Connection, shelter_id: int, category: str, subcategory, text: str) -> int:
    return conn.execute(
        "INSERT INTO needs (shelter_id, category, subcategory, text) VALUES (?, ?, ?, ?)",
        (shelter_id, category, subcategory, text.strip()),
    ).lastrowid


def insert_link(conn: sqlite3.Connection, shelter_id: int, kind: str, url: str) -> int:
    pos = conn.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM shelter_links WHERE shelter_id = ?",
                       (shelter_id,)).fetchone()[0]
    return conn.execute("INSERT INTO shelter_links (shelter_id, kind, url, position) VALUES (?, ?, ?, ?)",
                        (shelter_id, kind, url, pos)).lastrowid


def insert_fundraiser(conn: sqlite3.Connection, shelter_id: int, title: str, kind: str, value: str,
                      note) -> int:
    return conn.execute("INSERT INTO fundraisers (shelter_id, title, kind, value, note) VALUES (?, ?, ?, ?, ?)",
                        (shelter_id, title, kind, value, note)).lastrowid


def user_label(user: dict) -> str:
    from html import escape
    if user.get("username"):
        return "@" + escape(user["username"])
    name = escape(user.get("first_name") or "Волонтер")
    return f'<a href="tg://user?id={user["telegram_id"]}">{name}</a>'
