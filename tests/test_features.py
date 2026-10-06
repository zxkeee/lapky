"""Масштаб, соцмережі/збори, акаунти притулків, заявки, волонтерський функціонал."""
import json
from datetime import datetime, timedelta

from backend import config
from backend.db import connect, migrate
from backend.osm import import_items, parse_elements

from .conftest import ADMIN, ADMIN_TG, BOT, as_user, outbox

VOL, MGR, OTHER = 2001, 2002, 2003


def _future(hours: int = 48) -> str:
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")


def _make_manager(client, telegram_id: int, shelter_id: int) -> None:
    r = client.post("/api/applications", json={"kind": "claim", "shelter_id": shelter_id}, headers=as_user(telegram_id))
    assert r.status_code == 201, r.text
    assert client.post(f"/api/applications/{r.json()['id']}/approve", json={}, headers=ADMIN).status_code == 200


# ---------- міграції ----------

def test_migration_from_old_schema(tmp_path):
    """Стара база (лише 001) з social_links / requisites → дані переносяться в нові таблиці."""
    path = tmp_path / "old.db"
    conn = connect(path)
    conn.executescript((config.BASE_DIR / "backend/migrations/001_init.sql").read_text(encoding="utf-8"))
    conn.execute("INSERT INTO shelters (name, city, address, lat, lng, social_links, requisites, bank) "
                 "VALUES ('Старий', 'Київ', 'вул. 1', 50.4, 30.5, ?, 'UA12 3052 9900 0002 6006 0101 1038 5', 'Приват')",
                 (json.dumps(["https://instagram.com/x", "https://site.ua"]),))
    conn.commit()
    assert migrate(conn) == [1, 2, 3, 4, 5]
    assert migrate(conn) == []
    s = conn.execute("SELECT oblast, status, source FROM shelters").fetchone()
    assert tuple(s) == ("kyiv", "published", "seed")
    assert [tuple(r) for r in conn.execute("SELECT kind, url FROM shelter_links ORDER BY position")] == \
        [("instagram", "https://instagram.com/x"), ("website", "https://site.ua")]
    assert tuple(conn.execute("SELECT kind, value, note FROM fundraisers").fetchone()) == \
        ("iban", "UA123052990000026006010110385", "Приват")


# ---------- масштаб і геопошук ----------

def test_oblast_filter_and_counts(client):
    kyiv = client.get("/api/shelters?oblast=kyiv").json()
    assert kyiv and all(s["oblast"] == "kyiv" for s in kyiv)
    counts = {o["key"]: o["count"] for o in client.get("/api/oblasts").json()}
    assert counts["kyiv"] == len(kyiv) and counts["lvivska"] == 0
    assert client.get("/api/shelters?oblast=atlantis").status_code == 422


def test_near_sorted_by_distance(client):
    # центр Києва: найближчий — «Хатуль Мадан» (Володимирська, 82в)
    r = client.get("/api/shelters", params={"near": "50.45,30.52", "radius_km": 15, "sort": "distance"})
    res = r.json()
    assert res[0]["name"] == "Хатуль Мадан"
    d = [s["distance_km"] for s in res]
    assert d == sorted(d) and max(d) <= 15
    assert all(s["name"] != "Сіріус" for s in res)  # ~48 км, поза радіусом
    assert client.get("/api/shelters?sort=distance").status_code == 422


def test_bbox_and_pagination(client):
    total = len(client.get("/api/shelters").json())
    r = client.get("/api/shelters?limit=3&offset=2")
    assert len(r.json()) == 3 and r.headers["X-Total-Count"] == str(total)
    inside = client.get("/api/shelters", params={"bbox": "30.4,50.35,30.6,50.5"}).json()
    assert inside and all(30.4 <= s["lng"] <= 30.6 and 50.35 <= s["lat"] <= 50.5 for s in inside)


def test_hidden_not_public(client):
    client.patch("/api/shelters/1", json={"status": "hidden"}, headers=ADMIN)
    assert all(s["id"] != 1 for s in client.get("/api/shelters").json())
    assert client.get("/api/shelters/1").status_code == 404
    assert client.get("/api/shelters/1", headers=ADMIN).status_code == 200


# ---------- соцмережі та збори ----------

def test_links_and_fundraisers_from_seed(client):
    g = next(s for s in client.get("/api/shelters").json() if s["name"] == "Gostomel Shelter")
    assert {"website", "instagram"} <= {l["kind"] for l in g["links"]}
    assert g["fundraisers"][0]["kind"] == "monobank_jar"


def test_link_and_fundraiser_validation(client):
    r = client.post("/api/shelters/1/links", json={"url": "https://t.me/sos_shelter"}, headers=ADMIN)
    assert r.status_code == 201 and r.json()["kind"] == "telegram"
    assert client.post("/api/shelters/1/links", json={"url": "http://insecure.ua"}, headers=ADMIN).status_code == 422
    assert client.post("/api/shelters/1/links", json={"url": "https://t.me/sos_shelter"},
                       headers=ADMIN).status_code == 409

    jar = client.post("/api/shelters/1/fundraisers", headers=ADMIN,
                      json={"title": "На ліки", "value": "https://send.monobank.ua/jar/abc"}).json()
    assert jar["kind"] == "monobank_jar"
    iban = client.post("/api/shelters/1/fundraisers", headers=ADMIN,
                       json={"title": "Рахунок", "value": "UA21 3052 9900 0002 6007 2335 6600 1"})
    assert iban.status_code == 201 and iban.json()["value"] == "UA213052990000026007233566001"
    bad = client.post("/api/shelters/1/fundraisers", headers=ADMIN, json={"title": "x", "value": "UA123", "kind": "iban"})
    assert bad.status_code == 422

    client.patch(f"/api/fundraisers/{jar['id']}", json={"active": False}, headers=ADMIN)
    pub = client.get("/api/shelters/1").json()["fundraisers"]
    assert jar["id"] not in [f["id"] for f in pub]
    assert jar["id"] in [f["id"] for f in client.get("/api/shelters/1/fundraisers", headers=ADMIN).json()]


# ---------- ролі ----------

def test_bot_token_required(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"X-Bot-Token": "wrong", "X-Telegram-User-Id": "1"}).status_code == 403
    me = client.get("/api/me", headers=as_user(VOL)).json()
    assert me["role"] == "volunteer" and me["shelters"] == []
    assert client.get("/api/me", headers=as_user(ADMIN_TG)).json()["is_admin"] is True


def test_manager_edits_only_own_shelter(client):
    _make_manager(client, MGR, 1)
    h = as_user(MGR)
    assert client.patch("/api/shelters/1", json={"phone": "+380 00 000 00 00"}, headers=h).status_code == 200
    assert client.post("/api/shelters/1/needs", json={"category": "care", "text": "Повідці"}, headers=h).status_code == 201
    assert client.patch("/api/shelters/2", json={"phone": "1"}, headers=h).status_code == 403
    assert client.patch("/api/shelters/1", json={"status": "hidden"}, headers=h).status_code == 403
    assert client.patch("/api/shelters/1", json={"phone": "1"}, headers=as_user(VOL)).status_code == 403
    assert client.get("/api/me", headers=h).json()["shelters"][0]["id"] == 1


# ---------- заявки ----------

def test_new_shelter_application(client):
    payload = {"name": "Лапа Львова", "oblast": "lvivska", "city": "Львів", "address": "вул. Городоцька, 1",
               "lat": 49.84, "lng": 24.02, "links": [{"url": "https://instagram.com/lapa_lviv"}]}
    r = client.post("/api/applications", json={"kind": "new_shelter", "payload": payload}, headers=as_user(MGR))
    assert r.status_code == 201
    # адмін ще не писав боту → його немає в users, сповіщати нікого
    assert not any("Лапа Львова" in m["text"] for m in outbox(client))
    assert client.get("/api/applications", headers=as_user(VOL)).status_code == 403
    pending = client.get("/api/applications", headers=ADMIN).json()
    assert [a["payload"]["name"] for a in pending] == ["Лапа Львова"]

    res = client.post(f"/api/applications/{r.json()['id']}/approve", json={}, headers=ADMIN).json()
    s = client.get(f"/api/shelters/{res['shelter_id']}").json()
    assert s["oblast"] == "lvivska" and s["source"] == "application" and s["links"][0]["kind"] == "instagram"
    assert client.get("/api/me", headers=as_user(MGR)).json()["shelters"][0]["id"] == res["shelter_id"]
    assert any("схвалено" in m["text"] for m in outbox(client) if m["telegram_id"] == MGR)
    assert client.post(f"/api/applications/{r.json()['id']}/approve", json={}, headers=ADMIN).status_code == 409


def test_application_notifies_admins_and_reject(client):
    client.get("/api/me", headers=as_user(ADMIN_TG))  # адмін уже користувався ботом
    r = client.post("/api/applications", json={"kind": "claim", "shelter_id": 3, "comment": "Я директорка"},
                    headers=as_user(MGR))
    assert any(m["telegram_id"] == ADMIN_TG and "Сіріус" in m["text"] for m in outbox(client))
    assert client.post("/api/applications", json={"kind": "claim", "shelter_id": 3},
                       headers=as_user(MGR)).status_code == 409
    client.post(f"/api/applications/{r.json()['id']}/reject", json={"note": "Не підтверджено"},
                headers=as_user(ADMIN_TG))
    assert client.get("/api/me", headers=as_user(MGR)).json()["shelters"] == []
    assert any("відхилено" in m["text"] for m in outbox(client) if m["telegram_id"] == MGR)


# ---------- «Беру потребу» ----------

def test_pledge_flow(client):
    _make_manager(client, MGR, 1)
    client.post("/api/me", json={"username": "kind_volunteer"}, headers=as_user(VOL))
    need_id = client.get("/api/shelters/1").json()["needs"][0]["id"]
    r = client.post(f"/api/needs/{need_id}/pledges", json={"note": "Привезу в суботу"}, headers=as_user(VOL))
    assert r.status_code == 201
    assert client.post(f"/api/needs/{need_id}/pledges", json={}, headers=as_user(VOL)).status_code == 409
    need = next(n for n in client.get("/api/shelters/1").json()["needs"] if n["id"] == need_id)
    assert need["pledges_active"] == 1
    assert any(m["telegram_id"] == MGR and "@kind_volunteer" in m["text"] for m in outbox(client))
    assert client.get("/api/shelters/1/pledges", headers=as_user(MGR)).json()[0]["username"] == "kind_volunteer"
    assert client.get("/api/shelters/1/pledges", headers=as_user(VOL)).status_code == 403

    assert client.patch(f"/api/pledges/{r.json()['id']}", json={"status": "done"}, headers=as_user(OTHER)).status_code == 403
    assert client.patch(f"/api/pledges/{r.json()['id']}", json={"status": "done"}, headers=as_user(VOL)).status_code == 200
    assert client.get("/api/me/pledges", headers=as_user(VOL)).json() == []


# ---------- підписки та сповіщення ----------

def test_subscriptions_and_notifications(client):
    client.post("/api/me/subscriptions", json={"shelter_id": 2}, headers=as_user(VOL))
    client.post("/api/me/subscriptions", json={"oblast": "kyivska", "only_urgent": True}, headers=as_user(OTHER))
    assert client.post("/api/me/subscriptions", json={}, headers=as_user(VOL)).status_code == 422

    # Gostomel (orange) — нова потреба: підписник притулку отримує, «лише термінові» — ні
    client.post("/api/shelters/2/needs", json={"category": "care", "text": "Нашийники"}, headers=ADMIN)
    msgs = [m for m in outbox(client) if "Нашийники" in m["text"]]
    assert [m["telegram_id"] for m in msgs] == [VOL]

    # перехід у критичний рівень — отримують обидва
    client.patch("/api/shelters/2", json={"urgency_level": "red"}, headers=ADMIN)
    urgent = [m["telegram_id"] for m in outbox(client) if "критичний" in m["text"]]
    assert sorted(urgent) == [VOL, OTHER]

    # бот підтвердив доставку; заблокований користувач втрачає підписки
    pending = outbox(client)
    acks = [{"id": m["id"], "ok": m["telegram_id"] != OTHER, "blocked": m["telegram_id"] == OTHER} for m in pending]
    client.post("/api/internal/outbox/ack", json=acks, headers=BOT)
    assert outbox(client) == []
    assert client.get("/api/me/subscriptions", headers=as_user(OTHER)).json() == []
    assert len(client.get("/api/me/subscriptions", headers=as_user(VOL)).json()) == 1
    assert client.get("/api/internal/outbox", headers=as_user(VOL)).status_code == 200  # бот-токен є
    assert client.get("/api/internal/outbox").status_code == 401


# ---------- завдання ----------

def test_tasks_slots_and_reminders(client):
    _make_manager(client, MGR, 1)
    client.post("/api/me/subscriptions", json={"shelter_id": 1}, headers=as_user(OTHER))
    r = client.post("/api/shelters/1/tasks", headers=as_user(MGR),
                    json={"title": "Вигул собак", "starts_at": _future(10), "slots": 1})
    assert r.status_code == 201
    tid = r.json()["id"]
    assert any(m["telegram_id"] == OTHER and "Вигул собак" in m["text"] for m in outbox(client))
    assert client.post("/api/shelters/1/tasks", headers=as_user(VOL),
                       json={"title": "x", "starts_at": _future(), "slots": 1}).status_code == 403
    assert client.post("/api/shelters/1/tasks", headers=as_user(MGR),
                       json={"title": "x", "starts_at": "2020-01-01 10:00"}).status_code == 422

    assert client.post(f"/api/tasks/{tid}/signup", headers=as_user(VOL)).status_code == 201
    assert client.post(f"/api/tasks/{tid}/signup", headers=as_user(OTHER)).status_code == 409  # місць немає
    assert client.get("/api/shelters/1").json()["tasks"][0]["taken"] == 1
    assert client.get("/api/tasks", params={"near": "50.33,30.53"}).json()[0]["distance_km"] < 1
    assert client.get("/api/me/tasks", headers=as_user(VOL)).json()[0]["id"] == tid
    assert client.patch(f"/api/tasks/{tid}", json={"slots": 0}, headers=as_user(MGR)).status_code == 422

    res = client.post("/api/internal/remind", headers=BOT).json()
    assert res == {"tasks": 1, "messages": 1}
    assert client.post("/api/internal/remind", headers=BOT).json()["tasks"] == 0  # лише раз

    client.patch(f"/api/tasks/{tid}", json={"status": "closed"}, headers=as_user(MGR))
    assert client.get("/api/tasks").json() == []
    assert any(m["telegram_id"] == VOL and "скасовано або вже виконано" in m["text"] for m in outbox(client))


# ---------- імпорт з OSM ----------

OVERPASS_SAMPLE = {"elements": [
    {"type": "area", "id": 3600071950, "tags": {"ISO3166-2": "UA-46", "name": "Львівська область"}},
    {"type": "node", "id": 111, "lat": 49.80, "lon": 24.00,
     "tags": {"amenity": "animal_shelter", "name": "Дім Сірка", "addr:city": "Львів", "addr:street": "вул. Тиха",
              "addr:housenumber": "5", "website": "http://dimsirka.org", "contact:instagram": "dimsirka"}},
    {"type": "way", "id": 222, "center": {"lat": 49.9, "lon": 24.1}, "tags": {"amenity": "animal_shelter"}},
    # той самий «Дім Сірка» ще раз точкою без адреси — має злитися з повнішим записом
    {"type": "node", "id": 112, "lat": 49.8003, "lon": 24.0002, "tags": {"amenity": "animal_shelter", "name": "Дім Сірка"}},
    # центр для диких тварин — не беремо
    {"type": "node", "id": 444, "lat": 49.7, "lon": 23.9,
     "tags": {"amenity": "animal_shelter", "animal_shelter": "wildlife", "name": "Ведмежий притулок"}},
    {"type": "area", "id": 3600072639, "tags": {"ISO3166-2": "UA-43"}},  # окупований Крим — не беремо
    {"type": "node", "id": 555, "lat": 44.5, "lon": 34.1, "tags": {"amenity": "animal_shelter", "name": "Ковчег"}},
    {"type": "area", "id": 3600071248, "tags": {"ISO3166-2": "UA-32"}},
    {"type": "node", "id": 333, "lat": 50.8779, "lon": 30.2685,
     "tags": {"amenity": "animal_shelter", "name": "Притулок Сіріус"}},
]}


def test_osm_import_idempotent(client):
    items = parse_elements(OVERPASS_SAMPLE)
    assert [i["name"] for i in items] == ["Дім Сірка", "Притулок Сіріус"]  # без назви — пропущено
    assert items[0]["oblast"] == "lvivska" and items[0]["address"] == "вул. Тиха 5"
    assert items[0]["links"] == [("website", "https://dimsirka.org"), ("instagram", "https://instagram.com/dimsirka")]

    conn = connect()
    stats = import_items(conn, items)
    conn.commit()
    assert stats["new"] == 1 and stats["linked"] == 1  # «Сіріус» уже є з seed — лише зв'язуємо
    lviv = client.get("/api/shelters?oblast=lvivska").json()
    assert [s["name"] for s in lviv] == ["Дім Сірка"] and lviv[0]["source"] == "osm"

    # ручна правка не перезаписується повторним імпортом
    client.patch(f"/api/shelters/{lviv[0]['id']}", json={"name": "Дім Сірка (ГО)"}, headers=ADMIN)
    stats = import_items(conn, items)
    conn.commit()
    assert stats["new"] == 0 and stats["kept_manual"] == 2
    assert client.get(f"/api/shelters/{lviv[0]['id']}").json()["name"] == "Дім Сірка (ГО)"
    conn.close()


# ---------- імпорт з відкритих джерел ----------

def test_web_import_helpers():
    import sys
    sys.path.insert(0, str(config.BASE_DIR / "scripts"))
    from import_web import city_plain, clean, jitter

    assert city_plain("с. Піщане (Кременчуцький р-н)") == "Піщане"
    item = clean({"name": "Котики", "oblast": "kyiv", "city": "Київ", "links": ["instagram.com/kotyky", "http://x.ua"],
                  "fundraisers": [{"title": "Банка", "value": "https://send.monobank.ua/jar/abc"},
                                  {"title": "Картка?", "value": "UA1"}]})
    assert item["links"] == ["https://instagram.com/kotyky", "https://x.ua"]
    assert [f.kind for f in item["fundraisers"]] == ["monobank_jar", "other"]
    assert clean({"name": "Ковчег", "oblast": "crimea", "city": "Ялта"}) is None  # окуповано
    a, b = jitter(50.0, 30.0, "x"), jitter(50.0, 30.0, "x")
    assert a == b and abs(a[0] - 50) < 0.004 and abs(a[1] - 30) < 0.006
