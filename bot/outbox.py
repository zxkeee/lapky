"""Фонова доставка сповіщень: бот забирає чергу outbox із сервера й надсилає її в Telegram."""
import asyncio
import logging
import time

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .api import APIError, LapkyAPI

log = logging.getLogger("lapky.outbox")
POLL_SECONDS = 15
REMIND_SECONDS = 3600
SEND_PAUSE = 0.04  # ~25 повідомлень/с — у межах лімітів Telegram


def _markup(buttons: list[list[dict]]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(**b) for b in row] for row in buttons])


async def deliver_once(bot: Bot, api: LapkyAPI) -> int:
    messages = await api.outbox()
    results = []
    for msg in messages:
        try:
            await bot.send_message(msg["telegram_id"], msg["text"], reply_markup=_markup(msg["buttons"]),
                                   disable_web_page_preview=True)
            results.append({"id": msg["id"], "ok": True})
        except TelegramRetryAfter as e:
            log.warning("Ліміт Telegram, чекаю %s с", e.retry_after)
            await asyncio.sleep(e.retry_after)
            break  # решту заберемо наступного разу
        except TelegramForbiddenError as e:
            results.append({"id": msg["id"], "ok": False, "blocked": True, "error": str(e)})
        except Exception as e:  # noqa: BLE001 — одна погана розсилка не має зупиняти чергу
            results.append({"id": msg["id"], "ok": False, "error": str(e)})
        await asyncio.sleep(SEND_PAUSE)
    if results:
        await api.outbox_ack(results)
    return len(results)


async def run(bot: Bot, api: LapkyAPI) -> None:
    last_remind = 0.0
    while True:
        try:
            if time.monotonic() - last_remind > REMIND_SECONDS:
                await api.remind()
                last_remind = time.monotonic()
            sent = await deliver_once(bot, api)
            if sent:
                log.info("Надіслано сповіщень: %s", sent)
        except APIError as e:
            if e.status in (401, 403):
                log.error("Сервер відхилив BOT_API_TOKEN — сповіщення вимкнено. Перевірте .env (%s)", e.detail)
                return
            log.warning("Outbox: %s", e.detail)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("Outbox: неочікувана помилка")
        await asyncio.sleep(POLL_SECONDS)
