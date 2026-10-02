"""Клієнт до спільного сервера. Бот НЕ має власної бази — лише читає API."""
import time
from typing import Any, Optional

import httpx


class APIError(Exception):
    pass


class LapkyAPI:
    META_TTL = 300  # секунд

    def __init__(self, base_url: str):
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=10)
        self._meta: Optional[dict] = None
        self._meta_at = 0.0

    async def _get(self, path: str, **params) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        try:
            r = await self._client.get(path, params=params)
        except httpx.HTTPError as e:
            raise APIError(f"Сервер недоступний: {e}") from e
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise APIError(f"{r.status_code}: {r.text[:200]}")
        return r.json()

    async def meta(self) -> dict:
        if self._meta is None or time.monotonic() - self._meta_at > self.META_TTL:
            self._meta = await self._get("/api/meta")
            self._meta_at = time.monotonic()
        return self._meta

    async def shelters(self, category: str | None = None, subcategory: str | None = None,
                       sort: str = "urgency") -> list[dict]:
        return await self._get("/api/shelters", category=category, subcategory=subcategory, sort=sort) or []

    async def shelter(self, shelter_id: int) -> Optional[dict]:
        return await self._get(f"/api/shelters/{shelter_id}")

    async def close(self) -> None:
        await self._client.aclose()
