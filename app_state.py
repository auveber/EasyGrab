# -*- coding: utf-8 -*-
"""
Общее состояние приложения EasyGrab.

Здесь хранится всё, что должно быть видно сразу нескольким окнам
(главному окну, окну входа, окну аккаунтов) — статус входа по платформам,
список аккаунтов, версия приложения. Плюс простое чтение/запись
локальных JSON-файлов настроек, без внешних зависимостей.

ВАЖНО ДЛЯ БЭКЕНД-РАЗРАБОТКИ (см. README.md):
Реальный сбор метрик (YouTube Data API v3 / Instagram / TikTok) сюда
не входит — см. mock_backend.py, там ровно одна функция, которую нужно
заменить на настоящие вызовы.
"""
import json
import os

import build_info

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION_FILE = os.path.join(HERE, "session.json")
ACCOUNTS_FILE = os.path.join(HERE, "accounts.json")

APP_NAME = "EasyGrab"

# Стадия зрелости — единственное, что задаётся руками: это решение о продукте,
# а не факт, который можно вычислить.
#   pre-alpha — только UI; alpha — собирается хотя бы одна площадка;
#   beta — все три; release — законченный проект.
APP_PHASE = "beta"

# Номер сборки и дата считаются сами по отпечатку исходников — см. build_info.py.
# Раньше дата была константой и отстала на пять дней, потому что про неё
# забывали. Теперь забывать нечего.
_BUILD, APP_BUILD_DATE = build_info.resolve()
APP_STAGE = "%s 0.%d" % (APP_PHASE, _BUILD)

# Авторство — показывается в окне «О программе» (клик по названию в шапке).
# DEVELOPER_URL_APP пробуется первым: если на устройстве стоит Telegram,
# откроется он, а не браузер.
DEVELOPER_CONTACT = "t.me/auveber"
DEVELOPER_URL = "https://t.me/auveber"
DEVELOPER_URL_APP = "tg://resolve?domain=auveber"

# Использованные библиотеки и их лицензии — сверено с метаданными
# установленных пакетов, а не по памяти. Показывается в окне «О программе».
LIBRARIES = (
    ("CustomTkinter", "MIT", "https://github.com/TomSchimansky/CustomTkinter"),
    ("yt-dlp", "Unlicense", "https://github.com/yt-dlp/yt-dlp"),
    ("instagrapi", "MIT", "https://github.com/subzeroid/instagrapi"),
    ("instaloader", "MIT", "https://github.com/instaloader/instaloader"),
    ("browser_cookie3", "LGPL-3.0", "https://github.com/borisbabic/browser_cookie3"),
    ("openpyxl", "MIT", "https://foss.heptapod.net/openpyxl/openpyxl"),
    ("ReportLab", "BSD", "https://www.reportlab.com/"),
    ("Pillow", "MIT-CMU", "https://github.com/python-pillow/Pillow"),
    ("Requests", "Apache-2.0", "https://github.com/psf/requests"),
    ("Pydantic", "MIT", "https://github.com/pydantic/pydantic"),
    ("Python", "PSF", "https://www.python.org/"),
)

# Показывается по значку ⓘ рядом со строкой про библиотеки. Первым абзацем —
# суть, ниже перечень с лицензиями: MIT и BSD требуют указывать авторство
# при распространении, и список это требование закрывает.
# Подсказка к строке с версией yt-dlp. Главное, что человек должен понять:
# тихого обновления нет, но и следить за версией самому не нужно.
YTDLP_HINT = (
    "yt-dlp — движок, которым собирается TikTok. Его номер версии и есть дата "
    "сборки: 2026.07.04 — это 4 июля 2026.\n\n"
    "АВТООБНОВЛЕНИЕ ЕСТЬ, но не молчаливое.\n\n"
    "При каждом запуске приложение сверяет установленную версию с последней "
    "стабильной. Если вышла новее — показывает окно с выбором: обновиться "
    "или остаться на текущей. Спрашивает при СТАРТЕ приложения и только там: "
    "открытие других окон вопрос не повторяет.\n\n"
    "Почему не обновляем молча: вы сравниваете цифры день ко дню. Если движок "
    "сменит версию сам и числа поедут, будет не отличить просадку каналов "
    "от смены версии. К тому же новая версия ломается не реже, чем чинит.\n\n"
    "Обновление не требует перезапуска: yt-dlp вызывается отдельным процессом, "
    "поэтому следующий же сбор возьмёт новую версию."
)

LIBRARIES_HINT = (
    "Программа использует сторонние библиотеки и ресурсы, включая ИИ-среды "
    "и инструменты для разработки.\n\n"
    + "\n".join("%s — %s" % (name, lic) for name, lic, _url in LIBRARIES)
)

# Показывается по значку ⓘ в окне «О программе». Задача — предупредить,
# не запугивая: человек должен понимать цену автоматизации заранее.
# Отдельно про Instagram: он ведёт себя иначе, чем YouTube и TikTok, и человек
# должен понимать это до первого сбора, а не по факту заблокированного аккаунта.
IG_STABILITY_HINT = (
    "Instagram — самая нестабильная из трёх площадок. YouTube и TikTok "
    "собираются ровно и предсказуемо, Instagram — нет.\n\n"
    "Почему: у него нет открытого доступа к данным, и любой сбор идёт через "
    "вход под аккаунтом. Instagram активно ищет автоматизацию и ограничивает "
    "такие аккаунты — сначала притормаживает запросы, потом присылает "
    "предупреждение, потом может отключить.\n\n"
    "ДВА СПОСОБА СБОРА\n\n"
    "1) Полный вход — логин и пароль. Просмотры приходят пачкой из вкладки "
    "Reels: один запрос на профиль. Данных больше, нагрузка та же. "
    "Рекомендуемый способ.\n\n"
    "2) Вход из браузера — без пароля. Вкладка Reels недоступна, поэтому "
    "просмотров не будет: только лайки и комментарии, тоже один запрос "
    "на профиль. Легче для аккаунта, но данных меньше.\n\n"
    "Есть и третий режим — добирать просмотры по одному запросу на каждый "
    "ролик при входе из браузера. Он ВЫКЛЮЧЕН по умолчанию: на живой проверке "
    "восемь запросов подряд по каждому профилю привели к предупреждению "
    "об автоматизации уже на первом сборе. Включается вручную в "
    "backend_instagram.py, на свой страх.\n\n"
    "Практика: собирайте Instagram раз в сутки, охватом «7 роликов», "
    "и держите наготове запасной бёрнер."
)

# Текст окна, которое всплывает перед сбором, если включён Instagram.
# Спокойно и по делу: не отговариваем, а даём принять решение осознанно.
IG_CONFIRM_TITLE = "Instagram собирается экспериментально"
IG_CONFIRM_TEXT = (
    "Сбор Instagram работает нестабильно — в отличие от YouTube и TikTok.\n\n"
    "У Instagram нет открытого доступа к данным: сбор идёт через вход под "
    "аккаунтом, а автоматизацию площадка активно ищет. Аккаунт-сборщик может "
    "получить ограничение частоты запросов, предупреждение или блокировку.\n\n"
    "Что это значит на практике:\n"
    "• собраться может не всё — часть профилей вернёт ошибку;\n"
    "• на рабочие аккаунты это никак не влияет, под риском только сборщик;\n"
    "• аккаунт-сборщик расходный: если его заблокируют, заведите новый.\n\n"
    "YouTube и TikTok в этом же сборе отработают как обычно."
)

RISK_HINT = (
    "Любой аккаунт, через который идёт автоматический сбор, рано или поздно "
    "может получить ограничение или блокировку. Это обычная плата за "
    "автоматизацию рутины, а не поломка приложения.\n\n"
    "Важно: чтение публичных страниц НЕ вредит тем, кого читают. Под риском "
    "только сам аккаунт-сборщик.\n\n"
    "Как продлить ему жизнь:\n"
    "• собирать раз в сутки, а не по десять раз в день;\n"
    "• для сбора использовать отдельный аккаунт-бёрнер, заведённый только "
    "для просмотра;\n"
    "• не входить в рабочие аккаунты с того же устройства, где идёт сбор;\n"
    "• не связывать почты и телефоны рабочих аккаунтов и бёрнера;\n"
    "• не подписывать бёрнер на рабочие аккаунты;\n"
    "• выбирать охват поу́же: «7 роликов» вместо «вся история»;\n"
    "• если прилетело ограничение — не долбиться, а подождать сутки.\n\n"
    "Бёрнер расходный: если его заблокируют, заведите новый и войдите заново — "
    "приложение это переживёт, история замеров не пострадает."
)
# Впишите адрес репозитория, когда заведёте его на GitHub. Пока строка пустая,
# окно честно пишет «ссылка появится позже» и ничего не открывает.
GITHUB_URL = ""

# Порядок здесь задаёт порядок ВЕЗДЕ: вкладки окна входа, кружки статуса,
# колонки таблицы, строки итогового окна и колонки во всех выгрузках.
# Instagram стоит третьим намеренно — он самый нестабильный из трёх,
# и глаз должен натыкаться сначала на то, что работает предсказуемо.
PLATFORMS = ("youtube", "tiktok", "instagram")

# Площадки, сбор которых пока экспериментальный. Помечаются в интерфейсе,
# чтобы человек не считал их сбои поломкой приложения.
EXPERIMENTAL_PLATFORMS = ("instagram",)
EXPERIMENTAL_SUFFIX = " (experimental)"
EXPERIMENTAL_SUFFIX_SHORT = " (exp.)"


def platform_label(platform, short=False):
    """Название площадки с пометкой об экспериментальности, если она есть.

    short=True — для узких мест вроде заголовков колонок таблицы.
    """
    label = PLATFORM_LABELS.get(platform, platform)
    if platform in EXPERIMENTAL_PLATFORMS:
        label += EXPERIMENTAL_SUFFIX_SHORT if short else EXPERIMENTAL_SUFFIX
    return label

# Площадки, которым вход НЕ нужен: данные берутся из публичного доступа.
# TikTok читается через yt-dlp анонимно — логин и пароль ему нечего дать
# (yt-dlp принимает cookies, а не пару логин/пароль). Держать эти площадки
# «незалогиненными» значило бы просто не собирать их без причины.
# Для изоляции это плюс: приложение не касается ни одного рабочего аккаунта.
NO_LOGIN_PLATFORMS = ("tiktok",)

# Охват сбора: сколько роликов канала учитывать. Порядок здесь = порядок
# в выпадающем списке главного окна.
#   all      — все ролики канала (накопительные числа, как в таблице «Продакшн»)
#   last_N   — N самых свежих роликов
#   days_N   — ролики, опубликованные за последние N дней
# Важно: «за 7 дней» — это НЕ «просмотры за 7 дней», а сумма просмотров у
# роликов, вышедших за 7 дней (каждый со своими просмотрами за всё время).
# Настоящий ответ на «сколько прибавили за сутки» даёт прирост — см. history.py.
SCOPE_PRESETS = (
    ("all", "Вся история"),
    ("last_7", "7 роликов"),
    ("last_30", "30 роликов"),
    ("days_7", "7 дней"),
    ("days_30", "30 дней"),
)
SCOPE_LABELS = dict(SCOPE_PRESETS)
SCOPE_KEYS = {label: key for key, label in SCOPE_PRESETS}
DEFAULT_SCOPE = "all"

SCOPE_HINT = (
    "Сколько роликов канала учитывать.\n\n"
    "«Вся история» — все ролики, накопительные числа (как в вашей таблице).\n"
    "«7/30 роликов» — только самые свежие публикации.\n"
    "«7/30 дней» — ролики, вышедшие за этот срок.\n\n"
    "Прирост «(+239)» считается только между замерами с одинаковым охватом."
)
PLATFORM_LABELS = {"youtube": "YouTube", "instagram": "Instagram", "tiktok": "TikTok"}
# Цвета "загоревшегося" статуса на платформу — используются и в окне входа
# (активная вкладка), и в статус-баре главного окна (кружок при входе).
PLATFORM_COLORS = {"youtube": "#E0342A", "instagram": "#F2A900", "tiktok": "#1FA34C"}

DEFAULT_ACCOUNTS = [
    {"name": "Блогер 1", "topic": "Дайвинг", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 2", "topic": "Дайвинг", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 3", "topic": "Дайвинг", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 4", "topic": "Сериалы и фильмы", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 5", "topic": "Сериалы и фильмы", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 6", "topic": "Сериалы и фильмы", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 7", "topic": "Тру-крайм", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 8", "topic": "Тру-крайм", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 9", "topic": "Тру-крайм", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 10", "topic": "Тру-крайм", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 11", "topic": "Сериалы и фильмы", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 12", "topic": "Дайвинг", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 13", "topic": "Дайвинг", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 14", "topic": "Дайвинг", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 15", "topic": "Тру-крайм", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 16", "topic": "Тру-крайм", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 17", "topic": "Сериалы и фильмы", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 18", "topic": "Сериалы и фильмы", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 19", "topic": "Сериалы и фильмы", "yt": "", "ig": "", "tt": ""},
    {"name": "Блогер 20", "topic": "Сериалы и фильмы", "yt": "", "ig": "", "tt": ""},
]


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


class AppState:
    """Единый на всё приложение объект состояния + подписчики на изменение логина."""

    def __init__(self):
        session = _load_json(SESSION_FILE, {})
        # login_status: залогинен ли вьюер-аккаунт по каждой платформе
        self.login_status = {p: bool(session.get(p, {}).get("logged_in")) for p in PLATFORMS}
        for p in NO_LOGIN_PLATFORMS:
            self.login_status[p] = True   # готовы к сбору сразу, вход не требуется
        # сами введённые данные (в памяти сессии, отдельно от диска — см. login_window.py)
        self.credentials = {p: session.get(p, {}).get("data", {}) for p in PLATFORMS}
        self.remember_on_device = bool(session.get("remember", False))
        self.appearance_mode = session.get("appearance_mode", "dark")  # по умолчанию тёмная
        # Показывать ли предупреждение перед сбором экспериментальных площадок.
        self.warn_experimental = bool(session.get("warn_experimental", True))
        scope = session.get("collect_scope", DEFAULT_SCOPE)
        self.collect_scope = scope if scope in SCOPE_LABELS else DEFAULT_SCOPE

        self.accounts = _load_json(ACCOUNTS_FILE, DEFAULT_ACCOUNTS)

        self._login_listeners = []  # колбэки: вызываются при изменении login_status

    # ---------- логин ----------
    def set_login(self, platform, logged_in, data=None, remember=False):
        # Площадки без входа всегда остаются готовыми: пустые поля в окне
        # входа не должны их «выключать».
        self.login_status[platform] = True if platform in NO_LOGIN_PLATFORMS else bool(logged_in)
        if data is not None:
            self.credentials[platform] = data
        self.remember_on_device = bool(remember)
        # Пишем всегда, а не только при включённой галочке: если её сняли,
        # запись как раз и должна СТЕРЕТЬ ранее сохранённые данные с диска.
        self._persist_session()
        for cb in self._login_listeners:
            cb()

    def add_login_listener(self, callback):
        """Главное окно подписывается сюда, чтобы обновлять кружки статус-бара живьём."""
        self._login_listeners.append(callback)

    def _persist_session(self):
        data = {
            "remember": self.remember_on_device,
            "appearance_mode": self.appearance_mode,
            "collect_scope": self.collect_scope,
            "warn_experimental": self.warn_experimental,
        }
        for p in PLATFORMS:
            # Логины/пароли/API-ключи пишем на диск ТОЛЬКО при включённой галочке
            # «Запомнить на этом устройстве». Раньше их выносило в session.json
            # любое сохранение настроек (например, переключение темы) — то есть
            # даже когда пользователь эту галочку намеренно снял. И статус входа
            # без самих данных не сохраняем: иначе после перезапуска приложение
            # считало бы себя залогиненным, не имея ключа.
            if self.remember_on_device:
                data[p] = {"logged_in": self.login_status[p], "data": self.credentials[p]}
            else:
                data[p] = {"logged_in": False}
        _save_json(SESSION_FILE, data)

    def set_appearance_mode(self, mode):
        self.appearance_mode = mode
        self._persist_session()

    def set_warn_experimental(self, value):
        self.warn_experimental = bool(value)
        self._persist_session()

    def set_collect_scope(self, scope_key):
        if scope_key in SCOPE_LABELS:
            self.collect_scope = scope_key
            self._persist_session()

    # ---------- аккаунты ----------
    def save_accounts(self, accounts):
        self.accounts = accounts
        return _save_json(ACCOUNTS_FILE, self.accounts)

    def reload_accounts(self):
        self.accounts = _load_json(ACCOUNTS_FILE, DEFAULT_ACCOUNTS)
        return self.accounts


# Единственный на процесс экземпляр — импортируется другими модулями напрямую.
state = AppState()
