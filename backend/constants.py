"""Довідники, спільні для сервера, карти й бота (віддаються через /api/meta)."""

URGENCY = [
    {"key": "red", "emoji": "🔴", "title": "Критичний рівень", "color": "#D7263D"},
    {"key": "orange", "emoji": "🟠", "title": "Високий рівень", "color": "#F08A24"},
    {"key": "white", "emoji": "⚪", "title": "Звичайні потреби", "color": "#FFFFFF"},
    {"key": "green", "emoji": "🟢", "title": "Потреби закриті", "color": "#3BA55C"},
]
URGENCY_ORDER = {u["key"]: i for i, u in enumerate(URGENCY)}

FOOD_SUBCATEGORIES = [
    {"key": "kids", "emoji": "🍼", "title": "Для малюків (кошенят/цуценят)"},
    {"key": "adult", "emoji": "🐕", "title": "Для дорослих тварин"},
    {"key": "sterilized", "emoji": "🐈", "title": "Для стерилізованих"},
    {"key": "medical", "emoji": "💊", "title": "Лікувальний / спецкорм"},
]

CATEGORIES = [
    {"key": "housing", "emoji": "🩶", "title": "Проживання", "hint": "житло, ковдри, одяг", "color": "#8E9196"},
    {"key": "food", "emoji": "🤎", "title": "Харчування та здоров'я", "hint": "корм, ліки", "color": "#8B5A3C",
     "subcategories": FOOD_SUBCATEGORIES},
    {"key": "care", "emoji": "🩷", "title": "Догляд та дозвілля", "hint": "іграшки, повідці", "color": "#E07A9B"},
    {"key": "finance", "emoji": "💛", "title": "Фінансова підтримка", "hint": "реквізити, збори", "color": "#E5B800"},
    {"key": "volunteer", "emoji": "💜", "title": "Волонтерство та авто", "hint": "вигул, автодопомога", "color": "#8A5CC7"},
]
CATEGORY_ORDER = {c["key"]: i for i, c in enumerate(CATEGORIES)}

# ---------- регіони ----------
# key — стабільний ідентифікатор (у БД, URL і callback_data бота), iso — код ISO 3166-2 (для імпорту з OSM)
OBLASTS = [
    {"key": "kyiv", "title": "м. Київ", "iso": "UA-30"},
    {"key": "kyivska", "title": "Київська", "iso": "UA-32"},
    {"key": "vinnytska", "title": "Вінницька", "iso": "UA-05"},
    {"key": "volynska", "title": "Волинська", "iso": "UA-07"},
    {"key": "dnipropetrovska", "title": "Дніпропетровська", "iso": "UA-12"},
    {"key": "donetska", "title": "Донецька", "iso": "UA-14"},
    {"key": "zhytomyrska", "title": "Житомирська", "iso": "UA-18"},
    {"key": "zakarpatska", "title": "Закарпатська", "iso": "UA-21"},
    {"key": "zaporizka", "title": "Запорізька", "iso": "UA-23"},
    {"key": "ivano-frankivska", "title": "Івано-Франківська", "iso": "UA-26"},
    {"key": "kirovohradska", "title": "Кіровоградська", "iso": "UA-35"},
    {"key": "luhanska", "title": "Луганська", "iso": "UA-09"},
    {"key": "lvivska", "title": "Львівська", "iso": "UA-46"},
    {"key": "mykolaivska", "title": "Миколаївська", "iso": "UA-48"},
    {"key": "odeska", "title": "Одеська", "iso": "UA-51"},
    {"key": "poltavska", "title": "Полтавська", "iso": "UA-53"},
    {"key": "rivnenska", "title": "Рівненська", "iso": "UA-56"},
    {"key": "sumska", "title": "Сумська", "iso": "UA-59"},
    {"key": "ternopilska", "title": "Тернопільська", "iso": "UA-61"},
    {"key": "kharkivska", "title": "Харківська", "iso": "UA-63"},
    {"key": "khersonska", "title": "Херсонська", "iso": "UA-65"},
    {"key": "khmelnytska", "title": "Хмельницька", "iso": "UA-68"},
    {"key": "cherkaska", "title": "Черкаська", "iso": "UA-71"},
    {"key": "chernivetska", "title": "Чернівецька", "iso": "UA-77"},
    {"key": "chernihivska", "title": "Чернігівська", "iso": "UA-74"},
    {"key": "crimea", "title": "АР Крим", "iso": "UA-43"},
    {"key": "sevastopol", "title": "м. Севастополь", "iso": "UA-40"},
]
OBLAST_KEYS = [o["key"] for o in OBLASTS]
OBLAST_BY_ISO = {o["iso"]: o["key"] for o in OBLASTS}
OBLAST_TITLE = {o["key"]: o["title"] for o in OBLASTS}

SHELTER_STATUSES = ["published", "pending", "hidden"]
SHELTER_SOURCES = ["seed", "admin", "osm", "web", "application"]

# ---------- соцмережі та збори ----------
LINK_KINDS = [
    {"key": "website", "emoji": "🌐", "title": "Сайт"},
    {"key": "facebook", "emoji": "📘", "title": "Facebook"},
    {"key": "instagram", "emoji": "📸", "title": "Instagram"},
    {"key": "telegram", "emoji": "✈️", "title": "Telegram"},
    {"key": "tiktok", "emoji": "🎵", "title": "TikTok"},
    {"key": "youtube", "emoji": "▶️", "title": "YouTube"},
    {"key": "viber", "emoji": "💬", "title": "Viber"},
    {"key": "other", "emoji": "🔗", "title": "Посилання"},
]
LINK_KIND_KEYS = [k["key"] for k in LINK_KINDS]

FUNDRAISER_KINDS = [
    {"key": "monobank_jar", "emoji": "🫙", "title": "Банка monobank", "is_url": True},
    {"key": "privat", "emoji": "💚", "title": "ПриватБанк", "is_url": True},
    {"key": "paypal", "emoji": "🅿️", "title": "PayPal", "is_url": True},
    {"key": "patreon", "emoji": "🧡", "title": "Patreon", "is_url": True},
    {"key": "iban", "emoji": "🏦", "title": "IBAN", "is_url": False},
    {"key": "card", "emoji": "💳", "title": "Картка", "is_url": False},
    {"key": "other", "emoji": "💛", "title": "Інший спосіб", "is_url": False},
]
FUNDRAISER_KIND_KEYS = [k["key"] for k in FUNDRAISER_KINDS]
URL_FUNDRAISER_KINDS = {k["key"] for k in FUNDRAISER_KINDS if k["is_url"]}

# ---------- волонтерство ----------
PLEDGE_STATUSES = ["active", "done", "cancelled"]
TASK_STATUSES = ["open", "closed"]
APPLICATION_KINDS = ["new_shelter", "claim"]
APPLICATION_STATUSES = ["pending", "approved", "rejected"]
USER_ROLES = ["volunteer", "admin"]

# повністю окуповані території: притулки звідти не імпортуємо й не показуємо
# (частково окуповані області, як-от Донецька, — точково, адмін ставить status=hidden)
OCCUPIED_OBLASTS = {"crimea", "sevastopol", "luhanska"}
