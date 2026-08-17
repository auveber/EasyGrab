# -*- coding: utf-8 -*-
"""Реальный сбор метрик TikTok — через yt-dlp.

Официального публичного API у TikTok, сравнимого с YouTube Data API, нет:
их Display API требует одобрения приложения и OAuth-входа во ВСЕ 20 рабочих
аккаунтов, что связало бы их в одну систему. Поэтому берём публичные данные
профиля через yt-dlp — ровно как в исходниках коллеги, но принципиально
эффективнее (см. ниже).

Ключевая находка (проверено на всех 19 профилях): при `--flat-playlist`
TikTok отдаёт view_count / like_count / comment_count ПРЯМО В СПИСКЕ роликов,
одним запросом на профиль. В старом решении на каждый ролик запускался
отдельный процесс yt-dlp — на 21 ролик это 21 запуск вместо одного.
Здесь весь профиль забирается за ~2,5 секунды.

Вход в TikTok не нужен: читаются публичные профили анонимно. Это в плюс
изоляции — приложение вообще не касается ни одного рабочего аккаунта.

yt-dlp запускается как модуль текущего интерпретатора
(`sys.executable -m yt_dlp`), а не как команда `yt-dlp` из PATH: так он
находится всегда, если установлен в то же окружение, что и приложение,
и не зависит от системных путей. Отдельный процесс, а не библиотека —
ради жёсткого таймаута: зависший разбор не подвесит всё приложение.
"""
import datetime
import json
import subprocess
import sys

import diagnostics

# ---------------------------------------------------------------- настройки
YTDLP_TIMEOUT_S = 90     # жёсткий потолок на один профиль
TT_MAX_VIDEOS = 500      # предохранитель от бесконечной прокрутки профиля
RETRIES = 2              # повтор при обрыве сети


class TikTokError(Exception):
    """Ошибка, уже переведённая на человеческий язык (см. backend_youtube)."""

    def __init__(self, message, reason=""):
        super().__init__(message)
        self.reason = reason


def parse_profile(raw):
    """Достаёт @ник из того, что вписано в колонку TikTok.

    Понимает полную ссылку, ссылку с метками шеринга (?_t=…&_r=1),
    адрес конкретного ролика и просто «@ник» или «ник».
    """
    s = (raw or "").strip()
    if not s:
        raise TikTokError("не заполнена ссылка на профиль TikTok (экран «Аккаунты»)", "empty")

    if s.startswith("@") and "/" not in s:
        return s.split("?")[0]

    low = s.lower()
    if "tiktok.com" not in low:
        if "/" not in s and "." not in s:      # голый ник без ссылки
            return "@" + s
        raise TikTokError("это не похоже на ссылку TikTok: %s" % s[:80], "not_tiktok")

    # Отрезаем метки шеринга и берём сегмент, начинающийся с @.
    path = s.split("?")[0].split("#")[0]
    for part in path.split("/"):
        if part.startswith("@"):
            return part
    raise TikTokError("в ссылке нет имени профиля (@ник): %s" % s[:80], "bad_url")


def profile_url(handle):
    return "https://www.tiktok.com/%s" % handle


def _friendly_error(stderr):
    """Переводит вывод yt-dlp в понятную пользователю причину."""
    text = (stderr or "").lower()
    # Именно так yt-dlp сообщает о несуществующем профиле: он не может достать
    # внутренний ID пользователя. Сверено с реальным выводом, не угадано.
    if "unable to extract secondary user id" in text:
        return ("профиль не найден — проверьте ссылку в экране «Аккаунты» "
                "(возможно, аккаунт удалён или переименован)")
    if "404" in text or "could not find" in text or "unable to find" in text:
        return "профиль не найден — проверьте ссылку в экране «Аккаунты»"
    if "private" in text:
        return "профиль закрытый (приватный) — публичные метрики недоступны"
    if "empty" in text and "playlist" in text:
        return "в профиле нет роликов"
    if "captcha" in text or "verify" in text:
        return ("TikTok потребовал проверку «я не робот». Подождите 20–30 минут "
                "или соберите позже — при частых запросах он временно ограничивает доступ")
    if "429" in text or "too many requests" in text or "rate" in text and "limit" in text:
        return ("TikTok временно ограничил частоту запросов. Подождите 20–30 минут "
                "и попробуйте снова")
    if "unable to download" in text or "connection" in text or "timed out" in text:
        return "нет связи с TikTok — проверьте интернет"
    # Признаки того, что TikTok поменял свою страницу и разборщик отстал.
    # Лечится обновлением yt-dlp, и об этом надо сказать прямо, а не показывать
    # пользователю внутренности ошибки.
    if any(m in text for m in ("unable to extract", "unsupported url", "failed to parse",
                               "no video formats", "extractorerror")):
        return ("yt-dlp не смог разобрать страницу TikTok — скорее всего он устарел. "
                "Обновите командой:  pip install -U yt-dlp")
    if "no module named" in text and "yt_dlp" in text:
        return ("не установлен yt-dlp. Выполните в терминале: "
                "pip install -U yt-dlp")
    first = (stderr or "").strip().splitlines()
    return "TikTok не отдал данные: %s" % (first[-1][:160] if first else "причина неизвестна")


def _run_ytdlp(url, limit):
    """Один запрос к yt-dlp. Возвращает разобранный JSON профиля."""
    args = [
        sys.executable, "-m", "yt_dlp",
        "-J",                    # весь результат одним JSON
        "--flat-playlist",       # без захода в каждый ролик: метрики уже в списке
        "--no-warnings",
        "--ignore-errors",
        "--no-playlist-reverse",
        "--playlist-end", str(max(1, limit)),
        url,
    ]
    last_error = ""
    for attempt in range(RETRIES):
        try:
            proc = subprocess.run(args, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=YTDLP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            last_error = "таймаут %d с" % YTDLP_TIMEOUT_S
            continue
        except FileNotFoundError:
            raise TikTokError("не найден интерпретатор Python для запуска yt-dlp", "no_python")

        if proc.stdout.strip():
            try:
                parsed = json.loads(proc.stdout)
            except json.JSONDecodeError:
                last_error = "yt-dlp вернул неразборчивый ответ"
                continue
            # С --ignore-errors несуществующий профиль даёт литерал `null`
            # в stdout, а настоящая причина уходит в stderr. Без этой проверки
            # дальше прилетало бы AttributeError на None.
            if isinstance(parsed, dict):
                return parsed
            last_error = proc.stderr or "профиль не найден"
            break
        last_error = proc.stderr or "пустой ответ"
        # Ошибки вроде «профиль не найден» повторять бессмысленно.
        if any(m in last_error.lower() for m in ("404", "private", "could not find")):
            break

    raise TikTokError(_friendly_error(last_error), "ytdlp")


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _select_entries(entries, scope_key):
    """Отбирает ролики по охвату. Список идёт от свежих к старым, как у YouTube."""
    import backend_youtube  # общий разбор ключа охвата, чтобы не дублировать
    mode, amount = backend_youtube.parse_scope(scope_key)

    if mode == "last_n":
        return entries[:max(1, amount)], False

    if mode == "days":
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max(1, amount))
        cutoff_ts = cutoff.timestamp()
        selected = []
        for e in entries:
            ts = e.get("timestamp")
            if ts is not None and ts < cutoff_ts:
                break          # дальше только более старые
            selected.append(e)
        return selected, False

    return entries[:TT_MAX_VIDEOS], len(entries) > TT_MAX_VIDEOS


# ---------------------------------------------------------------- точка входа
def collect(account, credentials, scope_key="all"):
    """Собирает метрики одного профиля TikTok. Контракт — как в mock_backend.

    credentials не используются: публичные профили читаются анонимно.
    Параметр оставлен, чтобы сигнатура совпадала с остальными сборщиками.
    """
    account_name = account.get("name", "")
    raw = (account.get("tt") or "").strip()

    try:
        handle = parse_profile(raw)
        url = profile_url(handle)

        # При охвате «последние N» просим у yt-dlp ровно столько, сколько нужно.
        import backend_youtube
        mode, amount = backend_youtube.parse_scope(scope_key)
        limit = max(1, amount) if mode == "last_n" else TT_MAX_VIDEOS

        data = _run_ytdlp(url, limit)
        entries = [e for e in (data.get("entries") or []) if e]

        if not entries:
            return {"ok": False, "error": "в профиле нет роликов (или TikTok их не отдал)"}

        selected, truncated = _select_entries(entries, scope_key)

        views = likes = comments = 0
        counted = 0
        zero_views = 0
        for e in selected:
            v = _to_int(e.get("view_count")) or 0
            views += v
            likes += _to_int(e.get("like_count")) or 0
            comments += _to_int(e.get("comment_count")) or 0
            counted += 1
            if v == 0:
                zero_views += 1

        title = data.get("title") or (selected[0].get("channel") if selected else "") or handle

        diagnostics.log(
            "INFO", "tiktok.profile", "Профиль собран",
            account=account_name, profile=handle, title=title, scope=scope_key,
            videos_in_profile=len(entries), videos_counted=counted,
            truncated=truncated, zero_view_videos=zero_views,
        )
        # 0 просмотров при ненулевых лайках физически невозможно: лайк ставит
        # тот, кто посмотрел. Значит TikTok не отдаёт счётчик показов у этого
        # профиля — типичный признак теневого бана. Пишем предупреждение,
        # но сбор не проваливаем: лайки и комментарии всё равно настоящие.
        if zero_views == counted and likes > 0:
            diagnostics.log(
                "WARNING", "tiktok.zero_views",
                "У профиля нулевые просмотры при ненулевых лайках — возможен теневой бан "
                "или TikTok скрыл счётчик показов",
                account=account_name, profile=handle, likes=likes, videos=counted,
            )

        return {
            "ok": True,
            "views": views,
            "likes": likes,
            "comments": comments,
            # Дополнительные поля: интерфейс их не показывает, но они видны
            # в тех.журнале и пригодятся, когда добавим колонку подписчиков.
            "videos_counted": counted,
            "profile": handle,
            "profile_title": title,
            "zero_view_videos": zero_views,
        }

    except TikTokError as e:
        diagnostics.log("WARNING", "tiktok.fail", str(e), account=account_name,
                        link=raw[:120], reason=e.reason)
        return {"ok": False, "error": str(e)}


def version_date(version):
    """Версия yt-dlp — это дата: «2026.07.04» -> «04.07.2026».

    У yt-dlp номер версии и есть день сборки, отдельной даты у него нет.
    Пустая строка, если разобрать не вышло.
    """
    parts = _version_tuple(version)
    if len(parts) < 3 or not (2000 <= parts[0] <= 2100):
        return ""
    year, month, day = parts[0], parts[1], parts[2]
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return "%02d.%02d.%d" % (day, month, year)


def _version_tuple(text):
    """«2026.07.04» и «2026.7.4» -> (2026, 7, 4): сравниваем числами, не строками."""
    parts = []
    for chunk in (text or "").strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def latest_version(timeout=15):
    """Последняя СТАБИЛЬНАЯ версия yt-dlp на PyPI. None, если не дозвонились."""
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/yt-dlp/json", timeout=timeout) as r:
            return (_json.loads(r.read().decode("utf-8")).get("info") or {}).get("version")
    except Exception:
        return None


def check_for_update():
    """Сравнивает установленную версию с последней стабильной.

    Ничего не устанавливает — только сообщает. Тихое обновление посреди
    наблюдений меняло бы движок сбора без ведома пользователя, а он сравнивает
    цифры день ко дню и не смог бы отличить просадку каналов от смены версии.

    Возвращает (устарел, установленная, последняя).
    """
    ok, installed = check_available()
    if not ok:
        return False, None, None
    latest = latest_version()
    if not latest:
        return False, installed, None
    return _version_tuple(latest) > _version_tuple(installed), installed, latest


def update():
    """Обновляет yt-dlp через pip. Возвращает (получилось, текст для лога)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )
    except subprocess.TimeoutExpired:
        return False, "обновление не уложилось в 5 минут"
    except Exception as e:
        return False, "не удалось запустить pip: %s" % e
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, "pip вернул ошибку: %s" % (tail[-1][:160] if tail else "причина неизвестна")
    ok, version = check_available()
    return (True, "yt-dlp обновлён до версии %s" % version) if ok else (False, version)


def check_available():
    """Проверяет, что yt-dlp установлен. Возвращает (True, версия) или (False, причина)."""
    try:
        proc = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"],
                              capture_output=True, text=True, timeout=30)
        if proc.returncode == 0 and proc.stdout.strip():
            return True, proc.stdout.strip()
        return False, "не установлен yt-dlp. Выполните: pip install -U yt-dlp"
    except Exception as e:
        return False, "не удалось запустить yt-dlp: %s" % e
