"""Перегляд: старт і меню, усі притулки, фільтр за потребами й областю, картка, «поруч зі мною»."""
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import texts, ui
from ..api import APIError, LapkyAPI
from ..common import edit, fail, last_location, remember_location, show_card
from ..config import Settings

router = Router(name="browse")
NEAR_RADIUS_KM = (30, 100, 300)  # якщо поруч нічого — розширюємо пошук


# ---------- старт, deep-link і головне меню ----------

@router.message(CommandStart(deep_link=True))
async def cmd_start_deep(m: Message, command: CommandObject, state: FSMContext, api: LapkyAPI, settings: Settings):
    """Посилання з вебкарти: t.me/<bot>?start=shelter_7 | pledge_12 | task_5 | apply."""
    await state.clear()
    kind, _, raw = (command.args or "").partition("_")
    if kind == "shelter" and raw.isdigit():
        await m.answer(texts.MAIN_MENU, reply_markup=ui.main_menu())
        await show_card(m, api, settings, int(raw))
    elif kind == "pledge" and raw.isdigit():
        from .volunteer import ask_pledge
        await ask_pledge(m, api, int(raw))
    elif kind == "task" and raw.isdigit():
        from .volunteer import show_task
        await show_task(m, api, int(raw))
    elif kind == "claim" and raw.isdigit():
        from .apply import ask_claim
        await ask_claim(m, int(raw))
    elif kind == "apply":
        from .apply import start_apply
        await start_apply(m, state)
    else:
        await m.answer(texts.ONBOARDING, reply_markup=ui.onboarding_kb())


@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    await state.clear()
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
@router.message(Command("cancel"))
async def cmd_menu(m: Message, state: FSMContext):
    was_busy = await state.get_state() is not None
    await state.clear()
    await m.answer(texts.CANCELLED if was_busy else texts.MAIN_MENU, reply_markup=ui.main_menu())


@router.callback_query(F.data == "menu")
async def cb_menu(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.answer(texts.MAIN_MENU, reply_markup=ui.main_menu())
    await c.answer()


@router.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await c.answer()


# ---------- списки ----------

async def load_list(api: LapkyAPI, ctx: str, uid: int) -> list[dict] | None:
    cat, sub, oblast = ui.parse_ctx(ctx)
    if cat == "near":
        loc = last_location(uid)
        if loc is None:
            return None
        for radius in NEAR_RADIUS_KM:
            found = await api.shelters(sort="distance", near=loc, radius_km=radius)
            if found:
                return found
        return []
    # «Усі притулки» — за терміновістю; фільтр — за назвою
    return await api.shelters(cat, sub, "urgency" if cat is None else "name", oblast=oblast)


@router.message(F.text == texts.BTN_ALL)
@router.message(Command("all"))
async def msg_all(m: Message, state: FSMContext, api: LapkyAPI, settings: Settings):
    await state.clear()
    try:
        meta, shelters = await api.meta(), await api.shelters(sort="urgency")
    except APIError as e:
        await fail(m, e)
        return
    text, kb = ui.list_view(shelters, "all", 0, meta, settings)
    await m.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data.startswith("list:"))
async def cb_list(c: CallbackQuery, api: LapkyAPI, settings: Settings):
    _, ctx, page = c.data.split(":")
    try:
        meta, shelters = await api.meta(), await load_list(api, ctx, c.from_user.id)
    except APIError as e:
        await fail(c, e)
        return
    if shelters is None:
        await c.message.answer(texts.NEAR_ASK, reply_markup=ui.main_menu())
        await c.answer()
        return
    text, kb = ui.list_view(shelters, ctx, int(page), meta, settings)
    await edit(c, text, kb)
    await c.answer()


# ---------- вибір області ----------

@router.callback_query(F.data.startswith("op:"))
async def cb_oblast_picker(c: CallbackQuery, api: LapkyAPI):
    ctx = c.data[3:]
    what = ctx.partition("@")[0]
    back = ("cat" + ctx[len(what):]) if what == "cat" else f"list:{ctx}:0"
    try:
        meta, counts = await api.meta(), {o["key"]: o["count"] for o in await api.oblasts()}
    except APIError as e:
        await fail(c, e)
        return
    await edit(c, "📍 <b>Оберіть область</b> (у дужках — кількість притулків):",
               ui.oblast_picker(meta, counts, f"os:{what}:", back))
    await c.answer()


@router.callback_query(F.data.startswith("os:"))
async def cb_oblast_set(c: CallbackQuery, api: LapkyAPI, settings: Settings):
    _, what, oblast = c.data.split(":", 2)
    oblast = oblast or None
    try:
        meta = await api.meta()
        if what == "cat":
            await edit(c, texts.FILTER_INTRO, ui.categories_kb(meta, oblast))
        else:
            ctx = what + (f"@{oblast}" if oblast else "")
            shelters = await load_list(api, ctx, c.from_user.id)
            text, kb = ui.list_view(shelters or [], ctx, 0, meta, settings)
            await edit(c, text, kb)
    except APIError as e:
        await fail(c, e)
        return
    await c.answer()


# ---------- фільтр за потребами ----------

@router.message(F.text == texts.BTN_FILTER)
@router.message(Command("filter"))
async def msg_filter(m: Message, state: FSMContext, api: LapkyAPI):
    await state.clear()
    try:
        meta = await api.meta()
    except APIError as e:
        await fail(m, e)
        return
    await m.answer(texts.FILTER_INTRO, reply_markup=ui.categories_kb(meta))


@router.callback_query(F.data.regexp(r"^cat(@[\w-]+)?$"))
async def cb_categories(c: CallbackQuery, api: LapkyAPI):
    oblast = c.data.partition("@")[2] or None
    try:
        meta = await api.meta()
    except APIError as e:
        await fail(c, e)
        return
    await edit(c, texts.FILTER_INTRO, ui.categories_kb(meta, oblast))
    await c.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(c: CallbackQuery, api: LapkyAPI, settings: Settings):
    key, _, oblast = c.data.split(":", 1)[1].partition("@")
    oblast = oblast or None
    try:
        meta = await api.meta()
        if key == "food":
            await edit(c, texts.FOOD_INTRO, ui.food_kb(meta, oblast))
        else:
            ctx = ui.make_ctx(key, None, oblast)
            shelters = await api.shelters(key, None, "name", oblast=oblast)
            text, kb = ui.list_view(shelters, ctx, 0, meta, settings)
            await edit(c, text, kb)
    except APIError as e:
        await fail(c, e)
        return
    await c.answer()


# ---------- поруч зі мною ----------

@router.message(StateFilter(None), F.location)  # під час анкети геолокацію обробляє apply.py
async def msg_location(m: Message, api: LapkyAPI, settings: Settings):
    remember_location(m.from_user.id, m.location.latitude, m.location.longitude)
    try:
        meta, shelters = await api.meta(), await load_list(api, "near", m.from_user.id)
    except APIError as e:
        await fail(m, e)
        return
    text, kb = ui.list_view(shelters or [], "near", 0, meta, settings)
    await m.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.message(F.text == texts.BTN_NEAR)
async def msg_near_text(m: Message):
    # кнопка з request_location надсилає геолокацію; текст приходить лише з десктопу, де геолокації немає
    await m.answer(texts.NEAR_ASK, reply_markup=ui.main_menu())


# ---------- картка притулку ----------

@router.callback_query(F.data.startswith("sh:"))
async def cb_shelter(c: CallbackQuery, api: LapkyAPI, settings: Settings):
    _, sid, rest = c.data.split(":", 2)
    ctx, _, page = rest.rpartition(":")
    await show_card(c, api, settings, int(sid), ctx or "all", int(page or 0))


@router.callback_query(F.data.startswith("contact:"))
async def cb_contact(c: CallbackQuery, api: LapkyAPI):
    try:
        s = await api.shelter(int(c.data.split(":")[1]))
    except APIError as e:
        await fail(c, e)
        return
    if s is None:
        await c.answer(texts.NOT_FOUND, show_alert=True)
        return
    await c.message.answer(ui.contacts_text(s), disable_web_page_preview=True)
    await c.answer()


# ---------- як допомогти, про проєкт ----------

@router.message(F.text == texts.BTN_HELP)
@router.message(Command("help"))
async def msg_help(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(texts.HOW_TO_HELP, reply_markup=ui.help_kb())


@router.message(F.text == texts.BTN_ABOUT)
@router.message(Command("about"))
async def msg_about(m: Message, state: FSMContext, settings: Settings):
    await state.clear()
    await m.answer(texts.about(settings.web_url, settings.coordinator_email),
                   reply_markup=ui.about_kb(settings), disable_web_page_preview=True)
