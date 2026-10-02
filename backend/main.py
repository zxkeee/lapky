"""«Лапки» — спільний сервер для вебкарти й Telegram-бота.

Запуск:  uvicorn backend.main:app --reload
Документація API (Swagger): http://127.0.0.1:8000/docs
"""
import json
import secrets
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .constants import CATEGORIES, CATEGORY_ORDER, URGENCY, URGENCY_ORDER
from .db import get_db, init_db
from .models import (
    CategoryKey, Need, NeedIn, NeedPatch, Shelter, ShelterIn, ShelterPatch,
    SubcategoryKey, Urgency, check_sub,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Лапки API",
    version="1.0.0",
    description="Єдине джерело даних про притулки для вебкарти й Telegram-бота.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- допоміжне ----------

def require_admin(x_admin_token: str = Header(..., description="Токен адміністратора з .env")):
    if not secrets.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Невірний X-Admin-Token")


def _needs_for(conn: sqlite3.Connection, shelter_ids: list[int]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {sid: [] for sid in shelter_ids}
    if not shelter_ids:
        return result
    marks = ",".join("?" * len(shelter_ids))
    rows = conn.execute(
        f"SELECT * FROM needs WHERE shelter_id IN ({marks}) ORDER BY id", shelter_ids
    ).fetchall()
    for r in rows:
        result[r["shelter_id"]].append({
            "id": r["id"], "category": r["category"], "subcategory": r["subcategory"],
            "text": r["text"], "updated_at": r["updated_at"],
        })
    for needs in result.values():
        needs.sort(key=lambda n: CATEGORY_ORDER[n["category"]])
    return result


def _row_to_dict(row: sqlite3.Row, needs: list[dict]) -> dict:
    d = dict(row)
    d["social_links"] = json.loads(d.get("social_links") or "[]")
    d["needs"] = needs
    d.pop("created_at", None)
    return d


def _get_shelter(conn: sqlite3.Connection, shelter_id: int) -> dict:
    row = conn.execute("SELECT * FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Притулок не знайдено")
    return _row_to_dict(row, _needs_for(conn, [shelter_id])[shelter_id])


def _touch(conn: sqlite3.Connection, shelter_id: int) -> None:
    conn.execute("UPDATE shelters SET updated_at = datetime('now') WHERE id = ?", (shelter_id,))


def _insert_need(conn: sqlite3.Connection, shelter_id: int, need: NeedIn) -> int:
    cur = conn.execute(
        "INSERT INTO needs (shelter_id, category, subcategory, text) VALUES (?, ?, ?, ?)",
        (shelter_id, need.category, need.subcategory, need.text.strip()),
    )
    return cur.lastrowid


# ---------- читання (карта і бот) ----------

@app.get("/api/health", tags=["service"])
def health():
    return {"status": "ok"}


@app.get("/api/meta", tags=["read"])
def meta():
    """Довідники: рівні терміновості та категорії потреб (з кольорами й емодзі)."""
    return {
        "urgency": URGENCY,
        "categories": CATEGORIES,
        "bot_url": f"https://t.me/{config.BOT_USERNAME}" if config.BOT_USERNAME else None,
    }


@app.get("/api/shelters", response_model=list[Shelter], tags=["read"])
def list_shelters(
    category: Optional[CategoryKey] = None,
    subcategory: Optional[SubcategoryKey] = None,
    urgency: Optional[Urgency] = None,
    q: Optional[str] = Query(None, max_length=100, description="Пошук за назвою, містом, районом, адресою"),
    sort: Literal["urgency", "name"] = "urgency",
    conn: sqlite3.Connection = Depends(get_db),
):
    if subcategory is not None:
        if category not in (None, "food"):
            raise HTTPException(422, "subcategory дозволена лише разом із category=food")
        category = "food"

    where, params = [], []
    if category == "finance":
        # фінансову допомогу показуємо, якщо є реквізити або окремий збір
        where.append(
            "((s.requisites IS NOT NULL AND s.requisites <> '') OR EXISTS "
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
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        where.append(
            "(py_lower(s.name) LIKE ? OR py_lower(s.city) LIKE ? "
            "OR py_lower(COALESCE(s.district, '')) LIKE ? OR py_lower(s.address) LIKE ?)"
        )
        params += [like] * 4

    sql = "SELECT * FROM shelters s"
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = conn.execute(sql, params).fetchall()

    needs = _needs_for(conn, [r["id"] for r in rows])
    shelters = [_row_to_dict(r, needs[r["id"]]) for r in rows]
    if sort == "urgency":
        shelters.sort(key=lambda s: (URGENCY_ORDER[s["urgency_level"]], s["name"].lower()))
    else:
        shelters.sort(key=lambda s: s["name"].lower())
    return shelters


@app.get("/api/shelters/{shelter_id}", response_model=Shelter, tags=["read"])
def get_shelter(shelter_id: int, conn: sqlite3.Connection = Depends(get_db)):
    return _get_shelter(conn, shelter_id)


# ---------- зміна даних (адмін, потрібен X-Admin-Token) ----------

SHELTER_FIELDS = [
    "name", "urgency_level", "city", "district", "address", "lat", "lng", "phone",
    "contact_person", "social_links", "requisites", "bank", "source_url", "verified_at",
]


@app.post("/api/shelters", response_model=Shelter, status_code=201,
          tags=["admin"], dependencies=[Depends(require_admin)])
def create_shelter(body: ShelterIn, conn: sqlite3.Connection = Depends(get_db)):
    data = body.model_dump(exclude={"needs"})
    data["social_links"] = json.dumps(data["social_links"], ensure_ascii=False)
    cols = ", ".join(SHELTER_FIELDS)
    marks = ", ".join("?" * len(SHELTER_FIELDS))
    cur = conn.execute(f"INSERT INTO shelters ({cols}) VALUES ({marks})",
                       [data[f] for f in SHELTER_FIELDS])
    for need in body.needs:
        _insert_need(conn, cur.lastrowid, need)
    return _get_shelter(conn, cur.lastrowid)


@app.patch("/api/shelters/{shelter_id}", response_model=Shelter,
           tags=["admin"], dependencies=[Depends(require_admin)])
def update_shelter(shelter_id: int, body: ShelterPatch, conn: sqlite3.Connection = Depends(get_db)):
    _get_shelter(conn, shelter_id)  # 404, якщо нема
    data = body.model_dump(exclude_unset=True)
    for required in ("name", "city", "address", "lat", "lng", "urgency_level"):
        if required in data and data[required] is None:
            raise HTTPException(422, f"Поле {required} не може бути порожнім")
    if "social_links" in data:
        data["social_links"] = json.dumps(data["social_links"] or [], ensure_ascii=False)
    if data:
        sets = ", ".join(f"{k} = ?" for k in data)
        conn.execute(f"UPDATE shelters SET {sets}, updated_at = datetime('now') WHERE id = ?",
                     [*data.values(), shelter_id])
    return _get_shelter(conn, shelter_id)


@app.delete("/api/shelters/{shelter_id}", status_code=204,
            tags=["admin"], dependencies=[Depends(require_admin)])
def delete_shelter(shelter_id: int, conn: sqlite3.Connection = Depends(get_db)):
    _get_shelter(conn, shelter_id)
    conn.execute("DELETE FROM shelters WHERE id = ?", (shelter_id,))
    return Response(status_code=204)


@app.post("/api/shelters/{shelter_id}/needs", response_model=Need, status_code=201,
          tags=["admin"], dependencies=[Depends(require_admin)])
def add_need(shelter_id: int, body: NeedIn, conn: sqlite3.Connection = Depends(get_db)):
    _get_shelter(conn, shelter_id)
    need_id = _insert_need(conn, shelter_id, body)
    _touch(conn, shelter_id)
    return dict(conn.execute("SELECT * FROM needs WHERE id = ?", (need_id,)).fetchone())


@app.patch("/api/needs/{need_id}", response_model=Need,
           tags=["admin"], dependencies=[Depends(require_admin)])
def update_need(need_id: int, body: NeedPatch, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT * FROM needs WHERE id = ?", (need_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Потребу не знайдено")
    merged = {**dict(row), **body.model_dump(exclude_unset=True)}
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
    _touch(conn, row["shelter_id"])
    return dict(conn.execute("SELECT * FROM needs WHERE id = ?", (need_id,)).fetchone())


@app.delete("/api/needs/{need_id}", status_code=204,
            tags=["admin"], dependencies=[Depends(require_admin)])
def delete_need(need_id: int, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT shelter_id FROM needs WHERE id = ?", (need_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Потребу не знайдено")
    conn.execute("DELETE FROM needs WHERE id = ?", (need_id,))
    _touch(conn, row["shelter_id"])
    return Response(status_code=204)


# ---------- вебкарта (статичні файли, монтується останньою) ----------
app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")
