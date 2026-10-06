"""Модерація заявок (лише адміністратори: ADMIN_TELEGRAM_IDS на сервері)."""
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton as IB, InlineKeyboardMarkup, Message

from .. import ui
from ..api import APIError, LapkyAPI
from ..common import edit, fail

router = Router(name="moderate")


async def _view(api: LapkyAPI, uid: int, idx: int) -> tuple[str, InlineKeyboardMarkup]:
    apps = await api.applications(uid)
    if not apps:
        return "🛡 Нових заявок немає ✨", InlineKeyboardMarkup(inline_keyboard=[[IB(text="⬅️ Мої справи", callback_data="mine")]])
    idx = min(max(idx, 0), len(apps) - 1)
    a = apps[idx]
    who = ("@" + escape(a["username"])) if a["username"] else \
        f'<a href="tg://user?id={a["telegram_id"]}">{escape(a["first_name"] or "користувач")}</a>'
    lines = [f"🛡 <b>Заявка {idx + 1}/{len(apps)}</b> (№{a['id']}, {escape(a['created_at'])})", f"Від: {who}", ""]
    if a["kind"] == "claim":
        lines.append(f"🔑 «Це мій притулок»: <b>{escape(a['shelter_name'] or '?')}</b> (id {a['shelter_id']})")
        if a["payload"].get("comment"):
            lines.append(f"Коментар: {escape(a['payload']['comment'])}")
    else:
        p = a["payload"]
        meta = await api.meta()
        lines += [
            f"➕ Новий притулок: <b>{escape(p['name'])}</b>",
            f"📍 {escape(ui.oblast_title(meta, p['oblast']))}, {escape(p['city'])}, {escape(p['address'])}",
            f'🗺 <a href="https://www.openstreetmap.org/?mlat={p["lat"]}&amp;mlon={p["lng"]}#map=17/{p["lat"]}/{p["lng"]}">'
            f"{p['lat']:.5f}, {p['lng']:.5f}</a>",
            f"📞 {escape(p.get('phone') or '—')}",
            "🌐 " + (", ".join(escape(l["url"]) for l in p.get("links", [])) or "—"),
        ]
    nav = []
    if idx > 0:
        nav.append(IB(text="◀️", callback_data=f"mod:{idx - 1}"))
    if idx < len(apps) - 1:
        nav.append(IB(text="▶️", callback_data=f"mod:{idx + 1}"))
    rows = [[IB(text="✅ Схвалити", callback_data=f"moda:{a['id']}:{idx}"),
             IB(text="❌ Відхилити", callback_data=f"modr:{a['id']}:{idx}")]]
    if nav:
        rows.append(nav)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("moderate"))
async def cmd_moderate(m: Message, api: LapkyAPI):
    try:
        text, kb = await _view(api, m.from_user.id, 0)
    except APIError as e:
        await fail(m, e)
        return
    await m.answer(text, reply_markup=kb, disable_web_page_preview=True)


@router.callback_query(F.data.startswith("mod:"))
async def cb_moderate(c: CallbackQuery, api: LapkyAPI):
    try:
        text, kb = await _view(api, c.from_user.id, int(c.data[4:]))
    except APIError as e:
        await fail(c, e)
        return
    await edit(c, text, kb)
    await c.answer()


@router.callback_query(F.data.regexp(r"^mod[ar]:"))
async def cb_decide(c: CallbackQuery, api: LapkyAPI):
    action, app_id, idx = c.data.split(":")
    try:
        if action == "moda":
            await api.approve(c.from_user.id, int(app_id))
        else:
            await api.reject(c.from_user.id, int(app_id))
        text, kb = await _view(api, c.from_user.id, int(idx))
    except APIError as e:
        await fail(c, e)
        return
    await c.answer("Схвалено ✅" if action == "moda" else "Відхилено")
    await edit(c, text, kb)
