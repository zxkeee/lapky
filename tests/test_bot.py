"""Бот без Telegram: клієнт API (через ASGI), картки й клавіатури, доставка черги сповіщень."""
import asyncio

import httpx
import pytest

from backend.main import app
from bot import outbox, ui
from bot.api import APIError, LapkyAPI
from bot.config import Settings

from .conftest import ADMIN, BOT_TOKEN, as_user

SETTINGS = Settings(bot_token="x", api_url="http://test", web_url="https://lapky.example", coordinator_email="a@b.c")


def _api() -> LapkyAPI:
    return LapkyAPI("http://test", BOT_TOKEN, transport=httpx.ASGITransport(app=app))


def _all_callbacks(kb) -> list[str]:
    return [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]


def test_cards_and_keyboards_render(client):
    async def run():
        api = _api()
        meta = await api.meta()
        shelters = await api.shelters()
        for ctx in ("all", "food.sterilized@ivano-frankivska", "near"):
            text, kb = ui.list_view(shelters, ctx, 0, meta, SETTINGS)
            assert text and all(len(cb.encode()) <= 64 for cb in _all_callbacks(kb))
        for s in shelters:
            assert s["name"] in ui.shelter_card(s, meta)
            kb = ui.card_kb(s, "food.sterilized@ivano-frankivska", 12, SETTINGS, subscribed=True)
            assert all(len(cb.encode()) <= 64 for cb in _all_callbacks(kb))
        counts = {o["key"]: o["count"] for o in await api.oblasts()}
        picker = ui.oblast_picker(meta, counts, "os:food.sterilized:", "cat")
        assert all(len(cb.encode()) <= 64 for cb in _all_callbacks(picker))
        g = next(s for s in shelters if s["name"] == "Gostomel Shelter")
        assert "send.monobank.ua" in ui.shelter_card(g, meta)
        assert any(b.url and "monobank" in b.url for row in ui.card_kb(g, "all", 0, SETTINGS).inline_keyboard
                   for b in row)
        await api.close()
    asyncio.run(run())


def test_user_actions_via_client(client):
    async def run():
        api = _api()
        need = (await api.shelter(1))["needs"][0]
        await api.pledge(555, need["id"])
        assert (await api.my_pledges(555))[0]["need_id"] == need["id"]
        with pytest.raises(APIError) as e:
            await api.pledge(555, need["id"])
        assert e.value.status == 409 and "вже" in e.value.detail
        with pytest.raises(APIError) as e:
            await api.add_fundraiser(555, 1, "x", "UA1")  # не менеджер
        assert e.value.status == 403
        await api.close()
    asyncio.run(run())


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None, **_):
        if chat_id == 666:
            from aiogram.exceptions import TelegramForbiddenError
            raise TelegramForbiddenError(method=None, message="bot was blocked by the user")
        self.sent.append((chat_id, text, reply_markup))


def test_outbox_delivery(client):
    client.post("/api/me/subscriptions", json={"shelter_id": 1}, headers=as_user(777))
    client.post("/api/me/subscriptions", json={"shelter_id": 1}, headers=as_user(666))
    client.post("/api/shelters/1/needs", json={"category": "care", "text": "Іграшки"}, headers=ADMIN)

    async def run():
        api, bot = _api(), FakeBot()
        outbox.SEND_PAUSE = 0
        assert await outbox.deliver_once(bot, api) == 2
        assert [m[0] for m in bot.sent] == [777]
        assert bot.sent[0][2].inline_keyboard[0][0].callback_data == "sh:1:all:0"
        assert await outbox.deliver_once(bot, api) == 0  # усе підтверджено
        await api.close()
    asyncio.run(run())
    assert client.get("/api/me/subscriptions", headers=as_user(666)).json() == []
