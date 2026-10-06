"""Імпорт притулків для тварин з OpenStreetMap (Overpass API).

Область визначається контуром OSM (admin_level=4, ISO 3166-2), тож геокодування не потрібне.
Записи, які вже відредагували вручну (edited_at), імпорт не перезаписує.
"""
import re
import sqlite3
from collections import Counter

from .constants import OBLAST_BY_ISO, OBLAST_TITLE, OCCUPIED_OBLASTS
from .links import detect_link_kind, normalize_url
from .repo import haversine_km, insert_link

# основний сервер і дзеркала (основний часто перевантажений і віддає 504)
ROAD_REF_RE = re.compile(r"^[А-ЯA-Z]{1,2}-?\d")
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def overpass_query(iso: str | None = None) -> str:
    region = f'["ISO3166-2"="{iso}"]' if iso else '["ISO3166-2"~"^UA-"]'
    return f"""[out:json][timeout:300];
area["ISO3166-1"="UA"][admin_level=2]->.ua;
rel(area.ua)[admin_level=4]{region};
map_to_area->.regions;
foreach.regions->.r(
  .r out tags;
  nwr(area.r)[amenity=animal_shelter];
  out center tags;
);"""


LINK_TAGS = [
    ("website", None), ("contact:website", None), ("url", None),
    ("contact:facebook", "facebook"), ("facebook", "facebook"),
    ("contact:instagram", "instagram"), ("instagram", "instagram"),
    ("contact:telegram", "telegram"), ("telegram", "telegram"),
    ("contact:youtube", "youtube"), ("contact:tiktok", "tiktok"), ("contact:viber", "viber"),
]


def is_wildlife(tags: dict) -> bool:
    """Центри для диких тварин (ведмеді тощо) — не про корм і вигул, на карту не беремо."""
    kinds = {k for k in (tags.get("animal_shelter") or "").split(";") if k}
    if kinds and kinds <= {"wildlife", "bear", "horse", "bird"}:
        return True
    return "ведмед" in (tags.get("name") or "").lower()


def parse_elements(data: dict) -> list[dict]:
    """Відповідь Overpass → список притулків з областю (елементи area задають поточну область)."""
    out, seen, oblast = [], set(), None
    for el in data.get("elements", []):
        if el["type"] == "area":
            oblast = OBLAST_BY_ISO.get(el.get("tags", {}).get("ISO3166-2"))
            continue
        osm_id = f"{el['type']}/{el['id']}"
        if osm_id in seen:
            continue  # точка на межі може потрапити у дві області
        seen.add(osm_id)
        tags = el.get("tags", {})
        name = (tags.get("name:uk") or tags.get("name") or "").strip()
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lng = el.get("lon", el.get("center", {}).get("lon"))
        if not name or lat is None or lng is None or is_wildlife(tags) or oblast in OCCUPIED_OBLASTS:
            continue
        city = (tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village")
                or tags.get("addr:place") or tags.get("addr:hamlet") or "")
        has_city = bool(city)
        if not city and oblast:
            city = OBLAST_TITLE[oblast] + ("" if oblast in ("kyiv", "sevastopol", "crimea") else " обл.")
        street = " ".join(x for x in (tags.get("addr:street"), tags.get("addr:housenumber")) if x)
        has_street = bool(tags.get("addr:street") or tags.get("addr:full"))
        address = tags.get("addr:full") or street or "адресу уточнюйте"
        links, urls = [], set()
        for tag, hint in LINK_TAGS:
            for raw in (tags.get(tag) or "").split(";"):
                url = normalize_url(raw, hint)
                if url and url not in urls:
                    urls.add(url)
                    links.append((detect_link_kind(url), url))
        out.append({
            "osm_id": osm_id, "oblast": oblast, "name": name[:200], "city": city[:100] or "—",
            "address": address[:300], "lat": float(lat), "lng": float(lng),
            "phone": tags.get("phone") or tags.get("contact:phone"),
            "source_url": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
            "links": links[:10],
            "needs_geocode": not (has_city and has_street),
            "has_street": has_street,
            "housenumber": tags.get("addr:housenumber"),
        })
    return _dedupe(out)


def _score(item: dict) -> int:
    return (not item["needs_geocode"]) * 8 + item["has_street"] * 4 + bool(item["phone"]) * 2 + len(item["links"])


def _dedupe(items: list[dict]) -> list[dict]:
    """Один притулок буває в OSM двічі (точка + контур): лишаємо найповніший запис."""
    kept: list[dict] = []
    for it in sorted(items, key=_score, reverse=True):
        key = _norm_name(it["name"])
        if any(_norm_name(k["name"]) == key and haversine_km(it["lat"], it["lng"], k["lat"], k["lng"]) < 0.5
               for k in kept):
            continue
        kept.append(it)
    order = {it["osm_id"]: i for i, it in enumerate(items)}
    return sorted(kept, key=lambda it: order[it["osm_id"]])


def apply_reverse_geocode(item: dict, address: dict) -> None:
    """Доповнює місто й вулицю з відповіді Nominatim reverse (поле address)."""
    city = (address.get("city") or address.get("town") or address.get("village")
            or address.get("hamlet") or address.get("municipality"))
    if city and (item["city"].endswith(" обл.") or item["city"] in ("—", "АР Крим", "м. Севастополь")):
        item["city"] = city[:100]
    if item["address"] == "адресу уточнюйте" or item["address"] == (item.get("housenumber") or ""):
        road = address.get("road") or address.get("pedestrian")
        if road and ROAD_REF_RE.match(road):  # «С140104», «Т-10-01» — номер дороги, а не вулиця
            road = None
        road = road or address.get("suburb") or address.get("neighbourhood")
        number = item.get("housenumber") or address.get("house_number")
        if road:
            item["address"] = " ".join(x for x in (road, number) if x)[:300]


def _norm_name(s: str) -> str:
    return re.sub(r"[^\w]+", "", s.lower().replace("притулок", "").replace("shelter", ""))


def _find_twin(conn: sqlite3.Connection, item: dict) -> sqlite3.Row | None:
    """Притулок, доданий вручну раніше, що збігається з OSM-записом (до 500 м і схожа назва)."""
    d = 0.006
    rows = conn.execute("SELECT * FROM shelters WHERE osm_id IS NULL AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
                        (item["lat"] - d, item["lat"] + d, item["lng"] - d * 1.6, item["lng"] + d * 1.6)).fetchall()
    a = _norm_name(item["name"])
    for r in rows:
        b = _norm_name(r["name"])
        if haversine_km(item["lat"], item["lng"], r["lat"], r["lng"]) <= 0.5 and a and b and (a in b or b in a):
            return r
    return None


def import_items(conn: sqlite3.Connection, items: list[dict], dry_run: bool = False,
                 prune: bool = False) -> Counter:
    """prune=True (повний імпорт по країні): OSM-записи, яких більше немає у вибірці, приховуємо."""
    stats: Counter = Counter()
    if prune:
        current = {it["osm_id"] for it in items}
        for r in conn.execute("SELECT id, osm_id FROM shelters WHERE source = 'osm' AND status = 'published' "
                              "AND edited_at IS NULL").fetchall():
            if r["osm_id"] not in current:
                stats["hidden"] += 1
                if not dry_run:
                    conn.execute("UPDATE shelters SET status = 'hidden', updated_at = datetime('now') WHERE id = ?",
                                 (r["id"],))
    for it in items:
        stats[f"oblast:{it['oblast'] or '?'}"] += 1
        row = conn.execute("SELECT * FROM shelters WHERE osm_id = ?", (it["osm_id"],)).fetchone()
        if row is None:
            twin = _find_twin(conn, it)
            if twin is not None:
                stats["linked"] += 1
                if not dry_run:
                    conn.execute("UPDATE shelters SET osm_id = ? WHERE id = ?", (it["osm_id"], twin["id"]))
                continue
            stats["new"] += 1
            if dry_run:
                continue
            sid = conn.execute(
                """INSERT INTO shelters (name, urgency_level, oblast, city, address, lat, lng, phone, source_url,
                                         source, status, osm_id)
                   VALUES (?, 'white', ?, ?, ?, ?, ?, ?, ?, 'osm', 'published', ?)""",
                (it["name"], it["oblast"], it["city"], it["address"], it["lat"], it["lng"], it["phone"],
                 it["source_url"], it["osm_id"])).lastrowid
            for kind, url in it["links"]:
                insert_link(conn, sid, kind, url)
        elif row["source"] == "osm" and row["edited_at"] is None:
            stats["updated"] += 1
            if dry_run:
                continue
            conn.execute(
                """UPDATE shelters SET name = ?, oblast = ?, city = ?, address = ?, lat = ?, lng = ?, phone = ?,
                   source_url = ?, status = 'published', updated_at = datetime('now') WHERE id = ?""",
                (it["name"], it["oblast"], it["city"], it["address"], it["lat"], it["lng"], it["phone"],
                 it["source_url"], row["id"]))
            conn.execute("DELETE FROM shelter_links WHERE shelter_id = ?", (row["id"],))
            for kind, url in it["links"]:
                insert_link(conn, row["id"], kind, url)
        else:
            stats["kept_manual"] += 1
    return stats
