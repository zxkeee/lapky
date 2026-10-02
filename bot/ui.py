"""Клавіатури та форматування картки притулку (за шаблоном Софії, Блок Б)."""
import math
from html import escape as _escape


def escape(s: str, quote: bool = False) -> str:
    return _escape(s, quote=quote)

from aiogram.types import (
    InlineKeyboardButton as IB, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup,
)

from . import texts
from .config import Settings

PAGE_SIZE = 8
DIVIDER = "━━━━━━━━━━━━━━━━━━━━"


# ---------- контекст списку у callback_data ----------
# ctx: "all" | "<category>" | "food.<subcategory>"   (callback_data ≤ 64 байти)

def parse_ctx(ctx: str) -> tuple[str | None, str | None]:
    if ctx == "all":
        return None, None
    cat, _, sub = ctx.partition(".")
    return cat, (sub or None)


def ctx_title(ctx: str, meta: dict) -> str:
    cat, sub = parse_ctx(ctx)
    if cat is None:
        return "🗺 <b>Усі притулки</b> — від найтерміновіших до стабільних"
    c = next(c for c in meta["categories"] if c["key"] == cat)
    title = f"{c['emoji']} <b>{escape(c['title'])}</b>"
    if sub:
        s = next(s for s in c.get("subcategories", []) if s["key"] == sub)
        title += f" → {s['emoji']} {escape(s['title'])}"
    return title


# ---------- клавіатури ----------

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.BTN_ALL), KeyboardButton(text=texts.BTN_FILTER)],
            [KeyboardButton(text=texts.BTN_HELP), KeyboardButton(text=texts.BTN_ABOUT)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def onboarding_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[IB(text="✅ Зрозуміло!", callback_data="ok")]])


def categories_kb(meta: dict) -> InlineKeyboardMarkup:
    rows = [[IB(text=f"{c['emoji']} {c['title']} ({c['hint']})", callback_data=f"cat:{c['key']}")]
            for c in meta["categories"]]
    rows.append([IB(text="🏠 Головне меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def food_kb(meta: dict) -> InlineKeyboardMarkup:
    food = next(c for c in meta["categories"] if c["key"] == "food")
    subs = [IB(text=f"{s['emoji']} {s['title']}", callback_data=f"list:food.{s['key']}:0")
            for s in food["subcategories"]]
    rows = [subs[i:i + 2] for i in range(0, len(subs), 2)]
    rows.append([IB(text="🍽 Показати весь корм та ліки", callback_data="list:food:0")])
    rows.append([IB(text="⬅️ До категорій", callback_data="cat")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [IB(text="🔍 Обрати категорію", callback_data="cat")],
        [IB(text="🗺 Усі притулки", callback_data="list:all:0")],
    ])


def about_kb(settings: Settings) -> InlineKeyboardMarkup:
    rows = []
    if settings.web_url_is_public:
        rows.append([IB(text="🗺 Відкрити вебкарту", url=settings.web_url)])
    rows.append([IB(text="➕ Додати притулок", callback_data="add")])
    rows.append([IB(text="⬅️ Назад до головного меню", callback_data="menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def list_view(shelters: list[dict], ctx: str, page: int, meta: dict,
              settings: Settings) -> tuple[str, InlineKeyboardMarkup]:
    urg = {u["key"]: u for u in meta["urgency"]}
    pages = max(1, math.ceil(len(shelters) / PAGE_SIZE))
    page = min(max(page, 0), pages - 1)
    chunk = shelters[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = [ctx_title(ctx, meta)]
    if ctx == "all":
        lines.append(" ".join(f"{u['emoji']} {u['title'].lower()}" for u in meta["urgency"]))
        if not settings.web_url_is_public:
            lines.append(f"\n🗺 Вебкарта: {escape(settings.web_url)}")
    lines.append("")
    lines.append(f"Знайдено притулків: <b>{len(shelters)}</b>" if shelters else texts.EMPTY_LIST)

    rows: list[list[IB]] = []
    if ctx == "all" and settings.web_url_is_public:
        rows.append([IB(text="🗺 Відкрити інтерактивну карту", url=settings.web_url)])
    for s in chunk:
        label = f"{urg[s['urgency_level']]['emoji']} {s['name']} · {s['city']}"
        rows.append([IB(text=label[:60], callback_data=f"sh:{s['id']}:{ctx}:{page}")])
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(IB(text="◀️", callback_data=f"list:{ctx}:{page - 1}"))
        nav.append(IB(text=f"{page + 1}/{pages}", callback_data="noop"))
        if page < pages - 1:
            nav.append(IB(text="▶️", callback_data=f"list:{ctx}:{page + 1}"))
        rows.append(nav)
    cat, _ = parse_ctx(ctx)
    if cat == "food":
        rows.append([IB(text="⬅️ До видів корму", callback_data="cat:food")])
    elif cat is not None:
        rows.append([IB(text="⬅️ До категорій", callback_data="cat")])
    rows.append([IB(text="🏠 Головне меню", callback_data="menu")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


# ---------- картка притулку ----------

def shelter_card(s: dict, meta: dict) -> str:
    urg = next(u for u in meta["urgency"] if u["key"] == s["urgency_level"])
    cats = {c["key"]: c for c in meta["categories"]}

    city = s["city"] if s["city"].startswith(("с.", "смт", "м.")) else f"м. {s['city']}"
    location = ", ".join(p for p in (city, s.get("district"), s["address"]) if p)
    lines = [
        f"{urg['emoji']} <b>[{urg['title'].upper()}]</b>",
        f"🏠 <b>Притулок:</b> «{escape(s['name'])}»",
        f"📍 <b>Локація:</b> {escape(location)}",
    ]
    if s.get("phone"):
        who = f" ({escape(s['contact_person'])})" if s.get("contact_person") else ""
        lines.append(f"📞 <b>Контакти:</b> {escape(s['phone'])}{who}")
    if s.get("social_links"):
        links = ", ".join(f'<a href="{escape(u, quote=True)}">{escape(_short(u))}</a>' for u in s["social_links"])
        lines.append(f"🌐 <b>Соцмережі:</b> {links}")

    lines += [DIVIDER, "📋 <b>АКТУАЛЬНІ ПОТРЕБИ:</b>"]
    grouped: dict[str, list[str]] = {}
    for n in s["needs"]:
        grouped.setdefault(n["category"], []).append(escape(n["text"]))

    has_any = False
    for key, c in cats.items():
        items = grouped.get(key, [])
        if key == "finance":
            req = ""
            if s.get("requisites"):
                bank = f" ({escape(s['bank'])})" if s.get("bank") else ""
                r = s["requisites"]
                req = (f'<a href="{escape(r, quote=True)}">{escape(_short(r))}</a>' if r.startswith("http")
                       else f"<code>{escape(r)}</code>") + bank
            parts = [p for p in [req, *items] if p]
            if parts:
                lines.append(f"{c['emoji']} <b>Фінанси:</b> " + "; ".join(parts))
                has_any = True
        elif items:
            lines.append(f"{c['emoji']} <b>{escape(c['title'])}:</b> " + "; ".join(items) + ".")
            has_any = True
    if not has_any:
        lines.append("Наразі всі потреби закриті 💚")

    if s.get("verified_at"):
        lines += ["", f"🕓 Дані перевірено: {escape(s['verified_at'])}"]
    return "\n".join(lines)


def card_kb(s: dict, ctx: str, page: int, settings: Settings) -> InlineKeyboardMarkup:
    first = []
    if settings.web_url_is_public:
        first.append(IB(text="🗺 Показати на вебкарті", url=settings.shelter_url(s["id"])))
    first.append(IB(text="📞 Зв'язатися з притулком", callback_data=f"contact:{s['id']}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        first,
        [IB(text="⬅️ Назад до списку", callback_data=f"list:{ctx}:{page}")],
    ])


def contacts_text(s: dict) -> str:
    lines = [f"📞 <b>Контакти притулку «{escape(s['name'])}»</b>", ""]
    if s.get("phone"):
        who = f" — {escape(s['contact_person'])}" if s.get("contact_person") else ""
        lines.append(f"Телефон: {escape(s['phone'])}{who}")
    lines.append(f"Адреса: {escape(', '.join(p for p in (s['city'], s.get('district'), s['address']) if p))}")
    lines.append(f'Маршрут: <a href="https://www.google.com/maps/dir/?api=1&amp;destination={s["lat"]},{s["lng"]}">'
                 "Google Maps</a>")
    for u in s.get("social_links", []):
        lines.append(f'<a href="{escape(u, quote=True)}">{escape(_short(u))}</a>')
    lines += ["", "Перед візитом зателефонуйте, будь ласка, — уточніть, що зараз найактуальніше."]
    return "\n".join(lines)


def _short(url: str) -> str:
    return url.split("://", 1)[-1].removeprefix("www.").rstrip("/")
