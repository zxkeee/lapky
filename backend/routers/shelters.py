import sqlite3
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from .. import config, notify, repo
from ..constants import (
    CATEGORIES, FUNDRAISER_KINDS, LINK_KINDS, OBLASTS, URGENCY, URGENCY_ORDER,
)
from ..db import get_db
from ..deps import Actor, check_manage, get_actor, require_admin
from ..models import (
    CategoryKey, Fundraiser, FundraiserIn, FundraiserPatch, Link, LinkIn, OblastKey, Shelter,
    ShelterIn, ShelterPatch, SubcategoryKey, Urgency,
)

router = APIRouter(prefix="/api")


@router.get("/health", tags=["service"])
def health():
    return {"status": "ok"}


@router.get("/meta", tags=["read"])
def meta():
    return {
        "urgency": URGENCY,
        "categories": CATEGORIES,
        "oblasts": [{"key": o["key"], "title": o["title"]} for o in OBLASTS],
        "link_kinds": LINK_KINDS,
        "fundraiser_kinds": FUNDRAISER_KINDS,
        "bot_url": f"https://t.me/{config.BOT_USERNAME}" if config.BOT_USERNAME else None,
    }


@router.get("/oblasts", tags=["read"])
def oblasts(conn: sqlite3.Connection = Depends(get_db)):
    counts = {r["oblast"]: (r["n"], r["red"]) for r in conn.execute(
        "SELECT oblast, COUNT(*) AS n, SUM(urgency_level = 'red') AS red FROM shelters "
        "WHERE status = 'published' GROUP BY oblast")}
    return [{"key": o["key"], "title": o["title"], "count": counts.get(o["key"], (0, 0))[0],
             "red": counts.get(o["key"], (0, 0))[1] or 0} for o in OBLASTS]


def _parse_floats(raw: str, n: int, name: str) -> list[float]:
    try:
        vals = [float(x) for x in raw.split(",")]
    except ValueError:
        vals = []
    if len(vals) != n:
        raise HTTPException(422, f"{name}: очікується {n} числа через кому")
    return vals


@router.get("/shelters", response_model=list[Shelter], tags=["read"])
def list_shelters(
    response: Response,
    category: Optional[CategoryKey] = None,
    subcategory: Optional[SubcategoryKey] = None,
    urgency: Optional[Urgency] = None,
    oblast: Optional[OblastKey] = None,
    q: Optional[str] = Query(None, max_length=100, description="Пошук за назвою, містом, районом, адресою"),
    bbox: Optional[str] = Query(None, description="minLng,minLat,maxLng,maxLat — видима область карти"),
    near: Optional[str] = Query(None, description="lat,lng — шукати поруч (відповідь містить distance_km)"),
    radius_km: float = Query(25, gt=0, le=300),
    sort: Literal["urgency", "name", "distance"] = "urgency",
    limit: Optional[int] = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
):
    if subcategory is not None:
        if category not in (None, "food"):
            raise HTTPException(422, "subcategory дозволена лише разом із category=food")
        category = "food"

    where, params = ["s.status = 'published'"], []
    if category == "finance":
        where.append(
            "(EXISTS (SELECT 1 FROM fundraisers f WHERE f.shelter_id = s.id AND f.active = 1) OR EXISTS "
            "(SELECT 1 FROM needs n WHERE n.shelter_id = s.id AND n.category = 'finance'))"
        )
    elif category is not None:
        cond = "EXISTS (SELECT 1 FROM needs n WHERE n.shelter_id = s.id AND n.category = ?"
        params.append(category)
        if subcategory is not None:
            cond += " AND n.subcategory = ?"
            params.append(subcategory)
        where.append(cond + ")")
    if urgency is not None:
        where.append("s.urgency_level = ?")
        params.append(urgency)
    if oblast is not None:
        where.append("s.oblast = ?")
        params.append(oblast)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        where.append(
            "(py_lower(s.name) LIKE ? OR py_lower(s.city) LIKE ? "
            "OR py_lower(COALESCE(s.district, '')) LIKE ? OR py_lower(s.address) LIKE ?)"
        )
        params += [like] * 4
    if bbox:
        min_lng, min_lat, max_lng, max_lat = _parse_floats(bbox, 4, "bbox")
        where.append("s.lat BETWEEN ? AND ? AND s.lng BETWEEN ? AND ?")
        params += [min_lat, max_lat, min_lng, max_lng]
    center = None
    if near:
        center = _parse_floats(near, 2, "near")
        lat0, lng0, lat1, lng1 = repo.bbox_around(*center, radius_km)
        where.append("s.lat BETWEEN ? AND ? AND s.lng BETWEEN ? AND ?")
        params += [lat0, lat1, lng0, lng1]
    elif sort == "distance":
        raise HTTPException(422, "sort=distance потребує параметра near")

    rows = conn.execute("SELECT * FROM shelters s WHERE " + " AND ".join(where), params).fetchall()
    dist = {}
    if center:
        dist = {r["id"]: repo.haversine_km(*center, r["lat"], r["lng"]) for r in rows}
        rows = [r for r in rows if dist[r["id"]] <= radius_km]

    if sort == "distance":
        rows.sort(key=lambda r: dist[r["id"]])
    elif sort == "urgency":
        rows.sort(key=lambda r: (URGENCY_ORDER[r["urgency_level"]], r["name"].lower()))
    else:
        rows.sort(key=lambda r: r["name"].lower())

    response.headers["X-Total-Count"] = str(len(rows))
    rows = rows[offset:offset + limit] if limit else rows[offset:]
    shelters = repo.assemble(conn, rows)
    for s in shelters:
        if s["id"] in dist:
            s["distance_km"] = round(dist[s["id"]], 1)
    return shelters


@router.get("/shelters/{shelter_id}", response_model=Shelter, tags=["read"])
def get_shelter(shelter_id: int, actor: Actor = Depends(get_actor), conn: sqlite3.Connection = Depends(get_db)):
    s = repo.get_shelter(conn, shelter_id)
    if s["status"] != "published" and not actor.can_manage(shelter_id):
        raise HTTPException(404, "Притулок не знайдено")
    return s


SHELTER_FIELDS = ["name", "urgency_level", "oblast", "city", "district", "address", "lat", "lng", "phone",
                  "contact_person", "source_url", "verified_at"]


def create_shelter_row(conn: sqlite3.Connection, body: ShelterIn, source: str, status: str = "published") -> int:
    data = body.model_dump()
    cols = SHELTER_FIELDS + ["source", "status"]
    values = [data[f] for f in SHELTER_FIELDS] + [source, status]
    sid = conn.execute(f"INSERT INTO shelters ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                       values).lastrowid
    for need in body.needs:
        repo.insert_need(conn, sid, need.category, need.subcategory, need.text)
    for link in body.links:
        repo.insert_link(conn, sid, link.kind, link.url)
    for f in body.fundraisers:
        repo.insert_fundraiser(conn, sid, f.title, f.kind, f.value, f.note)
    return sid


@router.post("/shelters", response_model=Shelter, status_code=201, tags=["admin"])
def create_shelter(body: ShelterIn, _: Actor = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    sid = create_shelter_row(conn, body, source="admin")
    return repo.get_shelter(conn, sid)


@router.patch("/shelters/{shelter_id}", response_model=Shelter, tags=["manage"])
def update_shelter(shelter_id: int, body: ShelterPatch, actor: Actor = Depends(get_actor),
                   conn: sqlite3.Connection = Depends(get_db)):
    before = repo.shelter_row(conn, shelter_id)
    check_manage(actor, shelter_id)
    data = body.model_dump(exclude_unset=True)
    if not actor.is_admin and {"status", "verified_at"} & data.keys():
        raise HTTPException(403, "status і verified_at змінює лише адміністратор")
    for required in ("name", "city", "address", "lat", "lng", "urgency_level", "status"):
        if required in data and data[required] is None:
            raise HTTPException(422, f"Поле {required} не може бути порожнім")
    if data:
        sets = ", ".join(f"{k} = ?" for k in data)
        conn.execute(f"UPDATE shelters SET {sets}, updated_at = datetime('now'), edited_at = datetime('now') "
                     "WHERE id = ?", [*data.values(), shelter_id])
    if data.get("urgency_level") == "red" and before["urgency_level"] != "red":
        notify.became_urgent(conn, shelter_id, exclude=actor.user["telegram_id"] if actor.user else None)
    return repo.get_shelter(conn, shelter_id)


@router.delete("/shelters/{shelter_id}", status_code=204, tags=["admin"])
def delete_shelter(shelter_id: int, _: Actor = Depends(require_admin), conn: sqlite3.Connection = Depends(get_db)):
    repo.shelter_row(conn, shelter_id)
    conn.execute("DELETE FROM shelters WHERE id = ?", (shelter_id,))
    return Response(status_code=204)


@router.post("/shelters/{shelter_id}/links", response_model=Link, status_code=201, tags=["manage"])
def add_link(shelter_id: int, body: LinkIn, actor: Actor = Depends(get_actor),
             conn: sqlite3.Connection = Depends(get_db)):
    repo.shelter_row(conn, shelter_id)
    check_manage(actor, shelter_id)
    if conn.execute("SELECT 1 FROM shelter_links WHERE shelter_id = ? AND url = ?", (shelter_id, body.url)).fetchone():
        raise HTTPException(409, "Таке посилання вже є")
    link_id = repo.insert_link(conn, shelter_id, body.kind, body.url)
    repo.touch(conn, shelter_id)
    return {"id": link_id, "kind": body.kind, "url": body.url}


@router.delete("/links/{link_id}", status_code=204, tags=["manage"])
def delete_link(link_id: int, actor: Actor = Depends(get_actor), conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT shelter_id FROM shelter_links WHERE id = ?", (link_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Посилання не знайдено")
    check_manage(actor, row["shelter_id"])
    conn.execute("DELETE FROM shelter_links WHERE id = ?", (link_id,))
    repo.touch(conn, row["shelter_id"])
    return Response(status_code=204)


@router.get("/shelters/{shelter_id}/fundraisers", response_model=list[Fundraiser], tags=["manage"])
def list_fundraisers(shelter_id: int, actor: Actor = Depends(get_actor), conn: sqlite3.Connection = Depends(get_db)):
    repo.shelter_row(conn, shelter_id)
    check_manage(actor, shelter_id)
    return repo.fundraisers_for(conn, [shelter_id], include_inactive=True)[shelter_id]


@router.post("/shelters/{shelter_id}/fundraisers", response_model=Fundraiser, status_code=201, tags=["manage"])
def add_fundraiser(shelter_id: int, body: FundraiserIn, actor: Actor = Depends(get_actor),
                   conn: sqlite3.Connection = Depends(get_db)):
    repo.shelter_row(conn, shelter_id)
    check_manage(actor, shelter_id)
    fid = repo.insert_fundraiser(conn, shelter_id, body.title, body.kind, body.value, body.note)
    repo.touch(conn, shelter_id)
    return {"id": fid, "title": body.title, "kind": body.kind, "value": body.value, "note": body.note, "active": True}


def _fundraiser(conn: sqlite3.Connection, fid: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM fundraisers WHERE id = ?", (fid,)).fetchone()
    if row is None:
        raise HTTPException(404, "Збір не знайдено")
    return row


@router.patch("/fundraisers/{fid}", response_model=Fundraiser, tags=["manage"])
def update_fundraiser(fid: int, body: FundraiserPatch, actor: Actor = Depends(get_actor),
                      conn: sqlite3.Connection = Depends(get_db)):
    row = _fundraiser(conn, fid)
    check_manage(actor, row["shelter_id"])
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k == "note" or v is not None}
    if data:
        conn.execute(f"UPDATE fundraisers SET {', '.join(f'{k} = ?' for k in data)} WHERE id = ?",
                     [*data.values(), fid])
        repo.touch(conn, row["shelter_id"])
    r = _fundraiser(conn, fid)
    return {"id": r["id"], "title": r["title"], "kind": r["kind"], "value": r["value"], "note": r["note"],
            "active": bool(r["active"])}


@router.delete("/fundraisers/{fid}", status_code=204, tags=["manage"])
def delete_fundraiser(fid: int, actor: Actor = Depends(get_actor), conn: sqlite3.Connection = Depends(get_db)):
    row = _fundraiser(conn, fid)
    check_manage(actor, row["shelter_id"])
    conn.execute("DELETE FROM fundraisers WHERE id = ?", (fid,))
    repo.touch(conn, row["shelter_id"])
    return Response(status_code=204)
