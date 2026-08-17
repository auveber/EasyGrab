# -*- coding: utf-8 -*-
"""Реальный сбор метрик Instagram — через instagrapi.

ПОЧЕМУ НЕ instaloader. Он ходит веб-эндпоинтами, и на них Instagram отвечает
429 практически сразу: проверено на живом аккаунте, встроенный регулятор
частоты ждал больше семи минут и всё равно не пробился. instagrapi работает
через мобильный API — там лимиты другие, и он проходит.

ПОЧЕМУ ВХОД ПАРОЛЕМ, а не только сессия из браузера. Вкладка Reels
(`user_clips_v1`) отдаёт просмотры ПАЧКОЙ — один запрос на профиль вместо
одного на каждый ролик. Но она требует полноценного входа с отпечатком
устройства: вход по одной cookie из браузера получает login_required.
Проверено обоими способами.

Разница в цене:
  * полный вход   -> ~1 запрос на профиль, 17 профилей за пару минут;
  * только cookie -> ~9 запросов на профиль, те же 17 профилей за 10+ минут.

Пароль спрашивается ОДИН раз. После входа instagrapi сохраняет сессию вместе
с отпечатком устройства в файл, и дальше пароль не нужен — на диск он
не пишется ни при каких условиях.

ПРО РИСК. Любой аккаунт, через который идёт автоматический сбор, может быть
заблокирован — это плата за автоматизацию, а не поломка. Поэтому и нужен
отдельный аккаунт-бёрнер: его потеря ничего не стоит. На сами рабочие
аккаунты чтение их публичных страниц не влияет никак.
"""
import datetime
import os
import threading
import time

import diagnostics

# ---------------------------------------------------------------- настройки
IG_PAUSE_S = 12          # пауза между профилями
IG_MAX_POSTS = 300       # потолок постов на профиль
IG_TIME_BUDGET_S = 120   # потолок времени на один профиль
IG_DELAY_RANGE = [2, 4]  # instagrapi сам выдерживает паузу между своими запросами

# Добирать ли просмотры поштучно, когда пачкой не вышло.
#
# ВЫКЛЮЧЕНО ПО ИТОГАМ ЖИВОЙ ПРОВЕРКИ. Раньше стояло True, и на первом же
# реальном сборе Instagram прислал предупреждение об «автоматизированных
# действиях»: семь роликов = восемь запросов подряд за несколько секунд,
# и так по каждому профилю. Данные при этом собрались верно — но цена
# оказалась выше пользы.
#
# Правильный способ получить просмотры — полный вход паролем: он открывает
# вкладку Reels, где просмотры приходят ПАЧКОЙ, один запрос на профиль
# вместо восьми. Поштучный добор оставлен только как осознанный выбор.
IG_FETCH_VIEWS_ONE_BY_ONE = False

# Если поштучный добор всё же включат — не больше стольких запросов на профиль.
IG_VIEWS_ONE_BY_ONE_CAP = 5

HERE = os.path.dirname(os.path.abspath(__file__))

# Браузеры для запасного входа по сессии. Порядок = порядок в окне входа.
BROWSERS = (
    ("safari", "Safari"),
    ("chrome", "Chrome"),
    ("firefox", "Firefox"),
    ("edge", "Microsoft Edge"),
    ("brave", "Brave"),
    ("opera", "Opera"),
    ("vivaldi", "Vivaldi"),
    ("chromium", "Chromium"),
)
BROWSER_LABELS = dict(BROWSERS)
BROWSER_KEYS = {label: key for key, label in BROWSERS}


def settings_file(username):
    """Файл сессии instagrapi: ключ входа и отпечаток устройства.

    Это секрет — права ставим 600, и в бэкапы он не попадает.
    """
    return os.path.join(HERE, "ig_settings_%s.json" % username)


class InstagramError(Exception):
    """Ошибка, уже переведённая на человеческий язык (как в других сборщиках)."""

    def __init__(self, message, reason=""):
        super().__init__(message)
        self.reason = reason


# ------------------------------------------------------- разделяемая сессия
_lock = threading.Lock()
_session = {"client": None, "user": None}
_last_request_at = [0.0]


def reset_session():
    """Забыть текущий вход — например, когда сменили бёрнер."""
    with _lock:
        _session["client"] = None
        _session["user"] = None


def _new_client():
    from instagrapi import Client
    client = Client()
    client.delay_range = list(IG_DELAY_RANGE)
    return client


def _save_settings(client, username):
    path = settings_file(username)
    try:
        client.dump_settings(path)
        os.chmod(path, 0o600)
        return True
    except Exception as e:
        diagnostics.log("WARNING", "instagram.settings_save",
                        "Вход выполнен, но сессию не удалось сохранить", error=str(e)[:160])
        return False


def _friendly_error(error):
    """Переводит ошибку instagrapi в понятную пользователю причину."""
    text = str(error).lower()
    name = type(error).__name__.lower()

    if "challenge" in text or "challenge" in name or "checkpoint" in name:
        return ("Instagram запросил подтверждение личности. Войдите в этот аккаунт "
                "через приложение или браузер, пройдите проверку и повторите сбор")
    if "two_factor" in text or "twofactor" in name:
        return ("у аккаунта включена двухфакторная проверка — приложение не сможет "
                "ввести код. Отключите её у бёрнера")
    if "bad password" in text or "incorrect" in text or "badpassword" in name:
        return "неверный логин или пароль"
    if "429" in text or "too many" in text or ("rate" in text and "limit" in text):
        return ("Instagram ограничил частоту запросов. Подождите 20–40 минут. "
                "Если повторяется — собирайте реже или увеличьте паузу IG_PAUSE_S "
                "в backend_instagram.py")
    if "login_required" in text or "loginrequired" in name:
        return "сессия устарела — войдите заново (кружок «IG»)"
    if "feedback_required" in text or "spam" in text:
        return ("Instagram счёл действия аккаунта подозрительными. Дайте бёрнеру "
                "отдохнуть сутки и собирайте реже")
    if "not found" in text or "usernotfound" in name:
        return "профиль не найден — проверьте ссылку в экране «Аккаунты»"
    if "private" in text:
        return "профиль закрытый, а бёрнер на него не подписан"
    return "Instagram не отдал данные (%s): %s" % (type(error).__name__, str(error)[:140])


# ---------------------------------------------------------------- вход
def login_with_password(username, password):
    """Полный вход: ставит отпечаток устройства и открывает вкладку Reels.

    Пароль нужен ровно один раз — дальше живёт файл сессии. На диск пароль
    не пишется никогда.

    Возвращает (True, имя_пользователя) либо (False, причина).
    """
    username = (username or "").strip().lstrip("@")
    if not username or not password:
        return False, "заполните логин и пароль аккаунта-бёрнера"

    client = _new_client()
    path = settings_file(username)
    if os.path.exists(path):
        try:
            client.load_settings(path)   # сохраняем прежний отпечаток устройства:
        except Exception:                # новое «устройство» — лишний повод для проверки
            client = _new_client()

    try:
        client.login(username, password)
    except Exception as e:
        return False, _friendly_error(e)

    _save_settings(client, username)
    with _lock:
        _session["client"] = client
        _session["user"] = username
    diagnostics.log("INFO", "instagram.login", "Полный вход выполнен, сессия сохранена",
                    user=username)
    return True, username


def import_browser_session(browser_key):
    """Запасной путь: готовая сессия из браузера, без пароля.

    Работает, но вкладку Reels не открывает — у сессии из браузера нет
    отпечатка устройства, и user_clips_v1 отвечает login_required. Просмотры
    в этом режиме добираются поштучно, это заметно дольше.
    """
    try:
        from instaloader.__main__ import get_cookies_from_instagram
    except ImportError:
        return False, ("не установлена библиотека browser_cookie3. "
                       "Выполните: pip install -U browser_cookie3")

    label = BROWSER_LABELS.get(browser_key, browser_key)
    attempts = _profiles_with_instagram_session(browser_key) or [(None, None)]

    cookies, last_error = None, None
    for _name, path in attempts:
        try:
            cookies = get_cookies_from_instagram("instagram", browser_key, path)
            break
        except Exception as e:
            last_error = e
    if cookies is None:
        return False, _friendly_browser_error(browser_key, last_error or "нет данных")

    try:
        names = set(cookies.keys()) if hasattr(cookies, "keys") else {c.name for c in cookies}
    except Exception:
        names = set()
    if "sessionid" not in names:
        return False, ("в %s нет активного входа в Instagram (нет ключа сессии). "
                       "Откройте instagram.com в этом браузере, войдите под бёрнером "
                       "и попробуйте снова" % label)

    client = _new_client()
    try:
        client.login_by_sessionid(cookies["sessionid"])
        username = client.username
    except Exception as e:
        return False, _friendly_error(e)
    if not username:
        return False, ("сессия в %s найдена, но Instagram не даёт её проверить "
                       "(ограничение частоты). Подождите 10–20 минут" % label)

    _save_settings(client, username)
    with _lock:
        _session["client"] = client
        _session["user"] = username
    diagnostics.log("INFO", "instagram.browser_session",
                    "Сессия импортирована из браузера", browser=browser_key, user=username)
    return True, username


# Где браузеры семейства Chromium держат профили. У человека их бывает
# несколько, и вход в Instagram может быть в любом — а библиотека по умолчанию
# смотрит только в «Default». На живом Mac сессия нашлась в «Profile 4».
_CHROMIUM_DIRS = {
    "chrome": {"darwin": "~/Library/Application Support/Google/Chrome",
               "win32": "~/AppData/Local/Google/Chrome/User Data",
               "linux": "~/.config/google-chrome"},
    "chromium": {"darwin": "~/Library/Application Support/Chromium",
                 "win32": "~/AppData/Local/Chromium/User Data",
                 "linux": "~/.config/chromium"},
    "edge": {"darwin": "~/Library/Application Support/Microsoft Edge",
             "win32": "~/AppData/Local/Microsoft/Edge/User Data",
             "linux": "~/.config/microsoft-edge"},
    "brave": {"darwin": "~/Library/Application Support/BraveSoftware/Brave-Browser",
              "win32": "~/AppData/Local/BraveSoftware/Brave-Browser/User Data",
              "linux": "~/.config/BraveSoftware/Brave-Browser"},
    "vivaldi": {"darwin": "~/Library/Application Support/Vivaldi",
                "win32": "~/AppData/Local/Vivaldi/User Data",
                "linux": "~/.config/vivaldi"},
    "opera": {"darwin": "~/Library/Application Support/com.operasoftware.Opera",
              "win32": "~/AppData/Roaming/Opera Software/Opera Stable",
              "linux": "~/.config/opera"},
}


def _profiles_with_instagram_session(browser_key):
    """Профили браузера, где есть ключ сессии Instagram.

    Читаем ТОЛЬКО имена ключей и только из копии файла: значения cookie
    не трогаем, а оригинал занят работающим браузером.
    """
    import glob
    import shutil
    import sqlite3
    import sys
    import tempfile

    dirs = _CHROMIUM_DIRS.get(browser_key)
    if not dirs:
        return []
    platform = "darwin" if sys.platform == "darwin" else \
               "win32" if sys.platform.startswith("win") else "linux"
    base = os.path.expanduser(dirs.get(platform, ""))
    if not base or not os.path.isdir(base):
        return []

    found = []
    for path in sorted(glob.glob(os.path.join(base, "*", "Cookies")) +
                       glob.glob(os.path.join(base, "*", "Network", "Cookies"))):
        profile = path[len(base) + 1:].replace("/Network/Cookies", "").replace("/Cookies", "")
        tmp_dir = tempfile.mkdtemp()
        try:
            tmp = os.path.join(tmp_dir, "cookies.sqlite")
            shutil.copy(path, tmp)
            con = sqlite3.connect(tmp)
            has = con.execute("SELECT 1 FROM cookies WHERE host_key LIKE '%instagram%' "
                              "AND name = 'sessionid' LIMIT 1").fetchone()
            con.close()
            if has:
                found.append((profile, path))
        except Exception:
            continue
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    return found


def _friendly_browser_error(browser_key, error):
    label = BROWSER_LABELS.get(browser_key, browser_key)
    text = str(error).lower()
    if "could not find" in text or "not found" in text or "no such file" in text:
        return "%s не найден на этом компьютере" % label
    if "permission" in text or "operation not permitted" in text:
        return ("macOS не даёт читать cookie из %s. Проще всего войти под бёрнером "
                "в Chrome — оттуда читается без дополнительных разрешений" % label)
    if "locked" in text:
        return "%s сейчас занят — закройте браузер и попробуйте снова" % label
    return "не удалось прочитать сессию из %s: %s" % (label, str(error)[:140])


def _get_client(credentials):
    """Один вход на весь прогон. Пароль не нужен, если есть файл сессии."""
    username = ((credentials or {}).get("user") or "").strip().lstrip("@")
    if not username:
        raise InstagramError(
            "Instagram не подключён — нажмите кружок «IG» и войдите "
            "под аккаунтом-бёрнером", "no_user")

    with _lock:
        if _session["client"] is not None and _session["user"] == username:
            return _session["client"]

    path = settings_file(username)
    if not os.path.exists(path):
        raise InstagramError(
            "нет сохранённой сессии для @%s — нажмите кружок «IG» "
            "и войдите заново" % username, "no_session")

    client = _new_client()
    try:
        client.load_settings(path)
        client.get_timeline_feed()      # лёгкая проверка, что сессия ещё жива
    except Exception as e:
        raise InstagramError(_friendly_error(e), "session")

    with _lock:
        _session["client"] = client
        _session["user"] = username
    diagnostics.log("INFO", "instagram.session", "Использована сохранённая сессия", user=username)
    return client


def _pause_between_profiles():
    """Пауза ПЕРЕД запросом, а не после: так нажатая «Стоп» не ждёт впустую."""
    elapsed = time.time() - _last_request_at[0]
    if _last_request_at[0] and elapsed < IG_PAUSE_S:
        time.sleep(IG_PAUSE_S - elapsed)
    _last_request_at[0] = time.time()


# ---------------------------------------------------------------- разбор ссылки
def parse_profile(raw):
    """Достаёт ник из того, что вписано в колонку Instagram."""
    s = (raw or "").strip()
    if not s:
        raise InstagramError("не заполнена ссылка на профиль Instagram (экран «Аккаунты»)", "empty")

    if s.startswith("@") and "/" not in s:
        return s[1:].split("?")[0]

    if "instagram.com" not in s.lower():
        if "/" not in s and "." not in s:
            return s
        raise InstagramError("это не похоже на ссылку Instagram: %s" % s[:80], "not_instagram")

    path = s.split("?")[0].split("#")[0].rstrip("/")
    for part in [p for p in path.split("/") if p]:
        low = part.lower()
        if low in ("https:", "http:") or "instagram.com" in low:
            continue
        if low in ("p", "reel", "reels", "tv", "stories"):
            raise InstagramError(
                "это ссылка на отдельный пост, а нужен профиль: %s" % s[:70], "post_url")
        return part.lstrip("@")
    raise InstagramError("в ссылке нет имени профиля: %s" % s[:80], "bad_url")


# ---------------------------------------------------------------- точка входа
def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def collect(account, credentials, scope_key="all"):
    """Собирает метрики одного профиля Instagram. Контракт — как в mock_backend."""
    import backend_youtube      # общий разбор ключа охвата

    account_name = account.get("name", "")
    raw = (account.get("ig") or "").strip()

    try:
        username = parse_profile(raw)
        client = _get_client(credentials)
        _pause_between_profiles()

        try:
            info = client.user_info_by_username(username)
        except Exception as e:
            return {"ok": False, "error": _friendly_error(e)}

        if info.is_private:
            return {"ok": False, "error": "профиль @%s закрытый, а бёрнер на него "
                                          "не подписан" % username}

        mode, amount = backend_youtube.parse_scope(scope_key)
        limit = min(IG_MAX_POSTS, max(1, amount)) if mode == "last_n" else IG_MAX_POSTS
        cutoff = None
        if mode == "days":
            cutoff = datetime.datetime.now(datetime.timezone.utc) - \
                     datetime.timedelta(days=max(1, amount))

        # Вкладка Reels отдаёт просмотры ПАЧКОЙ — один запрос вместо одного
        # на каждый ролик. Работает только при полном входе (с отпечатком
        # устройства); при входе по cookie из браузера падает в login_required,
        # и тогда просмотры добираются поштучно.
        bulk = True
        try:
            medias = client.user_clips_v1(info.pk, amount=limit)
        except Exception as e:
            diagnostics.log("WARNING", "instagram.clips_unavailable",
                            "Вкладка Reels недоступна, беру обычную ленту",
                            account=account_name, error=str(e)[:160])
            bulk = False
            try:
                medias = client.user_medias(info.pk, amount=limit)
            except Exception as e2:
                return {"ok": False, "error": _friendly_error(e2)}

        views = likes = comments = 0
        counted = without_views = one_by_one = 0
        started = time.time()
        for media in medias:
            if time.time() - started > IG_TIME_BUDGET_S:
                break
            taken = getattr(media, "taken_at", None)
            if cutoff is not None and taken is not None:
                taken_utc = taken if taken.tzinfo else taken.replace(tzinfo=datetime.timezone.utc)
                if taken_utc < cutoff:
                    break                       # дальше только старее
            likes += _to_int(getattr(media, "like_count", 0))
            comments += _to_int(getattr(media, "comment_count", 0))

            count = _to_int(getattr(media, "play_count", 0)) or \
                    _to_int(getattr(media, "view_count", 0))
            if (not count and not bulk and IG_FETCH_VIEWS_ONE_BY_ONE
                    and one_by_one < IG_VIEWS_ONE_BY_ONE_CAP):
                # Обычная лента просмотры не отдаёт — спрашиваем по посту.
                # Строго с потолком: именно эта череда запросов и вызвала
                # у Instagram подозрение на автоматизацию.
                one_by_one += 1
                try:
                    count = _to_int(getattr(client.media_info(media.pk), "play_count", 0))
                except Exception:
                    count = 0
            if count:
                views += count
            else:
                without_views += 1
            counted += 1

        _last_request_at[0] = time.time()

        diagnostics.log(
            "INFO", "instagram.profile", "Профиль собран",
            account=account_name, profile=username, full_name=info.full_name,
            scope=scope_key, followers=info.follower_count, posts_on_profile=info.media_count,
            posts_counted=counted, without_view_counter=without_views, bulk_reels=bulk,
            one_by_one_requests=one_by_one,
        )
        if not bulk:
            diagnostics.log(
                "WARNING", "instagram.no_bulk",
                "Вкладка Reels недоступна — просмотры собраны не полностью. "
                "Войдите логином и паролем (кружок «IG»), это откроет сбор пачкой",
                account=account_name, profile=username)

        if counted == 0:
            return {"ok": False, "error": "у профиля @%s нет постов за выбранный охват" % username}

        return {
            "ok": True,
            "views": views,
            "likes": likes,
            "comments": comments,
            "posts_counted": counted,
            "profile": username,
            "profile_title": info.full_name or username,
            "followers": info.follower_count,
            "without_view_counter": without_views,
            "bulk_reels": bulk,
        }

    except InstagramError as e:
        diagnostics.log("WARNING", "instagram.fail", str(e), account=account_name,
                        link=raw[:120], reason=e.reason)
        return {"ok": False, "error": str(e)}


def check_available():
    """Установлен ли instagrapi. Возвращает (True, версия) или (False, причина)."""
    try:
        from importlib.metadata import version
        import instagrapi  # noqa: F401
        return True, version("instagrapi")
    except ImportError:
        return False, "не установлен instagrapi. Выполните: pip install -U instagrapi"
