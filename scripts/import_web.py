import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config
from backend.constants import OBLAST_KEYS, OBLAST_TITLE, OCCUPIED_OBLASTS
from backend.db import connect, init_db
from backend.links import detect_link_kind, normalize_url
from backend.models import FundraiserIn
from backend.repo import haversine_km, insert_fundraiser, insert_link

NOMINATIM = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "lapky-shelters-import/1.0"}
UA_BOX = (44.0, 22.0, 52.5, 40.3)


def norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("ʼ", "'")
    for w in ("притулок", "для тварин", "для собак", "для котів", "го ", "благодійний фонд", "бф ", "shelter"):
        s = s.replace(w, "")
    return re.sub(r"[^\w]+", "", s)


def city_plain(city: str) -> str:
    city = re.sub(r"\(.*?\)", "", city).strip()
    return re.sub(r"^(м\.|с\.|смт|сел\.|с-ще|село|місто)\s*", "", city, flags=re.I)


class Geocoder:
    def __init__(self):
        self.path = config.DB_PATH.parent / "geocode_web.json"
        self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def _q(self, q: str) -> tuple[float, float] | None:
        if q not in self.cache:
            try:
                r = httpx.get(NOMINATIM, headers=HEADERS, timeout=20,
                              params={"q": q, "format": "json", "limit": 1, "countrycodes": "ua", "accept-language": "uk"})
                r.raise_for_status()
                res = r.json()
                self.cache[q] = [float(res[0]["lat"]), float(res[0]["lon"])] if res else None
            except httpx.HTTPError as e:
                print(f"  геокодування «{q}»: {e}")
                return None
            time.sleep(1.1)
        return tuple(self.cache[q]) if self.cache[q] else None

    def locate(self, item: dict) -> tuple[float, float, bool] | None:
        region = OBLAST_TITLE[item["oblast"]] + ("" if item["oblast"] == "kyiv" else " область")
        city = city_plain(item["city"])
        if item.get("address"):
            addr = re.sub(r"\(.*?\)", "", item["address"]).strip()
            hit = self._q(f"{addr}, {city}, {region}")
            if hit:
                return (*hit, True)
        inner = re.search(r"\((.*?)\)", item["city"])
        if inner and not re.search(r"околиц|р-н|район", inner.group(1)):
            hit = self._q(f"{inner.group(1)}, {city}, {region}")
            if hit:
                return (*hit, False)
        hit = self._q(f"{city}, {region}")
        return (*hit, False) if hit else None

    def save(self):
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")


def jitter(lat: float, lng: float, key: str) -> tuple[float, float]:
    h = hashlib.md5(key.encode()).digest()
    return lat + (h[0] / 255 - .5) * 0.007, lng + (h[1] / 255 - .5) * 0.011


def find_existing(conn, item: dict, lat: float, lng: float):
    key = norm(item["name"])
    if not key:
        return None
    for r in conn.execute("SELECT * FROM shelters WHERE oblast = ?", (item["oblast"],)):
        other = norm(r["name"])
        if not other or not (key in other or other in key):
            continue
        same_city = norm(city_plain(r["city"])) == norm(city_plain(item["city"]))
        if same_city or haversine_km(lat, lng, r["lat"], r["lng"]) < 1:
            return r
    return None


def clean(item: dict) -> dict | None:
    if not item.get("name") or item.get("oblast") not in OBLAST_KEYS or item["oblast"] in OCCUPIED_OBLASTS:
        return None
    links = []
    for raw in item.get("links") or []:
        url = normalize_url(raw)
        if url and url not in links:
            links.append(url)
    funds = []
    for f in item.get("fundraisers") or []:
        try:
            funds.append(FundraiserIn(title=f.get("title") or "Підтримати притулок", value=f["value"]))
        except (ValueError, KeyError):
            pass
    return {
        "name": item["name"].strip()[:200], "oblast": item["oblast"], "city": item["city"].strip()[:100],
        "address": (item.get("address") or "").strip()[:300] or None, "phone": (item.get("phone") or None),
        "links": links[:10], "fundraisers": funds[:5],
        "source_url": item.get("source_url") if (item.get("source_url") or "").startswith("http") else None,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    raw = json.loads(args.file.read_text(encoding="utf-8"))
    items = [c for c in (clean(i) for i in raw) if c]
    print(f"У файлі {len(raw)} записів, придатних: {len(items)}")

    init_db()
    conn, geo, stats = connect(), Geocoder(), Counter()
    try:
        for it in items:
            loc = geo.locate(it)
            if loc is None or not (UA_BOX[0] <= loc[0] <= UA_BOX[2] and UA_BOX[1] <= loc[1] <= UA_BOX[3]):
                stats["no_location"] += 1
                print(f"  ✗ не знайдено на карті: {it['name']} ({it['city']})")
                continue
            lat, lng, exact = loc
            if not exact:
                lat, lng = jitter(lat, lng, it["name"] + it["city"])
                stats["approx"] += 1
            existing = find_existing(conn, it, lat, lng)
            if existing is not None and (existing["source"] != "web" or existing["edited_at"]):
                stats["duplicate"] += 1
                print(f"  = вже є: {it['name']} ↔ {existing['name']}")
                continue
            address = it["address"] or "адресу уточнюйте"
            district = None if exact else "точне місце уточнюйте"
            if existing is not None:
                sid = existing["id"]
                conn.execute("""UPDATE shelters SET name = ?, city = ?, district = ?, address = ?, lat = ?, lng = ?,
                                phone = ?, source_url = ?, status = 'published', updated_at = datetime('now')
                                WHERE id = ?""",
                             (it["name"], it["city"], district, address, lat, lng, it["phone"], it["source_url"], sid))
                conn.execute("DELETE FROM shelter_links WHERE shelter_id = ?", (sid,))
                conn.execute("DELETE FROM fundraisers WHERE shelter_id = ?", (sid,))
                stats["updated"] += 1
            else:
                sid = conn.execute(
                    """INSERT INTO shelters (name, urgency_level, oblast, city, district, address, lat, lng, phone,
                                             source_url, source, status)
                       VALUES (?, 'white', ?, ?, ?, ?, ?, ?, ?, ?, 'web', 'published')""",
                    (it["name"], it["oblast"], it["city"], district, address, lat, lng, it["phone"], it["source_url"]),
                ).lastrowid
                stats["new"] += 1
            for url in it["links"]:
                insert_link(conn, sid, detect_link_kind(url), url)
            for f in it["fundraisers"]:
                insert_fundraiser(conn, sid, f.title, f.kind, f.value, f.note)
            stats[f"oblast:{it['oblast']}"] += 1
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        geo.save()
        conn.close()

    print("\nПо областях:")
    for key, n in sorted(((k[7:], v) for k, v in stats.items() if k.startswith("oblast:")), key=lambda x: -x[1]):
        print(f"  {OBLAST_TITLE[key]:<20} {n}")
    print(f"\nНових: {stats['new']}, оновлено: {stats['updated']}, дублікатів: {stats['duplicate']}, "
          f"приблизне місце: {stats['approx']}, не знайдено на карті: {stats['no_location']}"
          + ("  [DRY RUN — нічого не записано]" if args.dry_run else ""))


if __name__ == "__main__":
    main()
