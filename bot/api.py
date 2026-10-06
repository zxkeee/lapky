import time
from typing import Any, Optional

import httpx


class APIError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status
        self.detail = message


class LapkyAPI:
    META_TTL = 300

    def __init__(self, base_url: str, bot_token: str = "", transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=10, transport=transport)
        self._bot_token = bot_token
        self._meta: Optional[dict] = None
        self._meta_at = 0.0

    def _headers(self, uid: Optional[int], bot: bool = False) -> dict:
        h = {}
        if (uid is not None or bot) and self._bot_token:
            h["X-Bot-Token"] = self._bot_token
        if uid is not None:
            h["X-Telegram-User-Id"] = str(uid)
        return h

    async def _req(self, method: str, path: str, uid: Optional[int] = None, *, bot: bool = False,
                   json: Any = None, params: Optional[dict] = None, none_on_404: bool = False) -> Any:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            r = await self._client.request(method, path, params=params, json=json, headers=self._headers(uid, bot))
        except httpx.HTTPError as e:
            raise APIError(f"Сервер недоступний: {e}") from e
        if r.status_code == 404 and none_on_404:
            return None
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
                if isinstance(detail, list):
                    detail = "; ".join(str(d.get("msg", d)).removeprefix("Value error, ") for d in detail)
            except ValueError:
                detail = r.text[:200]
            raise APIError(str(detail or r.status_code), r.status_code)
        return r.json() if r.content else None


    async def meta(self) -> dict:
        if self._meta is None or time.monotonic() - self._meta_at > self.META_TTL:
            self._meta = await self._req("GET", "/api/meta")
            self._meta_at = time.monotonic()
        return self._meta

    async def oblasts(self) -> list[dict]:
        return await self._req("GET", "/api/oblasts")

    async def shelters(self, category: str | None = None, subcategory: str | None = None, sort: str = "urgency",
                       oblast: str | None = None, near: tuple[float, float] | None = None,
                       radius_km: float | None = None) -> list[dict]:
        return await self._req("GET", "/api/shelters", params={
            "category": category, "subcategory": subcategory, "sort": sort, "oblast": oblast,
            "near": f"{near[0]},{near[1]}" if near else None, "radius_km": radius_km}) or []

    async def shelter(self, shelter_id: int, uid: Optional[int] = None) -> Optional[dict]:
        return await self._req("GET", f"/api/shelters/{shelter_id}", uid, none_on_404=True)

    async def tasks(self, near: tuple[float, float] | None = None, oblast: str | None = None,
                    shelter_id: int | None = None, radius_km: float | None = None) -> list[dict]:
        return await self._req("GET", "/api/tasks", params={
            "near": f"{near[0]},{near[1]}" if near else None, "oblast": oblast,
            "shelter_id": shelter_id, "radius_km": radius_km}) or []

    async def task(self, task_id: int) -> Optional[dict]:
        return await self._req("GET", f"/api/tasks/{task_id}", none_on_404=True)


    async def me(self, uid: int) -> dict:
        return await self._req("GET", "/api/me", uid)

    async def update_me(self, uid: int, username: str | None, first_name: str | None) -> dict:
        return await self._req("POST", "/api/me", uid, json={"username": username, "first_name": first_name})

    async def my_pledges(self, uid: int) -> list[dict]:
        return await self._req("GET", "/api/me/pledges", uid)

    async def pledge(self, uid: int, need_id: int, note: str | None = None) -> dict:
        return await self._req("POST", f"/api/needs/{need_id}/pledges", uid, json={"note": note})

    async def update_pledge(self, uid: int, pledge_id: int, status: str) -> dict:
        return await self._req("PATCH", f"/api/pledges/{pledge_id}", uid, json={"status": status})

    async def subscriptions(self, uid: int) -> list[dict]:
        return await self._req("GET", "/api/me/subscriptions", uid)

    async def subscribe(self, uid: int, shelter_id: int | None = None, oblast: str | None = None,
                        only_urgent: bool = False) -> list[dict]:
        return await self._req("POST", "/api/me/subscriptions", uid,
                               json={"shelter_id": shelter_id, "oblast": oblast, "only_urgent": only_urgent})

    async def unsubscribe(self, uid: int, sub_id: int) -> None:
        await self._req("DELETE", f"/api/me/subscriptions/{sub_id}", uid)

    async def signup(self, uid: int, task_id: int) -> dict:
        return await self._req("POST", f"/api/tasks/{task_id}/signup", uid)

    async def cancel_signup(self, uid: int, task_id: int) -> None:
        await self._req("DELETE", f"/api/tasks/{task_id}/signup", uid)

    async def my_tasks(self, uid: int) -> list[dict]:
        return await self._req("GET", "/api/me/tasks", uid)


    async def apply(self, uid: int, body: dict) -> dict:
        return await self._req("POST", "/api/applications", uid, json=body)

    async def applications(self, uid: int) -> list[dict]:
        return await self._req("GET", "/api/applications", uid)

    async def approve(self, uid: int, app_id: int) -> dict:
        return await self._req("POST", f"/api/applications/{app_id}/approve", uid, json={})

    async def reject(self, uid: int, app_id: int, note: str | None = None) -> dict:
        return await self._req("POST", f"/api/applications/{app_id}/reject", uid, json={"note": note})


    async def patch_shelter(self, uid: int, shelter_id: int, data: dict) -> dict:
        return await self._req("PATCH", f"/api/shelters/{shelter_id}", uid, json=data)

    async def add_need(self, uid: int, shelter_id: int, category: str, subcategory: str | None, text: str) -> dict:
        return await self._req("POST", f"/api/shelters/{shelter_id}/needs", uid,
                               json={"category": category, "subcategory": subcategory, "text": text})

    async def delete_need(self, uid: int, need_id: int) -> None:
        await self._req("DELETE", f"/api/needs/{need_id}", uid)

    async def add_link(self, uid: int, shelter_id: int, url: str) -> dict:
        return await self._req("POST", f"/api/shelters/{shelter_id}/links", uid, json={"url": url})

    async def delete_link(self, uid: int, link_id: int) -> None:
        await self._req("DELETE", f"/api/links/{link_id}", uid)

    async def fundraisers(self, uid: int, shelter_id: int) -> list[dict]:
        return await self._req("GET", f"/api/shelters/{shelter_id}/fundraisers", uid)

    async def add_fundraiser(self, uid: int, shelter_id: int, title: str, value: str) -> dict:
        return await self._req("POST", f"/api/shelters/{shelter_id}/fundraisers", uid,
                               json={"title": title, "value": value})

    async def patch_fundraiser(self, uid: int, fid: int, data: dict) -> dict:
        return await self._req("PATCH", f"/api/fundraisers/{fid}", uid, json=data)

    async def delete_fundraiser(self, uid: int, fid: int) -> None:
        await self._req("DELETE", f"/api/fundraisers/{fid}", uid)

    async def create_task(self, uid: int, shelter_id: int, body: dict) -> dict:
        return await self._req("POST", f"/api/shelters/{shelter_id}/tasks", uid, json=body)

    async def patch_task(self, uid: int, task_id: int, data: dict) -> dict:
        return await self._req("PATCH", f"/api/tasks/{task_id}", uid, json=data)

    async def task_signups(self, uid: int, task_id: int) -> list[dict]:
        return await self._req("GET", f"/api/tasks/{task_id}/signups", uid)

    async def shelter_pledges(self, uid: int, shelter_id: int) -> list[dict]:
        return await self._req("GET", f"/api/shelters/{shelter_id}/pledges", uid)


    async def outbox(self, limit: int = 50) -> list[dict]:
        return await self._req("GET", "/api/internal/outbox", bot=True, params={"limit": limit})

    async def outbox_ack(self, results: list[dict]) -> None:
        await self._req("POST", "/api/internal/outbox/ack", bot=True, json=results)

    async def remind(self) -> dict:
        return await self._req("POST", "/api/internal/remind", bot=True)

    async def close(self) -> None:
        await self._client.aclose()
