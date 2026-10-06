"""Соцмережі та збори окремими таблицями; переносимо дані зі старих social_links / requisites."""
import json
import sqlite3

from backend.links import detect_fundraiser_kind, detect_link_kind, normalize_requisites

DDL = """
CREATE TABLE IF NOT EXISTS shelter_links (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    shelter_id INTEGER NOT NULL REFERENCES shelters(id) ON DELETE CASCADE,
    kind       TEXT    NOT NULL,           -- website / facebook / instagram / telegram / tiktok / youtube / viber / other
    url        TEXT    NOT NULL,
    position   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_links_shelter ON shelter_links(shelter_id);

CREATE TABLE IF NOT EXISTS fundraisers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    shelter_id INTEGER NOT NULL REFERENCES shelters(id) ON DELETE CASCADE,
    title      TEXT    NOT NULL,
    kind       TEXT    NOT NULL,           -- monobank_jar / privat / paypal / patreon / iban / card / other
    value      TEXT    NOT NULL,           -- посилання або реквізити
    note       TEXT,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fundraisers_shelter ON fundraisers(shelter_id, active);
"""


def migrate(conn: sqlite3.Connection) -> None:
    for stmt in DDL.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    rows = conn.execute("SELECT id, social_links, requisites, bank FROM shelters").fetchall()
    for r in rows:
        for pos, url in enumerate(json.loads(r["social_links"] or "[]")):
            conn.execute("INSERT INTO shelter_links (shelter_id, kind, url, position) VALUES (?, ?, ?, ?)",
                         (r["id"], detect_link_kind(url), url, pos))
        if r["requisites"]:
            value = normalize_requisites(r["requisites"])
            kind = detect_fundraiser_kind(value)
            title = "Банка на корм" if kind == "monobank_jar" else "Реквізити притулку"
            conn.execute("INSERT INTO fundraisers (shelter_id, title, kind, value, note) VALUES (?, ?, ?, ?, ?)",
                         (r["id"], title, kind, value, r["bank"]))
