import re
from datetime import datetime
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as IB, InlineKeyboardMarkup, Message

from .. import ui
from ..api import APIError, LapkyAPI
from ..common import edit, fail

router = Router(name="manage")


class Edit(StatesGroup):
    need_text = State()
    link_url = State()
    fund_title = State()
    fund_value = State()
    task_title = State()
    task_description = State()
    task_when = State()
    task_slots = State()
    phone = State()


def _kb(rows: list[list[IB]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _back(sid: int) -> list[IB]:
    return [IB(text="⬅️ До кабінету", callback_data=f"m:{sid}")]


async def _my_list(api: LapkyAPI, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    me = await api.me(uid)
    rows = [[IB(text=f"⚙️ {s['name']}"[:60], callback_data=f"m:{s['id']}")] for s in me["shelters"]]
    rows.append([IB(text="➕ Додати притулок", callback_data="add")])
    text = "⚙️ <b>Мої притулки</b>" if me["shelters"] else \
        "У вас поки немає притулків. Знайдіть свій у списку й натисніть «🔑 Це мій притулок» або додайте новий."
    return text, _kb(rows)


@router.message(Command("my"))
async def cmd_my(m: Message, state: FSMContext, api: LapkyAPI):
    await state.clear()
    try:
        text, kb = await _my_list(api, m.from_user.id)
    except APIError as e:
        await fail(m, e)
        return
    await m.answer(text, reply_markup=kb)


@router.callback_query(F.data == "my")
async def cb_my(c: CallbackQuery, api: LapkyAPI):
    try:
        text, kb = await _my_list(api, c.from_user.id)
    except APIError as e:
        await fail(c, e)
        return
    await edit(c, text, kb)
    await c.answer()


async def _cabinet(api: LapkyAPI, uid: int, sid: int) -> tuple[str, InlineKeyboardMarkup]:
    meta, s = await api.meta(), await api.shelter(sid, uid)
    urg = next(u for u in meta["urgency"] if u["key"] == s["urgency_level"])
    pledged = sum(n["pledges_active"] for n in s["needs"])
    text = (f"⚙️ <b>Кабінет «{escape(s['name'])}»</b>\n"
            f"Терміновість: {urg['emoji']} {escape(urg['title'])}\n"
            f"Потреб: {len(s['needs'])} · соцмереж: {len(s['links'])} · зборів: {len(s['fundraisers'])} · "
            f"завдань: {len(s['tasks'])} · обіцянок волонтерів: {pledged}")
    return text, _kb([
        [IB(text="🚦 Терміновість", callback_data=f"mu:{sid}"), IB(text="📋 Потреби", callback_data=f"mn:{sid}")],
        [IB(text="🔗 Соцмережі", callback_data=f"ml:{sid}"), IB(text="💛 Збори", callback_data=f"mf:{sid}")],
        [IB(text="🗓 Завдання", callback_data=f"mt:{sid}"), IB(text="🙋 Хто що везе", callback_data=f"mp:{sid}")],
        [IB(text="📞 Телефон", callback_data=f"mph:{sid}"), IB(text="👁 Картка", callback_data=f"sh:{sid}:all:0")],
        [IB(text="⬅️ Мої притулки", callback_data="my")],
    ])


async def show_cabinet(event: CallbackQuery | Message, api: LapkyAPI, sid: int) -> None:
    try:
        text, kb = await _cabinet(api, event.from_user.id, sid)
    except APIError as e:
        await fail(event, e)
        return
    if isinstance(event, CallbackQuery):
        await edit(event, text, kb)
        await event.answer()
    else:
        await event.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("m:"))
async def cb_cabinet(c: CallbackQuery, state: FSMContext, api: LapkyAPI):
    await state.clear()
    await show_cabinet(c, api, int(c.data[2:]))


@router.callback_query(F.data.startswith("mu:"))
async def cb_urgency(c: CallbackQuery, api: LapkyAPI):
    sid = int(c.data[3:])
    meta = await api.meta()
    rows = [[IB(text=f"{u['emoji']} {u['title']}", callback_data=f"mus:{sid}:{u['key']}")] for u in meta["urgency"]]
    await edit(c, "🚦 Оберіть рівень. Критичний — підписники отримають сповіщення.", _kb(rows + [_back(sid)]))
    await c.answer()


@router.callback_query(F.data.startswith("mus:"))
async def cb_urgency_set(c: CallbackQuery, api: LapkyAPI):
    _, sid, level = c.data.split(":")
    try:
        await api.patch_shelter(c.from_user.id, int(sid), {"urgency_level": level})
    except APIError as e:
        await fail(c, e)
        return
    await show_cabinet(c, api, int(sid))


@router.callback_query(F.data.startswith("mph:"))
async def cb_phone(c: CallbackQuery, state: FSMContext):
    await state.set_state(Edit.phone)
    await state.update_data(sid=int(c.data[4:]))
    await c.message.answer("📞 Надішліть новий телефон притулку (або /cancel):")
    await c.answer()


@router.message(Edit.phone, F.text)
async def edit_phone(m: Message, state: FSMContext, api: LapkyAPI):
    sid = (await state.get_data())["sid"]
    try:
        await api.patch_shelter(m.from_user.id, sid, {"phone": m.text.strip()[:50]})
    except APIError as e:
        await fail(m, e)
        return
    await state.clear()
    await show_cabinet(m, api, sid)


@router.callback_query(F.data.startswith("mn:"))
async def cb_needs(c: CallbackQuery, state: FSMContext, api: LapkyAPI):
    await state.clear()
    await _needs(c, api, int(c.data[3:]))


async def _needs(c: CallbackQuery, api: LapkyAPI, sid: int) -> None:
    try:
        meta, s = await api.meta(), await api.shelter(sid, c.from_user.id)
    except APIError as e:
        await fail(c, e)
        return
    emoji = {cat["key"]: cat["emoji"] for cat in meta["categories"]}
    rows = [[IB(text=f"❌ {emoji[n['category']]} {n['text']}"[:60], callback_data=f"mnd:{n['id']}:{sid}")]
            for n in s["needs"]]
    rows.append([IB(text="➕ Додати потребу", callback_data=f"mna:{sid}")])
    rows.append(_back(sid))
    await edit(c, "📋 <b>Потреби</b>\nНатисніть ❌, щоб закрити потребу (волонтерів, які її взяли, буде повідомлено).",
               _kb(rows))
    await c.answer()


@router.callback_query(F.data.startswith("mnd:"))
async def cb_need_delete(c: CallbackQuery, state: FSMContext, api: LapkyAPI):
    _, nid, sid = c.data.split(":")
    try:
        await api.delete_need(c.from_user.id, int(nid))
    except APIError as e:
        await fail(c, e)
        return
    await _needs(c, api, int(sid))


@router.callback_query(F.data.startswith("mna:"))
async def cb_need_category(c: CallbackQuery, api: LapkyAPI):
    sid = int(c.data[4:])
    meta = await api.meta()
    rows = []
    for cat in meta["categories"]:
        if cat["key"] == "food":
            rows += [[IB(text=f"{cat['emoji']} Корм: {s['emoji']} {s['title']}"[:60], callback_data=f"mnc:{sid}:food.{s['key']}")]
                     for s in cat["subcategories"]]
        else:
            rows.append([IB(text=f"{cat['emoji']} {cat['title']}", callback_data=f"mnc:{sid}:{cat['key']}")])
    await edit(c, "➕ До якої категорії належить потреба?", _kb(rows + [_back(sid)]))
    await c.answer()


@router.callback_query(F.data.startswith("mnc:"))
async def cb_need_text(c: CallbackQuery, state: FSMContext):
    _, sid, cat = c.data.split(":")
    category, _, sub = cat.partition(".")
    await state.set_state(Edit.need_text)
    await state.update_data(sid=int(sid), category=category, subcategory=sub or None)
    await c.message.answer("✍️ Опишіть потребу одним повідомленням (до 500 символів), напр. "
                           "«Сухий корм для цуценят, 20 кг до п'ятниці». /cancel — скасувати.")
    await c.answer()


@router.message(Edit.need_text, F.text)
async def edit_need_text(m: Message, state: FSMContext, api: LapkyAPI):
    d = await state.get_data()
    try:
        await api.add_need(m.from_user.id, d["sid"], d["category"], d["subcategory"], m.text.strip()[:500])
    except APIError as e:
        await fail(m, e)
        return
    await state.clear()
    await m.answer("✅ Потребу додано — вона вже на карті й у боті, підписники отримали сповіщення.")
    await show_cabinet(m, api, d["sid"])


@router.callback_query(F.data.startswith("ml:"))
async def cb_links(c: CallbackQuery, state: FSMContext, api: LapkyAPI):
    await state.clear()
    await _links(c, api, int(c.data[3:]))


async def _links(c: CallbackQuery, api: LapkyAPI, sid: int) -> None:
    try:
        meta, s = await api.meta(), await api.shelter(sid, c.from_user.id)
    except APIError as e:
        await fail(c, e)
        return
    rows = [[IB(text=f"❌ {ui.link_icon(meta, l['kind'])} {ui._short(l['url'])}"[:60],
                callback_data=f"mld:{l['id']}:{sid}")] for l in s["links"]]
    rows.append([IB(text="➕ Додати посилання", callback_data=f"mla:{sid}")])
    await edit(c, "🔗 <b>Сайт і соцмережі</b>", _kb(rows + [_back(sid)]))
    await c.answer()


@router.callback_query(F.data.startswith("mld:"))
async def cb_link_delete(c: CallbackQuery, state: FSMContext, api: LapkyAPI):
    _, lid, sid = c.data.split(":")
    try:
        await api.delete_link(c.from_user.id, int(lid))
    except APIError as e:
        await fail(c, e)
        return
    await _links(c, api, int(sid))


@router.callback_query(F.data.startswith("mla:"))
async def cb_link_add(c: CallbackQuery, state: FSMContext):
    await state.set_state(Edit.link_url)
    await state.update_data(sid=int(c.data[4:]))
    await c.message.answer("🔗 Надішліть посилання (https://…): сайт, Instagram, Facebook, Telegram-канал, TikTok…")
    await c.answer()


@router.message(Edit.link_url, F.text)
async def edit_link(m: Message, state: FSMContext, api: LapkyAPI):
    sid = (await state.get_data())["sid"]
    url = m.text.strip().replace("http://", "https://", 1)
    if not url.startswith("https://"):
        url = "https://" + url
    try:
        await api.add_link(m.from_user.id, sid, url)
    except APIError as e:
        await fail(m, e)
        return
    await state.clear()
    await show_cabinet(m, api, sid)


@router.callback_query(F.data.startswith("mf:"))
async def cb_funds(c: CallbackQuery, state: FSMContext, api: LapkyAPI):
    await state.clear()
    await _funds(c, api, int(c.data[3:]))


async def _funds(c: CallbackQuery, api: LapkyAPI, sid: int) -> None:
    try:
        funds = await api.fundraisers(c.from_user.id, sid)
    except APIError as e:
        await fail(c, e)
        return
    rows = []
    for f in funds:
        rows.append([IB(text=("🟢 " if f["active"] else "⚪ ") + f["title"][:40], callback_data=f"mft:{f['id']}:{sid}:{int(not f['active'])}"),
                     IB(text="❌", callback_data=f"mfd:{f['id']}:{sid}")])
    rows.append([IB(text="➕ Додати збір або реквізити", callback_data=f"mfa:{sid}")])
    await edit(c, "💛 <b>Збори та реквізити</b>\n🟢 — показується на карті й у боті, ⚪ — приховано. "
                  "Натисніть на назву, щоб перемкнути.", _kb(rows + [_back(sid)]))
    await c.answer()


@router.callback_query(F.data.regexp(r"^mf[td]:"))
async def cb_fund_change(c: CallbackQuery, state: FSMContext, api: LapkyAPI):
    parts = c.data.split(":")
    fid, sid = int(parts[1]), int(parts[2])
    try:
        if parts[0] == "mft":
            await api.patch_fundraiser(c.from_user.id, fid, {"active": parts[3] == "1"})
        else:
            await api.delete_fundraiser(c.from_user.id, fid)
    except APIError as e:
        await fail(c, e)
        return
    await _funds(c, api, int(sid))


@router.callback_query(F.data.startswith("mfa:"))
async def cb_fund_add(c: CallbackQuery, state: FSMContext):
    await state.set_state(Edit.fund_title)
    await state.update_data(sid=int(c.data[4:]))
    await c.message.answer("💛 Назва збору, напр. «На стерилізацію 20 котів» або «Рахунок ГО»:")
    await c.answer()


@router.message(Edit.fund_title, F.text)
async def edit_fund_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip()[:120])
    await state.set_state(Edit.fund_value)
    await m.answer("Посилання на банку monobank / PayPal / Patreon або IBAN чи номер картки:")


@router.message(Edit.fund_value, F.text)
async def edit_fund_value(m: Message, state: FSMContext, api: LapkyAPI):
    d = await state.get_data()
    try:
        await api.add_fundraiser(m.from_user.id, d["sid"], d["title"], m.text.strip())
    except APIError as e:
        await fail(m, e)
        return
    await state.clear()
    await m.answer("✅ Збір додано.")
    await show_cabinet(m, api, d["sid"])


@router.callback_query(F.data.startswith("mt:"))
async def cb_tasks(c: CallbackQuery, state: FSMContext, api: LapkyAPI):
    await state.clear()
    await _tasks(c, api, int(c.data[3:]))


async def _tasks(c: CallbackQuery, api: LapkyAPI, sid: int) -> None:
    try:
        tasks = await api.tasks(shelter_id=sid)
    except APIError as e:
        await fail(c, e)
        return
    rows = [[IB(text=f"{t['starts_at'][5:]} · {t['title']} ({t['taken']}/{t['slots']})"[:60],
                callback_data=f"mtv:{t['id']}:{sid}")] for t in tasks]
    rows.append([IB(text="➕ Нове завдання", callback_data=f"mta:{sid}")])
    await edit(c, "🗓 <b>Волонтерські завдання</b>", _kb(rows + [_back(sid)]))
    await c.answer()


@router.callback_query(F.data.startswith("mtv:"))
async def cb_task_view(c: CallbackQuery, api: LapkyAPI):
    _, tid, sid = c.data.split(":")
    try:
        t, people = await api.task(int(tid)), await api.task_signups(c.from_user.id, int(tid))
    except APIError as e:
        await fail(c, e)
        return
    who = [("@" + escape(p["username"])) if p["username"] else
           f'<a href="tg://user?id={p["telegram_id"]}">{escape(p["first_name"] or "Волонтер")}</a>' for p in people]
    text = ui.task_text(t) + "\n\n👥 <b>Записані:</b> " + (", ".join(who) or "поки нікого")
    await edit(c, text, _kb([[IB(text="✅ Закрити завдання", callback_data=f"mtc:{tid}:{sid}")],
                             [IB(text="⬅️ До завдань", callback_data=f"mt:{sid}")]]))
    await c.answer()


@router.callback_query(F.data.startswith("mtc:"))
async def cb_task_close(c: CallbackQuery, state: FSMContext, api: LapkyAPI):
    _, tid, sid = c.data.split(":")
    try:
        await api.patch_task(c.from_user.id, int(tid), {"status": "closed"})
    except APIError as e:
        await fail(c, e)
        return
    await _tasks(c, api, int(sid))


@router.callback_query(F.data.startswith("mta:"))
async def cb_task_add(c: CallbackQuery, state: FSMContext):
    await state.set_state(Edit.task_title)
    await state.update_data(sid=int(c.data[4:]))
    await c.message.answer("🗓 Коротка назва завдання, напр. «Вигул собак», «Відвезти кота до ветклініки»:")
    await c.answer()


@router.message(Edit.task_title, F.text)
async def edit_task_title(m: Message, state: FSMContext):
    await state.update_data(title=m.text.strip()[:120])
    await state.set_state(Edit.task_description)
    await m.answer("Опис: що робити, що взяти з собою, де зустрічаємося (або «-»):")


@router.message(Edit.task_description, F.text)
async def edit_task_description(m: Message, state: FSMContext):
    text = m.text.strip()
    await state.update_data(description=None if text in ("-", "—") else text[:1000])
    await state.set_state(Edit.task_when)
    await m.answer("Коли? Формат <code>ДД.ММ ГГ:ХХ</code>, напр. <code>12.10 10:00</code>:")


@router.message(Edit.task_when, F.text)
async def edit_task_when(m: Message, state: FSMContext):
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\s+(\d{1,2}):(\d{2})", m.text.strip())
    now = datetime.now()
    try:
        day, month, year, hour, minute = match.groups()
        when = datetime(int(year or now.year), int(month), int(day), int(hour), int(minute))
        if when < now and not year:
            when = when.replace(year=now.year + 1)
    except (AttributeError, ValueError):
        await m.answer("Не вдалося розпізнати дату. Приклад: <code>12.10 10:00</code>")
        return
    if when < now:
        await m.answer("Ця дата вже минула.")
        return
    await state.update_data(starts_at=when.strftime("%Y-%m-%d %H:%M"))
    await state.set_state(Edit.task_slots)
    await m.answer("Скільки волонтерів потрібно? (число)")


@router.message(Edit.task_slots, F.text)
async def edit_task_slots(m: Message, state: FSMContext, api: LapkyAPI):
    if not m.text.strip().isdigit() or not 1 <= int(m.text) <= 100:
        await m.answer("Вкажіть число від 1 до 100.")
        return
    d = await state.get_data()
    try:
        await api.create_task(m.from_user.id, d["sid"], {"title": d["title"], "description": d["description"],
                                                         "starts_at": d["starts_at"], "slots": int(m.text)})
    except APIError as e:
        await fail(m, e)
        return
    await state.clear()
    await m.answer("✅ Завдання опубліковано — підписники отримали сповіщення.")
    await show_cabinet(m, api, d["sid"])


@router.callback_query(F.data.startswith("mp:"))
async def cb_pledges(c: CallbackQuery, api: LapkyAPI):
    sid = int(c.data[3:])
    try:
        pledges = await api.shelter_pledges(c.from_user.id, sid)
    except APIError as e:
        await fail(c, e)
        return
    lines = ["🙋 <b>Волонтери, які взяли потреби</b>"]
    for p in pledges:
        who = ("@" + escape(p["username"])) if p["username"] else \
            f'<a href="tg://user?id={p["telegram_id"]}">{escape(p["first_name"] or "Волонтер")}</a>'
        note = f" — <i>{escape(p['note'])}</i>" if p.get("note") else ""
        lines.append(f"• {who}: {escape(p['need_text'])}{note}")
    if not pledges:
        lines.append("\nПоки нікого. Коли волонтер натисне «Беру», ви отримаєте повідомлення.")
    await edit(c, "\n".join(lines), _kb([_back(sid)]))
    await c.answer()
