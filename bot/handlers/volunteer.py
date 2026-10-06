"""Волонтер: «беру потребу», підписки, завдання, «Мої справи»."""
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton as IB, InlineKeyboardMarkup, Message

from .. import texts, ui
from ..api import APIError, LapkyAPI
from ..common import edit, fail, last_location, show_card
from ..config import Settings

router = Router(name="volunteer")


def _kb(rows: list[list[IB]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- «Беру потребу» ----------

@router.callback_query(F.data.startswith("pl:"))
async def cb_pledge_pick(c: CallbackQuery, api: LapkyAPI):
    sid = int(c.data[3:])
    try:
        meta, s = await api.meta(), await api.shelter(sid)
    except APIError as e:
        await fail(c, e)
        return
    if not s or not s["needs"]:
        await c.answer("У притулку зараз немає відкритих потреб 💚", show_alert=True)
        return
    emoji = {cat["key"]: cat["emoji"] for cat in meta["categories"]}
    rows = [[IB(text=f"{emoji[n['category']]} {n['text']}"[:60], callback_data=f"pn:{n['id']}")] for n in s["needs"]]
    rows.append([IB(text="⬅️ До картки", callback_data=f"sh:{sid}:all:0")])
    await edit(c, f"🙋 <b>Що ви привезете або зробите для «{escape(s['name'])}»?</b>", _kb(rows))
    await c.answer()


async def ask_pledge(event: CallbackQuery | Message, api: LapkyAPI, need_id: int) -> None:
    """Підтвердження «беру» (з картки або з deep-link вебкарти ?start=pledge_<id>)."""
    try:
        shelters = await api.shelters()
    except APIError as e:
        await fail(event, e)
        return
    found = next(((s, n) for s in shelters for n in s["needs"] if n["id"] == need_id), None)
    if found is None:
        msg = "Цю потребу вже закрито 💚"
        await (event.answer(msg, show_alert=True) if isinstance(event, CallbackQuery) else event.answer(msg))
        return
    s, n = found
    text = texts.PLEDGE_CONFIRM.format(need=escape(n["text"]), shelter=escape(s["name"]))
    kb = _kb([[IB(text="✅ Так, беру", callback_data=f"pc:{need_id}"),
               IB(text="Скасувати", callback_data=f"sh:{s['id']}:all:0")]])
    if isinstance(event, CallbackQuery):
        await edit(event, text, kb)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("pn:"))
async def cb_pledge_ask(c: CallbackQuery, api: LapkyAPI):
    await ask_pledge(c, api, int(c.data[3:]))


@router.callback_query(F.data.startswith("pc:"))
async def cb_pledge_confirm(c: CallbackQuery, api: LapkyAPI):
    try:
        await api.pledge(c.from_user.id, int(c.data[3:]))
    except APIError as e:
        await fail(c, e)
        return
    await edit(c, "🙏 Дякуємо! Притулок отримав повідомлення й зв'яжеться з вами.\n"
                  "Коли передасте — позначте це в «🙋 Мої справи» → «Мої обіцянки».",
               _kb([[IB(text="🙋 Мої обіцянки", callback_data="myp")]]))
    await c.answer("Готово!")


@router.callback_query(F.data == "myp")
async def cb_my_pledges(c: CallbackQuery, api: LapkyAPI):
    try:
        pledges = await api.my_pledges(c.from_user.id)
    except APIError as e:
        await fail(c, e)
        return
    lines = ["🙋 <b>Мої обіцянки</b>"]
    rows = []
    for p in pledges:
        lines.append(f"• {escape(p['need_text'])} — «{escape(p['shelter_name'])}»")
        rows.append([IB(text=f"✅ Привіз: {p['need_text']}"[:40], callback_data=f"pd:{p['id']}"),
                     IB(text="❌", callback_data=f"px:{p['id']}")])
    if not pledges:
        lines.append("\nПоки порожньо. Відкрийте притулок і натисніть «🙋 Беру потребу».")
    rows.append([IB(text="⬅️ Мої справи", callback_data="mine")])
    await edit(c, "\n".join(lines), _kb(rows))
    await c.answer()


@router.callback_query(F.data.regexp(r"^p[dx]:\d+$"))
async def cb_pledge_close(c: CallbackQuery, api: LapkyAPI):
    status = "done" if c.data.startswith("pd:") else "cancelled"
    try:
        await api.update_pledge(c.from_user.id, int(c.data[3:]), status)
    except APIError as e:
        await fail(c, e)
        return
    await c.answer("Дякуємо! 💛" if status == "done" else "Скасовано")
    await cb_my_pledges(c, api)


# ---------- підписки ----------

@router.callback_query(F.data.startswith("sub:"))
async def cb_toggle_subscription(c: CallbackQuery, api: LapkyAPI, settings: Settings):
    sid = int(c.data[4:])
    try:
        subs = await api.subscriptions(c.from_user.id)
        current = next((x for x in subs if x["shelter_id"] == sid), None)
        if current:
            await api.unsubscribe(c.from_user.id, current["id"])
        else:
            await api.subscribe(c.from_user.id, shelter_id=sid)
    except APIError as e:
        await fail(c, e)
        return
    await c.answer("Підписку скасовано" if current else "🔔 Ви отримуватимете нові потреби й завдання притулку")
    await show_card(c, api, settings, sid)


@router.callback_query(F.data == "mys")
async def cb_my_subscriptions(c: CallbackQuery, api: LapkyAPI):
    try:
        subs = await api.subscriptions(c.from_user.id)
    except APIError as e:
        await fail(c, e)
        return
    lines = ["🔔 <b>Мої підписки</b>"]
    rows = []
    for s in subs:
        mark = " (лише термінове)" if s["only_urgent"] else ""
        lines.append(f"• {escape(s['title'])}{mark}")
        rows.append([IB(text=f"🔕 {s['title']}"[:60], callback_data=f"unsub:{s['id']}")])
    if not subs:
        lines.append("\nПідпишіться на притулок у його картці або на цілу область 👇")
    rows.append([IB(text="➕ Підписатися на область", callback_data="suo")])
    rows.append([IB(text="⬅️ Мої справи", callback_data="mine")])
    await edit(c, "\n".join(lines), _kb(rows))
    await c.answer()


@router.callback_query(F.data.startswith("unsub:"))
async def cb_unsubscribe(c: CallbackQuery, api: LapkyAPI):
    try:
        await api.unsubscribe(c.from_user.id, int(c.data[6:]))
    except APIError as e:
        await fail(c, e)
        return
    await cb_my_subscriptions(c, api)


@router.callback_query(F.data == "suo")
async def cb_subscribe_oblast(c: CallbackQuery, api: LapkyAPI):
    try:
        meta, counts = await api.meta(), {o["key"]: o["count"] for o in await api.oblasts()}
    except APIError as e:
        await fail(c, e)
        return
    await edit(c, "🔔 Про яку область повідомляти?", ui.oblast_picker(meta, counts, "suo:", "mys", with_all=False))
    await c.answer()


@router.callback_query(F.data.startswith("suo:"))
async def cb_subscribe_oblast_mode(c: CallbackQuery, api: LapkyAPI):
    key = c.data[4:]
    meta = await api.meta()
    await edit(c, f"🔔 {escape(ui.oblast_title(meta, key))}: що надсилати?", _kb([
        [IB(text="🔴 Лише термінове", callback_data=f"sus:{key}:1")],
        [IB(text="🆕 Усі нові потреби й завдання", callback_data=f"sus:{key}:0")],
        [IB(text="⬅️ Назад", callback_data="suo")],
    ]))
    await c.answer()


@router.callback_query(F.data.startswith("sus:"))
async def cb_subscribe_oblast_save(c: CallbackQuery, api: LapkyAPI):
    _, key, urgent = c.data.split(":")
    try:
        await api.subscribe(c.from_user.id, oblast=key, only_urgent=urgent == "1")
    except APIError as e:
        await fail(c, e)
        return
    await c.answer("🔔 Підписку оформлено")
    await cb_my_subscriptions(c, api)


# ---------- завдання ----------

async def show_task(event: CallbackQuery | Message, api: LapkyAPI, task_id: int) -> None:
    try:
        t = await api.task(task_id)
        mine = {x["id"] for x in await api.my_tasks(event.from_user.id)} if t else set()
    except APIError as e:
        if e.status in (401, 403):
            mine = set()
        else:
            await fail(event, e)
            return
    if t is None:
        msg = "Завдання вже не актуальне."
        await (event.answer(msg, show_alert=True) if isinstance(event, CallbackQuery) else event.answer(msg))
        return
    if task_id in mine:
        action = IB(text="❌ Скасувати запис", callback_data=f"tsc:{task_id}")
    elif t["status"] == "open" and t["taken"] < t["slots"]:
        action = IB(text="✋ Записатися", callback_data=f"tsu:{task_id}")
    else:
        action = IB(text="Місць немає", callback_data="noop")
    kb = _kb([[action], [IB(text="🏠 Притулок", callback_data=f"sh:{t['shelter_id']}:all:0")]])
    if isinstance(event, CallbackQuery):
        await edit(event, ui.task_text(t), kb)
        await event.answer()
    else:
        await event.answer(ui.task_text(t), reply_markup=kb)


@router.callback_query(F.data.startswith("task:"))
async def cb_task(c: CallbackQuery, api: LapkyAPI):
    await show_task(c, api, int(c.data[5:]))


@router.callback_query(F.data.regexp(r"^ts[uc]:\d+$"))
async def cb_task_signup(c: CallbackQuery, api: LapkyAPI):
    tid = int(c.data[4:])
    try:
        if c.data.startswith("tsu:"):
            await api.signup(c.from_user.id, tid)
            await c.answer("✋ Ви записані! Нагадаємо за добу до початку.", show_alert=True)
        else:
            await api.cancel_signup(c.from_user.id, tid)
            await c.answer("Запис скасовано")
    except APIError as e:
        await fail(c, e)
        return
    await show_task(c, api, tid)


@router.callback_query(F.data.startswith("st:"))
async def cb_shelter_tasks(c: CallbackQuery, api: LapkyAPI):
    sid = int(c.data[3:])
    try:
        tasks = await api.tasks(shelter_id=sid)
    except APIError as e:
        await fail(c, e)
        return
    text, kb = ui.tasks_list(tasks, "📋 <b>Завдання притулку</b>", f"sh:{sid}:all:0")
    await edit(c, text, kb)
    await c.answer()


@router.callback_query(F.data.in_({"tasks", "ntasks"}))
async def cb_all_tasks(c: CallbackQuery, api: LapkyAPI):
    loc = last_location(c.from_user.id) if c.data == "ntasks" else None
    try:
        tasks = await api.tasks(near=loc, radius_km=100 if loc else None)
    except APIError as e:
        await fail(c, e)
        return
    title = "📋 <b>Завдання поруч</b> (до 100 км)" if loc else "📋 <b>Найближчі волонтерські завдання</b>"
    text, kb = ui.tasks_list(tasks, title, "menu")
    await edit(c, text, kb)
    await c.answer()


@router.callback_query(F.data == "myt")
async def cb_my_tasks(c: CallbackQuery, api: LapkyAPI):
    try:
        tasks = await api.my_tasks(c.from_user.id)
    except APIError as e:
        await fail(c, e)
        return
    text, kb = ui.tasks_list(tasks, "🗓 <b>Мої завдання</b>", "mine")
    await edit(c, text, kb)
    await c.answer()


# ---------- «Мої справи» ----------

async def mine_kb(api: LapkyAPI, uid: int) -> InlineKeyboardMarkup:
    rows = [
        [IB(text="🙋 Мої обіцянки", callback_data="myp"), IB(text="🗓 Мої завдання", callback_data="myt")],
        [IB(text="🔔 Підписки", callback_data="mys"), IB(text="📋 Усі завдання", callback_data="tasks")],
    ]
    try:
        me = await api.me(uid)
    except APIError:
        me = {"shelters": [], "is_admin": False}
    if me["shelters"]:
        rows.append([IB(text="⚙️ Мої притулки", callback_data="my")])
    rows.append([IB(text="➕ Додати свій притулок", callback_data="add")])
    if me["is_admin"]:
        rows.append([IB(text="🛡 Модерація заявок", callback_data="mod:0")])
    return _kb(rows)


@router.message(F.text == texts.BTN_MINE)
@router.message(Command("mine"))
async def msg_mine(m: Message, state: FSMContext, api: LapkyAPI):
    await state.clear()
    await m.answer(texts.MINE_INTRO, reply_markup=await mine_kb(api, m.from_user.id))


@router.callback_query(F.data == "mine")
async def cb_mine(c: CallbackQuery, api: LapkyAPI):
    await edit(c, texts.MINE_INTRO, await mine_kb(api, c.from_user.id))
    await c.answer()
