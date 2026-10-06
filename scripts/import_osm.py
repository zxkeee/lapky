import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config
from backend.constants import OBLASTS
from backend.db import connect, init_db
from backend.osm import (
    OVERPASS_URLS, apply_reverse_geocode, import_items, overpass_query, parse_elements,
)

NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
HEADERS = {"User-Agent": "lapky-shelters-import/1.0"}


def fetch(iso: str | None, refresh: bool) -> dict:
    cache = config.DB_PATH.parent / (f"osm_cache_{iso}.json" if iso else "osm_cache.json")
    if cache.exists() and not refresh:
        print(f"Беру кеш {cache.name} (оновити: --refresh)")
        return json.loads(cache.read_text(encoding="utf-8"))
    data, errors = None, []
    for url in OVERPASS_URLS:
        print(f"Запит до {url} … (може тривати 1–3 хвилини)")
        try:
            r = httpx.post(url, data={"data": overpass_query(iso)}, timeout=360,
                           headers={"User-Agent": "lapky-shelters-import/1.0"})
            r.raise_for_status()
            data = r.json()
            break
        except (httpx.HTTPError, ValueError) as e:
            errors.append(f"{url}: {e}")
            print(f"  не вдалося: {e}")
    if data is None:
        raise SystemExit("Усі сервери Overpass недоступні, спробуйте пізніше:\n" + "\n".join(errors))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def geocode(items: list[dict]) -> int:
    cache_path = config.DB_PATH.parent / "geocode_cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    todo = [it for it in items if it["needs_geocode"]]
    if todo:
        print(f"Уточнюю адреси через Nominatim: {len(todo)} шт. (~{len(todo)} с)")
    for it in todo:
        if it["osm_id"] not in cache:
            try:
                r = httpx.get(NOMINATIM_REVERSE, headers=HEADERS, timeout=20, params={
                    "lat": it["lat"], "lon": it["lng"], "format": "jsonv2", "zoom": 18, "accept-language": "uk"})
                r.raise_for_status()
                cache[it["osm_id"]] = r.json().get("address", {})
            except httpx.HTTPError as e:
                print(f"  {it['name']}: {e}")
                continue
            time.sleep(1.1)
        apply_reverse_geocode(it, cache[it["osm_id"]])
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return len(todo)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--oblast", choices=[o["key"] for o in OBLASTS])
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--no-geocode", action="store_true")
    args = ap.parse_args()

    iso = next(o["iso"] for o in OBLASTS if o["key"] == args.oblast) if args.oblast else None
    items = parse_elements(fetch(iso, args.refresh))
    print(f"Знайдено в OSM: {len(items)} притулків для домашніх тварин")
    if not args.no_geocode:
        geocode(items)

    init_db()
    conn = connect()
    try:
        stats = import_items(conn, items, dry_run=args.dry_run, prune=args.oblast is None)
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    finally:
        conn.close()

    titles = {o["key"]: o["title"] for o in OBLASTS}
    print("\nПо областях:")
    for key, n in sorted(((k[7:], v) for k, v in stats.items() if k.startswith("oblast:")), key=lambda x: -x[1]):
        print(f"  {titles.get(key, key):<20} {n}")
    print(f"\nНових: {stats['new']}, оновлено: {stats['updated']}, зв'язано з наявними: {stats['linked']}, "
          f"не чіпали (не з OSM або правлені вручну): {stats['kept_manual']}, приховано застарілих: {stats['hidden']}" + ("  [DRY RUN — нічого не записано]" if args.dry_run else ""))


if __name__ == "__main__":
    main()
