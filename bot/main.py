"""Telegram-бот «Лапки».   Запуск:  python -m bot.main"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardMarkup, Message

from . import texts, ui
from .api import APIError, LapkyAPI
from .config import Settings, load_settings

router = Router()
log = logging.getLogger("lapky.bot")


async def edit(c: CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    """Редагує повідомлення з кнопками; якщо не можна — надсилає нове."""
    try:
        await c.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            await c.message.answer(text, reply_markup=kb, disable_web_page_preview=True)


# ---------- старт і головне меню ----------

@router.message(CommandStart())
async def cmd_start(m: Message):
    await m.answer(texts.ONBOARDING, reply_markup=ui.onboarding_kb())


@router.callback_query(F.data == "ok")
async def cb_ok(c: CallbackQuery):
    try:
        await c.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await c.message.answer(texts.MAIN_MENU, reply_markup=ui.main_menu())
    await c.answer()


@router.message(Command("menu"))
async def cmd_menu(m: Message):
    await m.answer(texts.MAIN_MENU, reply_markup=ui.main_menu())


@router.callback_query(F.data == "menu")
async def cb_menu(c: CallbackQuery):
    await c.message.answer(texts.MAIN_MENU, reply_markup=ui.main_menu())
    await c.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await c.answer()


# ---------- 1. Усі притулки ----------

@router.message(F.text == texts.BTN_ALL)
@router.message(Command("all"))
async def msg_all(m: Message, api: LapkyAPI, settings: Settings):
    try:
        meta, shelters = await api.meta(), await api.shelters(sort="urgency")
    except APIError:
        await m.answer(texts.SERVER_DOWN)
        return
    text, kb = ui.list_view(shelters, "all", 0, meta, settings)
    await m.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data.startswith("list:"))
async def cb_list(c: CallbackQuery, api: LapkyAPI, settings: Settings):
    _, ctx, page = c.data.split(":")
    cat, sub = ui.parse_ctx(ctx)
    # «Усі притулки» — за терміновістю; фільтр — без сортування за терміновістю (за назвою)
    sort = "urgency" if ctx == "all" else "name"
    try:
        meta, shelters = await api.meta(), await api.shelters(cat, sub, sort)
    except APIError:
        await c.answer(texts.SERVER_DOWN, show_alert=True)
        return
    text, kb = ui.list_view(shelters, ctx, int(page), meta, settings)
    await edit(c, text, kb)
    await c.answer()


# ---------- 2. Фільтр за потребами ----------

@router.message(F.text == texts.BTN_FILTER)
@router.message(Command("filter"))
async def msg_filter(m: Message, api: LapkyAPI):
    try:
        meta = await api.meta()
    except APIError:
        await m.answer(texts.SERVER_DOWN)
        return
    await m.answer(texts.FILTER_INTRO, reply_markup=ui.categories_kb(meta))


@router.callback_query(F.data == "cat")
async def cb_categories(c: CallbackQuery, api: LapkyAPI):
    try:
        meta = await api.meta()
    except APIError:
        await c.answer(texts.SERVER_DOWN, show_alert=True)
        return
    await edit(c, texts.FILTER_INTRO, ui.categories_kb(meta))
    await c.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(c: CallbackQuery, api: LapkyAPI, settings: Settings):
    key = c.data.split(":", 1)[1]
    try:
        meta = await api.meta()
        if key == "food":
            await edit(c, texts.FOOD_INTRO, ui.food_kb(meta))
        else:
            shelters = await api.shelters(key, None, "name")
            text, kb = ui.list_view(shelters, key, 0, meta, settings)
            await edit(c, text, kb)
    except APIError:
        await c.answer(texts.SERVER_DOWN, show_alert=True)
        return
    await c.answer()


# ---------- картка притулку ----------

@router.callback_query(F.data.startswith("sh:"))
async def cb_shelter(c: CallbackQuery, api: LapkyAPI, settings: Settings):
    _, sid, ctx, page = c.data.split(":")
    try:
        meta, s = await api.meta(), await api.shelter(int(sid))
    except APIError:
        await c.answer(texts.SERVER_DOWN, show_alert=True)
        return
    if s is None:
        await c.answer(texts.NOT_FOUND, show_alert=True)
        return
    await edit(c, ui.shelter_card(s, meta), ui.card_kb(s, ctx, int(page), settings))
    await c.answer()


@router.callback_query(F.data.startswith("contact:"))
async def cb_contact(c: CallbackQuery, api: LapkyAPI):
    try:
        s = await api.shelter(int(c.data.split(":")[1]))
    except APIError:
        await c.answer(texts.SERVER_DOWN, show_alert=True)
        return
    if s is None:
        await c.answer(texts.NOT_FOUND, show_alert=True)
        return
    await c.message.answer(ui.contacts_text(s), disable_web_page_preview=True)
    await c.answer()


# ---------- 3. Як допомогти, 4. Про проєкт ----------

@router.message(F.text == texts.BTN_HELP)
@router.message(Command("help"))
async def msg_help(m: Message):
    await m.answer(texts.HOW_TO_HELP, reply_markup=ui.help_kb())


@router.message(F.text == texts.BTN_ABOUT)
@router.message(Command("about"))
async def msg_about(m: Message, settings: Settings):
    await m.answer(texts.about(settings.web_url, settings.coordinator_email),
                   reply_markup=ui.about_kb(settings), disable_web_page_preview=True)


@router.callback_query(F.data == "add")
async def cb_add(c: CallbackQuery, settings: Settings):
    await c.message.answer(texts.add_shelter(settings.coordinator_email))
    await c.answer()


@router.message()
async def fallback(m: Message):
    await m.answer(texts.UNKNOWN, reply_markup=ui.main_menu())


# ---------- запуск ----------

async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = load_settings()
    api = LapkyAPI(settings.api_url)
    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(api=api, settings=settings)
    dp.include_router(router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Почати / привітання"),
        BotCommand(command="menu", description="Головне меню"),
        BotCommand(command="all", description="Усі притулки"),
        BotCommand(command="filter", description="Фільтр за потребами"),
        BotCommand(command="help", description="Як допомогти"),
        BotCommand(command="about", description="Про проєкт"),
    ])
    log.info("Бот запущено. API: %s, карта: %s", settings.api_url, settings.web_url)
    try:
        await dp.start_polling(bot)
    finally:
        await api.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
