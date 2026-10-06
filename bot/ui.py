import math
from html import escape as _escape

from aiogram.types import (
    InlineKeyboardButton as IB, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup,
)

from . import texts
from .config import Settings


def escape(s: str, quote: bool = False) -> str:
    return _escape(s, quote=quote)


PAGE_SIZE = 8
DIVIDER = "━━━━━━━━━━━━━━━━━━━━"


def parse_ctx(ctx: str) -> tuple[str | None, str | None, str | None]:
    what, _, oblast = ctx.partition("@")
    if what == "all":
        return None, None, oblast or None
    cat, _, sub = what.partition(".")
    return cat, (sub or None), oblast or None


def make_ctx(cat: str | None, sub: str | None, oblast: str | None) -> str:
    what = "all" if cat is None else (f"{cat}.{sub}" if sub else cat)
    return f"{what}@{oblast}" if oblast else what


def oblast_title(meta: dict, key: str | None) -> str:
    if not key:
        return "уся Україна"
    title = next((o["title"] for o in meta["oblasts"] if o["key"] == key), key)
    return title if key in ("kyiv", "sevastopol", "crimea") else f"{title} обл."


def ctx_title(ctx: str, meta: dict) -> str:
    cat, sub, oblast = parse_ctx(ctx)
    if cat == "near":
        return "📍 <b>Притулки поруч</b> — від найближчих"
    if cat is None:
        title = "🗺 <b>Усі притулки</b> — від найтерміновіших до стабільних"
    else:
        c = next(c for c in meta["categories"] if c["key"] == cat)
        title = f"{c['emoji']} <b>{escape(c['title'])}</b>"
        if sub:
            s = next(s for s in c.get("subcategories", []) if s["key"] == sub)
            title += f" → {s['emoji']} {escape(s['title'])}"
    return title + f"\n📍 {escape(oblast_title(meta, oblast))}"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.BTN_ALL), KeyboardButton(text=texts.BTN_FILTER)],
            [KeyboardButton(text=texts.BTN_NEAR, request_location=True), KeyboardButton(text=texts.BTN_MINE)],
            [KeyboardButton(text=texts.BTN_HELP), KeyboardButton(text=texts.BTN_ABOUT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def location_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Я зараз у притулку", request_location=True)]],
                               resize_keyboard=True, one_time_keyboard=True)


def onboarding_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[IB(text="✅ Зрозуміло!", callback_data="ok")]])


def categories_kb(meta: dict, oblast: str | None = None) -> InlineKeyboardMarkup:
    suffix = f"@{oblast}" if oblast else ""
    rows = [[IB(text=f"{c['emoji']} {c['title']} ({c['hint']})", callback_data=f"cat:{c['key']}{suffix}")]
            for c in meta["categories"]]
    rows.append([IB(text=f"📍 Область: {oblast_title(meta, oblast)}", callback_data=f"op:cat{suffix}")])
    rows.append([IB(text="🏠 Головне меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def food_kb(meta: dict, oblast: str | None = None) -> InlineKeyboardMarkup:
    food = next(c for c in meta["categories"] if c["key"] == "food")
    subs = [IB(text=f"{s['emoji']} {s['title']}", callback_data=f"list:{make_ctx('food', s['key'], oblast)}:0")
            for s in food["subcategories"]]
    rows = [subs[i:i + 2] for i in range(0, len(subs), 2)]
    rows.append([IB(text="🍽 Показати весь корм та ліки", callback_data=f"list:{make_ctx('food', None, oblast)}:0")])
    rows.append([IB(text="⬅️ До категорій", callback_data="cat" + (f"@{oblast}" if oblast else ""))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def oblast_picker(meta: dict, counts: dict[str, int], prefix: str, back: str,
                  with_all: bool = True) -> InlineKeyboardMarkup:
    ordered = sorted(meta["oblasts"], key=lambda o: counts.get(o["key"], 0) == 0)
    buttons = [IB(text=f"{oblast_title(meta, o['key'])} ({counts.get(o['key'], 0)})",
                  callback_data=f"{prefix}{o['key']}") for o in ordered]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    if with_all:
        rows.insert(0, [IB(text=f"🇺🇦 Уся Україна ({sum(counts.values())})", callback_data=prefix)])
    rows.append([IB(text="⬅️ Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [IB(text="🔍 Обрати категорію", callback_data="cat")],
        [IB(text="🗺 Усі притулки", callback_data="list:all:0")],
        [IB(text="📋 Волонтерські завдання", callback_data="tasks")],
    ])


def about_kb(settings: Settings) -> InlineKeyboardMarkup:
    rows = []
    if settings.web_url_is_public:
        rows.append([IB(text="🗺 Відкрити вебкарту", url=settings.web_url)])
    rows.append([IB(text="➕ Додати притулок", callback_data="add")])
    rows.append([IB(text="⬅️ Назад до головного меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _dist(s: dict) -> str:
    return f" · {s['distance_km']:.1f} км" if s.get("distance_km") is not None else ""


def list_view(shelters: list[dict], ctx: str, page: int, meta: dict,
              settings: Settings) -> tuple[str, InlineKeyboardMarkup]:
    urg = {u["key"]: u for u in meta["urgency"]}
    pages = max(1, math.ceil(len(shelters) / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    chunk = shelters[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    cat, sub, oblast = parse_ctx(ctx)

    lines = [ctx_title(ctx, meta)]
    if cat is None:
        lines.append(" ".join(f"{u['emoji']} {u['title'].lower()}" for u in meta["urgency"]))
        if not settings.web_url_is_public:
            lines.append(f"\n🗺 Вебкарта: {escape(settings.web_url)}")
    lines.append("")
    lines.append(f"Знайдено притулків: <b>{len(shelters)}</b>" if shelters else texts.EMPTY_LIST)

    rows: list[list[IB]] = []
    if cat is None and settings.web_url_is_public:
        url = settings.web_url + (f"/?oblast={oblast}" if oblast else "")
        rows.append([IB(text="🗺 Відкрити інтерактивну карту", url=url)])
    if cat != "near":
        rows.append([IB(text=f"📍 Область: {oblast_title(meta, oblast)}", callback_data=f"op:{ctx}")])
    for s in chunk:
        label = f"{urg[s['urgency_level']]['emoji']} {s['name']} · {s['city']}{_dist(s)}"
        rows.append([IB(text=label[:60], callback_data=f"sh:{s['id']}:{ctx}:{page}")])
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(IB(text="◀️", callback_data=f"list:{ctx}:{page - 1}"))
        nav.append(IB(text=f"{page + 1}/{pages}", callback_data="noop"))
        if page < pages - 1:
            nav.append(IB(text="▶️", callback_data=f"list:{ctx}:{page + 1}"))
        rows.append(nav)
    suffix = f"@{oblast}" if oblast else ""
    if cat == "near":
        rows.append([IB(text="📋 Завдання поруч", callback_data="ntasks")])
    elif cat == "food":
        rows.append([IB(text="⬅️ До видів корму", callback_data=f"cat:food{suffix}")])
    elif cat is not None:
        rows.append([IB(text="⬅️ До категорій", callback_data=f"cat{suffix}")])
    rows.append([IB(text="🏠 Головне меню", callback_data="menu")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def link_icon(meta: dict, kind: str) -> str:
    return next((k["emoji"] for k in meta.get("link_kinds", []) if k["key"] == kind), "🔗")


def fundraiser_line(f: dict, meta: dict) -> str:
    kind = next((k for k in meta.get("fundraiser_kinds", []) if k["key"] == f["kind"]), {"emoji": "💛"})
    value = (f'<a href="{escape(f["value"], quote=True)}">{escape(_short(f["value"]))}</a>'
             if f["value"].startswith("http") else f"<code>{escape(f['value'])}</code>")
    note = f" ({escape(f['note'])})" if f.get("note") else ""
    return f"{kind['emoji']} {escape(f['title'])}: {value}{note}"


def shelter_card(s: dict, meta: dict) -> str:
    urg = next(u for u in meta["urgency"] if u["key"] == s["urgency_level"])
    cats = {c["key"]: c for c in meta["categories"]}

    city = s["city"] if s["city"].startswith(("с.", "смт", "м.")) else f"м. {s['city']}"
    location = ", ".join(p for p in (city, s.get("district"), s["address"]) if p)
    lines = [
        f"{urg['emoji']} <b>[{urg['title'].upper()}]</b>",
        f"🏠 <b>Притулок:</b> «{escape(s['name'])}»",
        f"📍 <b>Локація:</b> {escape(location)}" + (f" · {s['distance_km']:.1f} км від вас" if s.get("distance_km") else ""),
    ]
    if s.get("phone"):
        who = f" ({escape(s['contact_person'])})" if s.get("contact_person") else ""
        lines.append(f"📞 <b>Контакти:</b> {escape(s['phone'])}{who}")
    if s.get("links"):
        links = " · ".join(f'{link_icon(meta, l["kind"])} <a href="{escape(l["url"], quote=True)}">'
                           f'{escape(_short(l["url"]))}</a>' for l in s["links"])
        lines.append(f"🌐 <b>Соцмережі:</b> {links}")

    lines += [DIVIDER, "📋 <b>АКТУАЛЬНІ ПОТРЕБИ:</b>"]
    grouped: dict[str, list[str]] = {}
    for n in s["needs"]:
        mark = f" <i>(🙋 вже везуть: {n['pledges_active']})</i>" if n.get("pledges_active") else ""
        grouped.setdefault(n["category"], []).append(escape(n["text"]) + mark)

    has_any = False
    for key, c in cats.items():
        items = grouped.get(key, [])
        if items:
            lines.append(f"{c['emoji']} <b>{escape(c['title'])}:</b> " + "; ".join(items) + ".")
            has_any = True
    if not has_any:
        lines.append("Наразі всі потреби закриті 💚")

    if s.get("fundraisers"):
        lines += ["", "💛 <b>ЗБОРИ ТА РЕКВІЗИТИ:</b>"]
        lines += [fundraiser_line(f, meta) for f in s["fundraisers"]]
    if s.get("tasks"):
        lines += ["", "📋 <b>ВОЛОНТЕРСЬКІ ЗАВДАННЯ:</b>"]
        lines += [f"• {escape(t['title'])} — {escape(t['starts_at'])} ({t['taken']}/{t['slots']})" for t in s["tasks"][:5]]

    if s.get("verified_at"):
        lines += ["", f"🕓 Дані перевірено: {escape(s['verified_at'])}"]
    elif s.get("source") in ("osm", "web"):
        lines += ["", "⚠️ Дані з відкритих джерел, притулок ще не підтвердив їх. Перед візитом зателефонуйте."]
    return "\n".join(lines)


def card_kb(s: dict, ctx: str, page: int, settings: Settings, *, subscribed: bool = False,
            manages: bool = False) -> InlineKeyboardMarkup:
    rows = []
    first = []
    if settings.web_url_is_public:
        first.append(IB(text="🗺 На вебкарті", url=settings.shelter_url(s["id"])))
    first.append(IB(text="📞 Зв'язатися", callback_data=f"contact:{s['id']}"))
    rows.append(first)
    act = []
    if s["needs"]:
        act.append(IB(text="🙋 Беру потребу", callback_data=f"pl:{s['id']}"))
    if s.get("tasks"):
        act.append(IB(text=f"📋 Завдання ({len(s['tasks'])})", callback_data=f"st:{s['id']}"))
    if act:
        rows.append(act)
    for f in s.get("fundraisers", [])[:3]:
        if f["value"].startswith("https://"):
            rows.append([IB(text=f"💛 Підтримати: {f['title']}"[:60], url=f["value"])])
    rows.append([IB(text="🔕 Відписатися" if subscribed else "🔔 Підписатися на новини",
                    callback_data=f"sub:{s['id']}")])
    if manages:
        rows.append([IB(text="⚙️ Керувати притулком", callback_data=f"m:{s['id']}")])
    elif not s.get("has_manager"):
        rows.append([IB(text="🔑 Це мій притулок", callback_data=f"claim:{s['id']}")])
    rows.append([IB(text="⬅️ Назад до списку", callback_data=f"list:{ctx}:{page}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contacts_text(s: dict) -> str:
    lines = [f"📞 <b>Контакти притулку «{escape(s['name'])}»</b>", ""]
    if s.get("phone"):
        who = f" — {escape(s['contact_person'])}" if s.get("contact_person") else ""
        lines.append(f"Телефон: {escape(s['phone'])}{who}")
    lines.append(f"Адреса: {escape(', '.join(p for p in (s['city'], s.get('district'), s['address']) if p))}")
    lines.append(f'Маршрут: <a href="https://www.google.com/maps/dir/?api=1&amp;destination={s["lat"]},{s["lng"]}">'
                 "Google Maps</a>")
    for l in s.get("links", []):
        lines.append(f'<a href="{escape(l["url"], quote=True)}">{escape(_short(l["url"]))}</a>')
    lines += ["", "Перед візитом зателефонуйте, будь ласка, — уточніть, що зараз найактуальніше."]
    return "\n".join(lines)


def task_text(t: dict) -> str:
    free = t["slots"] - t["taken"]
    lines = [f"📋 <b>{escape(t['title'])}</b>", f"🏠 «{escape(t['shelter_name'])}»",
             f"🗓 {escape(t['starts_at'])}", f"👥 Вільних місць: {free} з {t['slots']}"]
    if t.get("distance_km") is not None:
        lines.append(f"📍 {t['distance_km']:.1f} км від вас")
    if t.get("description"):
        lines += ["", escape(t["description"])]
    return "\n".join(lines)


def tasks_list(tasks: list[dict], title: str, back: str) -> tuple[str, InlineKeyboardMarkup]:
    rows = [[IB(text=f"{t['starts_at'][5:]} · {t['title']} · {t['shelter_name']}"[:60],
                callback_data=f"task:{t['id']}")] for t in tasks[:20]]
    rows.append([IB(text="⬅️ Назад", callback_data=back)])
    text = title + ("\n\nОберіть завдання 👇" if tasks else "\n\nЗараз відкритих завдань немає 🙌")
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _short(url: str) -> str:
    return url.split("://", 1)[-1].removeprefix("www.").rstrip("/")
