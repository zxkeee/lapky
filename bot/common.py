"""Спільне для хендлерів: редагування повідомлень, помилки API, показ картки, остання геолокація."""
import time
from math import asin, cos, radians, sin, sqrt

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from . import texts, ui
from .api import APIError, LapkyAPI
from .config import Settings

# остання геолокація користувача — лише в пам'яті бота, для списку «поруч» (живе 1 год)
_locations: dict[int, tuple[float, float, float]] = {}
LOCATION_TTL = 3600


def remember_location(uid: int, lat: float, lng: float) -> None:
    _locations[uid] = (lat, lng, time.monotonic())


def last_location(uid: int) -> tuple[float, float] | None:
    loc = _locations.get(uid)
    if loc and time.monotonic() - loc[2] < LOCATION_TTL:
        return loc[0], loc[1]
    return None


async def edit(c: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """Редагує повідомлення з кнопками; якщо не можна — надсилає нове."""
    try:
        await c.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await c.message.answer(text, reply_markup=kb, disable_web_page_preview=True)


def error_text(e: APIError) -> str:
    if e.status == 0 or e.status >= 500:
        return texts.SERVER_DOWN
    if e.status == 401 or (e.status == 403 and "X-Bot-Token" in e.detail):
        return texts.NEED_USER_FEATURES
    return f"⚠️ {e.detail}"


async def fail(event: CallbackQuery | Message, e: APIError) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer(error_text(e)[:200], show_alert=True)
    else:
        await event.answer(error_text(e))


async def card_markup(api: LapkyAPI, settings: Settings, s: dict, uid: int, ctx: str, page: int):
    subscribed, manages = False, False
    try:
        subs = await api.subscriptions(uid)
        subscribed = any(x["shelter_id"] == s["id"] for x in subs)
        me = await api.me(uid)
        manages = me["is_admin"] or any(x["id"] == s["id"] for x in me["shelters"])
    except APIError:
        pass  # без BOT_API_TOKEN картка все одно показується, лише без персональних кнопок
    return ui.card_kb(s, ctx, page, settings, subscribed=subscribed, manages=manages)


async def show_card(event: CallbackQuery | Message, api: LapkyAPI, settings: Settings, shelter_id: int,
                    ctx: str = "all", page: int = 0) -> None:
    uid = event.from_user.id
    try:
        meta, s = await api.meta(), await api.shelter(shelter_id, uid)
    except APIError as e:
        await fail(event, e)
        return
    if s is None:
        if isinstance(event, CallbackQuery):
            await event.answer(texts.NOT_FOUND, show_alert=True)
        else:
            await event.answer(texts.NOT_FOUND)
        return
    loc = last_location(uid)
    if loc and ctx == "near":
        dlat, dlng = radians(s["lat"] - loc[0]), radians(s["lng"] - loc[1])
        a = sin(dlat / 2) ** 2 + cos(radians(loc[0])) * cos(radians(s["lat"])) * sin(dlng / 2) ** 2
        s["distance_km"] = 2 * 6371 * asin(sqrt(a))
    kb = await card_markup(api, settings, s, uid, ctx, page)
    text = ui.shelter_card(s, meta)
    if isinstance(event, CallbackQuery):
        await edit(event, text, kb)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb, disable_web_page_preview=True)
