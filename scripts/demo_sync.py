import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
API = os.getenv("API_URL", "http://127.0.0.1:8000")
HEAD = {"X-Admin-Token": os.getenv("ADMIN_TOKEN", "change-me-please")}
TEXT = "ДЕМО: потрібні 10 теплих ковдр до п'ятниці"
SHELTER_ID = int(os.getenv("DEMO_SHELTER_ID", "1"))

with httpx.Client(base_url=API, timeout=10) as c:
    s = c.get(f"/api/shelters/{SHELTER_ID}").json()
    demo = [n for n in s["needs"] if n["text"] == TEXT]
    if "--undo" in sys.argv:
        for n in demo:
            c.delete(f"/api/needs/{n['id']}", headers=HEAD).raise_for_status()
        print(f"Прибрано демо-потреб: {len(demo)}")
    elif demo:
        print("Демо-потреба вже додана.")
    else:
        r = c.post(f"/api/shelters/{SHELTER_ID}/needs", headers=HEAD, json={"category": "housing", "text": TEXT})
        r.raise_for_status()
        print(f"Додано до «{s['name']}». Оновіть карту (або зачекайте хвилину) і відкрийте картку в боті.")
