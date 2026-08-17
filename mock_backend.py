# -*- coding: utf-8 -*-
"""Точка входа сбора метрик — БОЛЬШЕ НЕ ЗАГЛУШКА.

Имя файла осталось прежним намеренно: main_window.py делает
`from mock_backend import simulate_collect`, и не трогать этот импорт —
значит не рисковать уже отлаженным интерфейсом. Внутри теперь не случайные
числа, а настоящие запросы к площадкам.

Этот модуль — тонкий диспетчер: он только выбирает нужную площадку и
приводит ответ к формату, который ждёт main_window.py. Вся реальная логика
живёт в отдельных файлах по площадке (backend_youtube.py и далее), чтобы
один файл не превратился в тысячу строк на три соцсети.

Контракт (не менять — от него зависит отрисовка статусов, живое обновление
таблицы и экспорт):
    {"ok": True, "views": 128400, "likes": 6200, "comments": 340}  — успех
    {"ok": False, "error": "текст причины"}                        — неудача
Исключение тоже допустимо: main_window.py поймает его и запишет в
технический журнал с полной трассировкой.

Состояние подключения площадок:
    youtube   — YouTube Data API v3, только API-ключ, без входа
    tiktok    — yt-dlp, анонимно, без входа
    instagram — instaloader, ВХОД ОБЯЗАТЕЛЕН (анонимно Instagram не отдаёт
                ничего: 429 на первом же запросе), под отдельным вьюер-аккаунтом
"""
import backend_instagram
import backend_tiktok
import backend_youtube
from app_state import state

# Площадки, у которых уже есть настоящий сбор. Остальные возвращают понятную
# причину вместо случайных чисел — чтобы в таблице было честно видно, что
# именно ещё не подключено, а не «ошибка» без объяснений.
_COLLECTORS = {
    "youtube": backend_youtube.collect,
    "tiktok": backend_tiktok.collect,
    "instagram": backend_instagram.collect,
}

_NOT_READY = {}   # все три площадки подключены


def simulate_collect(account, platform):
    """Собирает метрики одного аккаунта на одной площадке.

    account  — dict: {"name":.., "topic":.., "yt":.., "ig":.., "tt":..}
    platform — "youtube" / "instagram" / "tiktok"

    Данные для входа берутся из общего состояния приложения: для YouTube это
    API-ключ, для Instagram/TikTok — логин и пароль отдельного вьюер-аккаунта.
    """
    collector = _COLLECTORS.get(platform)
    if collector is None:
        return {"ok": False, "error": _NOT_READY.get(platform, "неизвестная площадка: %s" % platform)}

    credentials = state.credentials.get(platform, {}) or {}
    return collector(account, credentials, state.collect_scope)


# Понятное имя для нового кода; старое оставлено ради импорта в main_window.py.
collect = simulate_collect
