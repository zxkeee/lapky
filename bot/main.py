import asyncio
import contextlib
import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, Message, TelegramObject

from . import outbox, texts, ui
from .api import APIError, LapkyAPI
from .config import load_settings
from .handlers import apply, browse, manage, moderate, volunteer

log = logging.getLogger("lapky.bot")
fallback = Router(name="fallback")


@fallback.message()
async def on_unknown(m: Message):
    await m.answer(texts.UNKNOWN, reply_markup=ui.main_menu())


class UserSync(BaseMiddleware):
    TTL = 3600

    def __init__(self, api: LapkyAPI, enabled: bool):
        self.api, self.enabled = api, enabled
        self._seen: dict[int, float] = {}

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if self.enabled and user and time.monotonic() - self._seen.get(user.id, -self.TTL) >= self.TTL:
            self._seen[user.id] = time.monotonic()
            with contextlib.suppress(APIError):
                await self.api.update_me(user.id, user.username, user.first_name)
        return await handler(event, data)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    api = LapkyAPI(settings.api_url, settings.bot_api_token)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage(), api=api, settings=settings)
    dp.update.outer_middleware(UserSync(api, enabled=bool(settings.bot_api_token)))
    for r in (browse.router, apply.router, manage.router, moderate.router, volunteer.router, fallback):
        dp.include_router(r)

    await bot.set_my_commands([
        BotCommand(command="start", description="Почати / привітання"),
        BotCommand(command="menu", description="Головне меню"),
        BotCommand(command="all", description="Усі притулки"),
        BotCommand(command="filter", description="Фільтр за потребами й областю"),
        BotCommand(command="mine", description="Мої обіцянки, завдання, підписки"),
        BotCommand(command="my", description="Кабінет мого притулку"),
        BotCommand(command="apply", description="Додати притулок"),
        BotCommand(command="help", description="Як допомогти"),
        BotCommand(command="about", description="Про проєкт"),
        BotCommand(command="cancel", description="Скасувати поточну дію"),
    ])
    if not settings.bot_api_token:
        log.warning("BOT_API_TOKEN не задано: працює лише перегляд; «беру», підписки, завдання, кабінет "
                    "притулку й сповіщення вимкнені.")
    log.info("Бот запущено. API: %s, карта: %s", settings.api_url, settings.web_url)
    notifier = asyncio.create_task(outbox.run(bot, api)) if settings.bot_api_token else None
    try:
        await dp.start_polling(bot)
    finally:
        if notifier:
            notifier.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await notifier
        await api.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
