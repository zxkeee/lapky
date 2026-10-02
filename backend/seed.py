"""Реальні притулки Києва та області (зібрано з офіційних сайтів і ЗМІ, жовтень 2026).

Джерело кожного запису — у полі source_url, деталі й що треба перевірити — docs/DATA_SOURCES.md.
Рівень терміновості виставлено командою за описом потреб (не самими притулками).
Координати — приблизні, Назар уточнює на тижні 6.

    python -m backend.seed           # заповнити, якщо база порожня
    python -m backend.seed --reset   # стерти все й заповнити заново
"""
import json
import sys

from .db import connect, init_db

N = lambda cat, text, sub=None: {"category": cat, "subcategory": sub, "text": text}  # noqa: E731

SHELTERS = [
    {
        "name": "SOS", "urgency_level": "red",
        "city": "Київ", "district": "Голосіївський район (Пирогово)",
        "address": "вул. Пирогівський шлях, 186",
        "lat": 50.3319, "lng": 30.5298,
        "phone": "+380 97 393 64 68", "contact_person": "Наталія Андріївна (директорка)",
        "social_links": ["https://www.sos-shelter.kiev.ua", "https://www.facebook.com/AnimalShelterSOS"],
        "source_url": "https://www.sos-shelter.kiev.ua/help", "verified_at": "2026-10-02",
        "needs": [
            N("housing", "Старі светри, килими, рушники, матраци, покривала — на підстилки"),
            N("housing", "Дрова — для обігріву й приготування їжі"),
            N("food", "Крупи та макарони — усе, крім перловки й гороху", "adult"),
            N("food", "М'який корм і смаколики для котів", "adult"),
            N("food", "Орідерміл — гостро потрібен", "medical"),
            N("food", "Засоби від бліх і кліщів (краплі, спреї, нашийники)", "medical"),
            N("food", "Бинти, шприци 0,5 і 2 мл, хірургічні рукавички", "medical"),
            N("care", "Старі миски, каструлі, відра, баки"),
            N("care", "Іграшки для собак і котів, тенісні м'ячики (без ватного наповнювача)"),
            N("care", "Кігтеточки (можна б/у в доброму стані)"),
            N("volunteer", "Доставка допомоги: Нова Пошта №1, Пирогівський шлях, 135 — Оксана, +380 97 386 98 53"),
            N("volunteer", "Притулок переповнений — терміново шукають родини для цуценят"),
        ],
    },
    {
        "name": "Gostomel Shelter", "urgency_level": "orange",
        "city": "Гостомель", "district": "Бучанський район",
        "address": "вул. Свято-Покровська, 213 (кінцева «Кімерка»)",
        "lat": 50.5920, "lng": 30.2700,
        "phone": "+380 50 597 89 31", "contact_person": None,
        "social_links": ["https://www.gostomelshelter.com", "https://www.instagram.com/gostomel.shelter/",
                         "https://t.me/gostomelanimalshelter"],
        "requisites": "https://send.monobank.ua/jar/5Unkjm8SWr", "bank": "monobank, банка на корм",
        "source_url": "https://www.gostomelshelter.com/актуальні-потреби-притулку", "verified_at": "2026-10-02",
        "needs": [
            N("housing", "Дрова — 120–140 кубів на холодний період"),
            N("food", "Сухий корм або м'ясо (не кістки й не жир) — 4–5 тонн на місяць", "adult"),
            N("food", "Крупа — 2 тонни на місяць", "adult"),
            N("food", "Ліверна ковбаса та сосиски", "adult"),
            N("food", "Вологий корм для котів", "adult"),
            N("food", "Сухий корм для кошенят", "kids"),
            N("food", "Royal Canin Hypoallergenic для собак (30 кг/міс), Royal Canin Mobility", "medical"),
            N("food", "Вакцини Nobivac (Tricat, DHPPi+L), Біокан R", "medical"),
            N("food", "Bravecto, краплі Селафорт, гепатопротектори, вітаміни", "medical"),
            N("care", "Деревний наповнювач для котів — 30 пакунків по 10 кг"),
            N("care", "Одноразові пелюшки — 1000 шт. на місяць"),
            N("care", "Побутова хімія: Domestos, Mr. Proper, Fairy, пральний порошок, губки"),
            N("finance", "Оплата електроенергії та бензину для авто й генераторів"),
            N("volunteer", "Волонтерство на постійній основі — форма на сайті притулку"),
        ],
    },
    {
        "name": "Сіріус", "urgency_level": "orange",
        "city": "с. Федорівка", "district": "Вишгородський район",
        "address": "вул. Миру, 2",
        "lat": 50.7850, "lng": 30.2550,
        "phone": "+380 67 656 70 98", "contact_person": "Олександра Мезінова (засновниця)",
        "social_links": ["https://www.dogcat.com.ua/ua", "https://www.facebook.com/Shelter.SIRIUS"],
        "source_url": "https://life.pravda.com.ua/society/na-kijivshchini-goriv-pritulok-sirius-video-316763/",
        "verified_at": None,
        "needs": [
            N("housing", "Будматеріали й інструменти — відновлення вольєрів після пожежі"),
            N("food", "Корм для собак", "adult"),
            N("finance", "Бензин для генератора"),
            N("finance", "Щомісячна підписка на годування котів (на сайті притулку)"),
            N("volunteer", "Посилки: Нова Пошта №1 у Федорівці, на ім'я Олександри Мезінової"),
        ],
    },
    {
        "name": "В добрі руки", "urgency_level": "orange",
        "city": "Вишневе", "district": "Бучанський район",
        "address": "вул. Святошинська, 13 (юридична адреса ГО)",
        "lat": 50.3880, "lng": 30.3600,
        "phone": "+380 98 177 84 34", "contact_person": "дзвінки 10:00–20:00",
        "social_links": ["https://dobri-ruky.com.ua", "https://www.facebook.com/Dobriruky/",
                         "https://t.me/vdobriruky_kyiv"],
        "requisites": "UA123052990000026006010110385", "bank": "ПриватБанк, ГО «У добрі руки», ЄДРПОУ 38379580",
        "source_url": "https://dobri-ruky.com.ua/help/", "verified_at": "2026-10-02",
        "needs": [
            N("housing", "Старі ковдри, пледи, постільне, рушники"),
            N("housing", "Куртки для співробітників"),
            N("food", "Крупи (окрім перлової)", "adult"),
            N("food", "Корм для собак і котів — сухий, напіввологий, вологий", "adult"),
            N("food", "Цефтріаксон 1 г, гептрал і квамател ін'єкційні, смекта, катетери G22–G26", "medical"),
            N("food", "Синулокс, Рікарфа, Катозал, Тіопротектін, обробка від паразитів Palladium", "medical"),
            N("care", "Іграшки, нашийники, брезентові повідці, переноски, миски, лотки, дряпки"),
            N("care", "Пелюшки 60×60 і 60×90, бинти, шприци 2 і 5 мл, рукавички S/M"),
            N("care", "Господарське: пральний порошок, Domestos, швабри, міцні сміттєві пакети"),
            N("volunteer", "Автодопомога: перевезення кормів, будматеріалів, тварин"),
            N("volunteer", "Прибирання, вигул і соціалізація тварин (проєкт WowBigWalk)"),
        ],
    },
    {
        "name": "Best Friends", "urgency_level": "white",
        "city": "с. Фасова", "district": "Бучанський район",
        "address": "на базі ГО «Зооцентр Ковчег»",
        "lat": 50.3700, "lng": 29.6700,
        "phone": None, "contact_person": None,
        "social_links": ["https://www.priiut-best-friends.com.ua", "https://www.facebook.com/priutbestfriends"],
        "source_url": "https://unn.ua/news/za-try-dni-liudy-prynesly-dvi-tonny-kormu-yak-zhyve-prytulok-dlia-tvaryn-best-friends-shcho-buv-zruinovanyi-vorozhym-obstrilom",
        "verified_at": None,
        "needs": [
            N("food", "Корм для котів і собак", "adult"),
            N("finance", "Відбудова вольєрів, зруйнованих обстрілами 2022 року"),
            N("volunteer", "Вигул тварин — притулок біля лісу, можна гуляти в лісі"),
        ],
    },
    {
        "name": "Виставковий центр (ВДНГ)", "urgency_level": "green",
        "city": "Київ", "district": "Голосіївський район",
        "address": "ВДНГ (Експоцентр України), павільйон 16",
        "lat": 50.3820, "lng": 30.4790,
        "phone": "+380 67 532 22 82", "contact_person": "КП «Київська міська лікарня ветмедицини»",
        "social_links": ["https://www.facebook.com/shelter.vdng"],
        "source_url": "https://kyivcity.gov.ua/news/News_28_sichnya_kiyan_zaproshuyut_vzyati_uchast_u_dni_vidkritikh_dverey_timchasovogo_pritulku_dlya_tvarin_na_vdng/",
        "verified_at": "2024-01-26",
        "needs": [
            N("volunteer", "Прийти погуляти з тваринами — допомагає їм соціалізуватися"),
            N("volunteer", "Адопція через співбесіду зі Службою адопції (грошей і речей притулок не приймає)"),
        ],
    },
    {
        "name": "Відродження", "urgency_level": "white",
        "city": "с. Деремезна", "district": "Обухівський район",
        "address": "вул. Гагаріна, 14",
        "lat": 50.1770, "lng": 30.5960,
        "phone": None, "contact_person": None,
        "social_links": ["https://www.facebook.com/deremezna.pets"],
        "source_url": "https://vikna.tv/styl-zhyttya/prytulky-dlya-tvaryn-kyyeva-ta-kyyivskoyi-oblasti/",
        "verified_at": "2023-02-14",
        "needs": [
            N("food", "Корм для котів і собак", "adult"),
            N("finance", "Утримання тварин і ремонт приміщень"),
            N("volunteer", "Робочі руки: будувати й лагодити вольєри"),
        ],
    },
    {
        "name": "Хатуль Мадан", "urgency_level": "orange",
        "city": "Київ", "district": None,
        "address": "вул. Володимирська, 82в",
        "lat": 50.4390, "lng": 30.5130,
        "phone": "+380 73 412 84 42", "contact_person": None,
        "social_links": ["https://hatul-madan.org", "https://www.instagram.com/hatulmadanshelter",
                         "https://www.facebook.com/HatulMadanShelter/"],
        "requisites": "UA153052990000026003035023137", "bank": "ПриватБанк, ГО «Хатуль Мадан», ЄДРПОУ 44749493",
        "source_url": "https://hatul-madan.org/help-us", "verified_at": "2026-10-02",
        "needs": [
            N("finance", "Утримання й лікування тварин, евакуйованих із зон бойових дій"),
            N("finance", "Кураторство: щомісячна підтримка конкретної тварини"),
            N("volunteer", "Прибирання вольєрів, годування й вигул — можна прийти будь-якого дня"),
            N("volunteer", "Собаки майже не знаходять родин — потрібна адопція й поширення"),
        ],
    },
    {
        "name": "Patron Pet Center", "urgency_level": "white",
        "city": "Київ", "district": "Голосіївський район",
        "address": "ВДНГ (Експоцентр України), павільйон 11, просп. Академіка Глушкова, 1",
        "lat": 50.3815, "lng": 30.4760,
        "phone": None, "contact_person": None,
        "social_links": [],
        "source_url": "https://life.pravda.com.ua/society/yak-centr-adopciji-patron-u-kiyevi-daruye-tvarinam-z-frontu-nove-zhittya-305724/",
        "verified_at": "2025-09-25",
        "needs": [
            N("volunteer", "Вечірній вигул собак — анкета й інструктаж на місці"),
            N("volunteer", "Допомога з прибиранням за графіком центру"),
            N("finance", "Власна ветклініка — зараз ветбригади залучають ззовні, це дорого"),
        ],
    },
    {
        "name": "Rifugio Italia KJ2", "urgency_level": "orange",
        "city": "с. Лісовичі", "district": "Київська обл. (північ)",
        "address": "притулок Андреа Чистерніно",
        "lat": 50.7500, "lng": 30.4000,
        "phone": None, "contact_person": "Андреа Чистерніно (засновник)",
        "social_links": [],
        "source_url": "https://uanimals.org/media/en/reportazhi-en/rifudzhio/",
        "verified_at": "2025-02-27",
        "needs": [
            N("food", "Сухий корм для собак і котів", "adult"),
            N("food", "Яблука, морква, гарбуз — для великих тварин", "adult"),
            N("housing", "Дрова — дров'яні печі гріють кошенят і цуценят"),
            N("finance", "Утримання близько 500 тварин"),
        ],
    },
]

FIELDS = ["name", "urgency_level", "city", "district", "address", "lat", "lng", "phone",
          "contact_person", "social_links", "requisites", "bank", "source_url", "verified_at"]


def seed(reset: bool = False) -> int:
    init_db()
    conn = connect()
    try:
        if reset:
            conn.execute("DELETE FROM needs")
            conn.execute("DELETE FROM shelters")
            conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('needs', 'shelters')")
        elif conn.execute("SELECT COUNT(*) FROM shelters").fetchone()[0]:
            print("База вже не порожня — пропускаю (використайте --reset).")
            return 0
        for s in SHELTERS:
            row = {f: s.get(f) for f in FIELDS}
            row["social_links"] = json.dumps(s.get("social_links", []), ensure_ascii=False)
            cur = conn.execute(
                f"INSERT INTO shelters ({', '.join(FIELDS)}) VALUES ({', '.join('?' * len(FIELDS))})",
                [row[f] for f in FIELDS],
            )
            for n in s["needs"]:
                conn.execute(
                    "INSERT INTO needs (shelter_id, category, subcategory, text) VALUES (?, ?, ?, ?)",
                    (cur.lastrowid, n["category"], n["subcategory"], n["text"]),
                )
        conn.commit()
        print(f"Додано притулків: {len(SHELTERS)}.")
        return len(SHELTERS)
    finally:
        conn.close()


if __name__ == "__main__":
    seed(reset="--reset" in sys.argv)
