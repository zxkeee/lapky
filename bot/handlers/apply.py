"""Заявки: «Додати притулок» (покрокова анкета) і «Це мій притулок»."""
import re
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton as IB, InlineKeyboardMarkup, Message

from .. import texts, ui
from ..api import APIError, LapkyAPI
from ..common import edit, fail

router = Router(name="apply")
URL_RE = re.compile(r"(https?://\S+|@\w{3,})")


class Apply(StatesGroup):
    name = State()
    oblast = State()
    city = State()
    address = State()
    location = State()
    phone = State()
    links = State()
    confirm = State()


async def start_apply(m: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(Apply.name)
    await m.answer(texts.APPLY_INTRO)


@router.message(Command("apply"))
async def cmd_apply(m: Message, state: FSMContext):
    await start_apply(m, state)


@router.callback_query(F.data == "add")
async def cb_add(c: CallbackQuery, state: FSMContext):
    await start_apply(c.message, state)
    await c.answer()


@router.message(Apply.name, F.text)
async def step_name(m: Message, state: FSMContext, api: LapkyAPI):
    if not 2 <= len(m.text.strip()) <= 200:
        await m.answer("Назва має бути від 2 до 200 символів.")
        return
    await state.update_data(name=m.text.strip())
    await state.set_state(Apply.oblast)
    meta = await api.meta()
    await m.answer("2/7. Оберіть область:", reply_markup=ui.oblast_picker(meta, {}, "apo:", "menu", with_all=False))


@router.callback_query(Apply.oblast, F.data.startswith("apo:"))
async def step_oblast(c: CallbackQuery, state: FSMContext, api: LapkyAPI):
    key = c.data[4:]
    await state.update_data(oblast=key)
    await state.set_state(Apply.city)
    meta = await api.meta()
    await edit(c, f"Область: <b>{escape(ui.oblast_title(meta, key))}</b>\n\n3/7. Місто або село:")
    await c.answer()


@router.message(Apply.city, F.text)
async def step_city(m: Message, state: FSMContext):
    await state.update_data(city=m.text.strip()[:100])
    await state.set_state(Apply.address)
    await m.answer("4/7. Адреса (вулиця, будинок; якщо немає — орієнтир):")


@router.message(Apply.address, F.text)
async def step_address(m: Message, state: FSMContext):
    await state.update_data(address=m.text.strip()[:300])
    await state.set_state(Apply.location)
    await m.answer("5/7. Де притулок на карті? Надішліть геоточку: 📎 → «Геопозиція» → перетягніть мітку "
                   "на притулок. Або кнопкою нижче, якщо ви зараз там.\n"
                   "Можна й текстом: <code>50.4501, 30.5234</code>",
                   reply_markup=ui.location_kb())


@router.message(Apply.location, F.location)
async def step_location(m: Message, state: FSMContext):
    await _save_location(m, state, m.location.latitude, m.location.longitude)


@router.message(Apply.location, F.text)
async def step_location_text(m: Message, state: FSMContext):
    nums = re.findall(r"-?\d+(?:[.,]\d+)?", m.text)
    if len(nums) != 2:
        await m.answer("Не вдалося розпізнати координати. Надішліть геоточку або два числа: широта, довгота.")
        return
    lat, lng = (float(x.replace(",", ".")) for x in nums)
    await _save_location(m, state, lat, lng)


async def _save_location(m: Message, state: FSMContext, lat: float, lng: float):
    if not (44 <= lat <= 53 and 22 <= lng <= 41):
        await m.answer("Ця точка поза межами України. Спробуйте ще раз.")
        return
    await state.update_data(lat=lat, lng=lng)
    await state.set_state(Apply.phone)
    await m.answer("6/7. Телефон притулку (або «-», щоб пропустити):", reply_markup=ui.main_menu())


@router.message(Apply.phone, F.text)
async def step_phone(m: Message, state: FSMContext):
    phone = m.text.strip()
    await state.update_data(phone=None if phone in ("-", "—") else phone[:50])
    await state.set_state(Apply.links)
    await m.answer("7/7. Посилання на сайт і соцмережі (кожне з нового рядка), або «-»:")


@router.message(Apply.links, F.text)
async def step_links(m: Message, state: FSMContext, api: LapkyAPI):
    links = [u if u.startswith("http") else f"https://instagram.com/{u[1:]}" for u in URL_RE.findall(m.text)][:10]
    links = [u.replace("http://", "https://", 1) for u in links]
    await state.update_data(links=links)
    await state.set_state(Apply.confirm)
    d = await state.get_data()
    meta = await api.meta()
    summary = "\n".join([
        "📝 <b>Перевірте заявку:</b>",
        f"🏠 {escape(d['name'])}",
        f"📍 {escape(ui.oblast_title(meta, d['oblast']))}, {escape(d['city'])}, {escape(d['address'])}",
        f"🗺 {d['lat']:.5f}, {d['lng']:.5f}",
        f"📞 {escape(d.get('phone') or '—')}",
        "🌐 " + (", ".join(escape(u) for u in links) or "—"),
    ])
    await m.answer(summary, disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [IB(text="✅ Надіслати", callback_data="apyes"), IB(text="❌ Скасувати", callback_data="apno")],
    ]))


@router.callback_query(Apply.confirm, F.data == "apno")
async def step_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit(c, texts.CANCELLED)
    await c.answer()


@router.callback_query(Apply.confirm, F.data == "apyes")
async def step_send(c: CallbackQuery, state: FSMContext, api: LapkyAPI):
    d = await state.get_data()
    payload = {k: d.get(k) for k in ("name", "oblast", "city", "address", "lat", "lng", "phone")}
    payload["links"] = [{"url": u} for u in d.get("links", [])]
    try:
        await api.apply(c.from_user.id, {"kind": "new_shelter", "payload": payload})
    except APIError as e:
        await fail(c, e)
        return
    await state.clear()
    await edit(c, "📨 Заявку надіслано! Адміністратор перевірить дані й повідомить вас тут.")
    await c.answer()


@router.message(Apply.oblast)
@router.message(Apply.confirm)
async def step_use_buttons(m: Message):
    await m.answer("Скористайтеся кнопками вище 👆 або /cancel, щоб скасувати.")


# ---------- «Це мій притулок» ----------

CLAIM_TEXT = ("🔑 <b>Це ваш притулок?</b>\n\nАдміністратор перевірить, що ви його представляєте "
              "(може зв'язатися з вами), і відкриє доступ до керування: потреби, збори, соцмережі, завдання.")


def _claim_kb(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [IB(text="✅ Так, надіслати заявку", callback_data=f"claimok:{sid}")],
        [IB(text="⬅️ До притулку", callback_data=f"sh:{sid}:all:0")],
    ])


async def ask_claim(m: Message, sid: int) -> None:
    """Deep-link з вебкарти: ?start=claim_<id>."""
    await m.answer(CLAIM_TEXT, reply_markup=_claim_kb(sid))


@router.callback_query(F.data.startswith("claim:"))
async def cb_claim(c: CallbackQuery):
    await edit(c, CLAIM_TEXT, _claim_kb(int(c.data[6:])))
    await c.answer()


@router.callback_query(F.data.startswith("claimok:"))
async def cb_claim_send(c: CallbackQuery, api: LapkyAPI):
    sid = int(c.data[8:])
    try:
        await api.apply(c.from_user.id, {"kind": "claim", "shelter_id": sid})
    except APIError as e:
        await fail(c, e)
        return
    await edit(c, "📨 Заявку надіслано! Адміністратор повідомить вас тут.")
    await c.answer()
