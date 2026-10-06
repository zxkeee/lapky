"""Перевірка контракту API (для Богдана).  Запуск:  pytest -q"""
from .conftest import ADMIN


def test_meta(client):
    m = client.get("/api/meta").json()
    assert [u["key"] for u in m["urgency"]] == ["red", "orange", "white", "green"]
    assert len(m["categories"]) == 5
    assert {"oblasts", "link_kinds", "fundraiser_kinds"} <= m.keys()


def test_sorted_by_urgency(client):
    order = {"red": 0, "orange": 1, "white": 2, "green": 3}
    levels = [order[s["urgency_level"]] for s in client.get("/api/shelters").json()]
    from backend.seed import SHELTERS
    assert levels == sorted(levels) and len(levels) == len(SHELTERS)


def test_filter_category_and_sub(client):
    kids = client.get("/api/shelters?subcategory=kids").json()
    assert kids and all(any(n["subcategory"] == "kids" for n in s["needs"]) for s in kids)
    vol = client.get("/api/shelters?category=volunteer").json()
    assert all(any(n["category"] == "volunteer" for n in s["needs"]) for s in vol)
    fin = client.get("/api/shelters?category=finance").json()
    assert fin and all(s["fundraisers"] or any(n["category"] == "finance" for n in s["needs"]) for s in fin)
    assert client.get("/api/shelters?category=care&subcategory=kids").status_code == 422


def test_search_cyrillic_case_insensitive(client):
    res = client.get("/api/shelters", params={"q": "СІРІУС"}).json()
    assert [s["name"] for s in res] == ["Сіріус"]


def test_404(client):
    assert client.get("/api/shelters/9999").status_code == 404


def test_admin_requires_token(client):
    assert client.patch("/api/shelters/1", json={"urgency_level": "green"}).status_code == 401
    assert client.patch("/api/shelters/1", json={"urgency_level": "green"},
                        headers={"X-Admin-Token": "wrong"}).status_code == 403


def test_need_change_visible_everywhere(client):
    """Тиждень 7: змінили потребу в базі → карта й бот бачать те саме (обидва читають /api/shelters)."""
    r = client.post("/api/shelters/1/needs", json={"category": "food", "subcategory": "kids",
                                                   "text": "Тестова суміш"}, headers=ADMIN)
    assert r.status_code == 201
    need_id = r.json()["id"]
    s = client.get("/api/shelters/1").json()
    assert any(n["text"] == "Тестова суміш" for n in s["needs"])
    client.patch(f"/api/needs/{need_id}", json={"text": "Оновлено"}, headers=ADMIN)
    assert any(n["text"] == "Оновлено" for n in client.get("/api/shelters/1").json()["needs"])
    client.delete(f"/api/needs/{need_id}", headers=ADMIN)
    assert not any(n["id"] == need_id for n in client.get("/api/shelters/1").json()["needs"])


def test_sub_only_for_food(client):
    r = client.post("/api/shelters/1/needs", json={"category": "care", "subcategory": "kids", "text": "x"},
                    headers=ADMIN)
    assert r.status_code == 422


def test_create_and_delete_shelter(client):
    body = {"name": "Новий", "city": "Київ", "address": "вул. Тестова, 1", "lat": 50.4, "lng": 30.5,
            "needs": [{"category": "care", "text": "Іграшки"}]}
    r = client.post("/api/shelters", json=body, headers=ADMIN)
    assert r.status_code == 201 and r.json()["needs"][0]["text"] == "Іграшки"
    sid = r.json()["id"]
    assert client.delete(f"/api/shelters/{sid}", headers=ADMIN).status_code == 204
    assert client.get(f"/api/shelters/{sid}").status_code == 404


def test_web_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Лапки" in r.text
