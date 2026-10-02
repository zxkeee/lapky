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
