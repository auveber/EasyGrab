# -*- coding: utf-8 -*-
"""Реальный сбор метрик YouTube — официальный YouTube Data API v3.

Только API-ключ, без OAuth и без входа в Google-аккаунт: собираются
исключительно публичные данные каналов. Это принципиально для изоляции
рабочих аккаунтов — приложение вообще не «знает» ни одного логина Google
и не может связать 20 каналов между собой.

Поток сбора по одному каналу (как в ТЗ):
    1. channels.list  — по ссылке/хэндлу канала, part=statistics,contentDetails
       -> id канала, подписчики, накопительные просмотры канала,
          uploadsPlaylistId (плейлист «Загрузки» = все ролики канала);
    2. playlistItems.list — постранично по этому плейлисту -> ID роликов;
    3. videos.list — part=statistics, батчами до 50 ID за вызов
       -> viewCount / likeCount / commentCount по каждому ролику;
    4. суммируем и отдаём одну тройку чисел на канал.

Расход квоты: каждый из этих вызовов стоит 1 юнит. На канал с ≤50 роликами
это 3 юнита, на 20 каналов — около 60 юнитов из 10 000 в сутки, то есть
меньше процента. Дорогой здесь только запасной search.list (100 юнитов),
он используется лишь для старых ссылок вида /c/Название — см.
YT_ALLOW_SEARCH_FALLBACK ниже.

Зависимостей нет: работаем через стандартный urllib, чтобы пользователю
не пришлось ставить лишние библиотеки.
"""
import datetime
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import diagnostics

API_ROOT = "https://www.googleapis.com/youtube/v3/"

# ---------------------------------------------------------------- настройки
# Сколько роликов канала максимум учитывать. Ролики берутся с самых свежих.
# 200 роликов = 4 страницы плейлиста + 4 батча статистики = 9 юнитов на канал.
# Если каналы вырастут и захочется считать вообще все ролики — поднимите число.
YT_MAX_VIDEOS = 200

# Откуда брать «Просмотры»:
#   "videos"  — сумма просмотров по роликам (по умолчанию). Согласовано
#               с лайками и комментариями: все три числа посчитаны по одному
#               и тому же набору роликов.
#   "channel" — «Накопительное кол-во просмотров» самого канала из статистики
#               канала. Это ровно то число, что в вашей таблице «Продакшн»,
#               но оно включает и удалённые/скрытые ролики, поэтому не всегда
#               сходится с суммой лайков и комментариев.
YT_VIEWS_SOURCE = "videos"

# Старые ссылки вида youtube.com/c/Название нельзя превратить в ID канала
# «дешёвым» вызовом — для них есть только поиск, а он стоит 100 юнитов
# (на 20 каналов — 2000 из 10 000). Результат кэшируется на диск, поэтому
# платим один раз, а не при каждом сборе. Поставьте False, чтобы запретить.
YT_ALLOW_SEARCH_FALLBACK = True

HTTP_TIMEOUT_S = 20      # ожидание ответа на один запрос
HTTP_RETRIES = 3         # повторы при временных сбоях сети/сервера
USER_AGENT = "EasyGrab/0.2 (+https://example.local)"

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(HERE, "yt_channel_cache.json")


class YouTubeError(Exception):
    """Ошибка, уже переведённая на человеческий язык.

    Всё, что попадает в этот класс, — предсказуемая ситуация (кончилась квота,
    канал не найден, ключ не тот). Она превращается в {"ok": False, "error": ...}
    и показывается пользователю как понятная причина. Любое ДРУГОЕ исключение
    намеренно летит наружу — main_window.py поймает его и запишет в тех.журнал
    с полной трассировкой, как настоящий сбой.
    """

    def __init__(self, message, reason=""):
        super().__init__(message)
        self.reason = reason


class _Quota:
    """Счётчик израсходованных юнитов — попадает в тех.журнал."""

    def __init__(self):
        self.units = 0

    def add(self, n):
        self.units += n


# ---------------------------------------------------------------- сеть / API
def _friendly_error(http_code, reason, message):
    """Превращает код ошибки Google в понятную пользователю причину."""
    # Тексты ниже сверены с настоящими ответами googleapis.com, а не выдуманы:
    # пустой ключ  -> 403 forbidden  «Method doesn't allow unregistered callers…»
    # мусорный ключ -> 400 badRequest «API key not valid. Please pass a valid API key.»
    r = (reason or "").lower()
    m = (message or "").lower()

    if r == "quotaexceeded" or "quota" in r:
        return ("исчерпана дневная квота YouTube API (10 000 юнитов на проект). "
                "Она обнуляется в полночь по тихоокеанскому времени — это примерно "
                "10 утра по Киеву. Попробуйте позже или заведите второй проект "
                "в Google Cloud Console со своим ключом")
    if r == "keyinvalid" or "api key not valid" in m or "api_key_invalid" in m:
        return ("неверный API-ключ — скопируйте его из Google Cloud Console заново, "
                "целиком и без пробелов по краям")
    if r in ("accessnotconfigured", "servicedisabled") or "has not been used" in m:
        return ("в вашем проекте Google Cloud не включён YouTube Data API v3. "
                "Включите его (Library -> YouTube Data API v3 -> Enable) и подождите "
                "2–3 минуты, пока настройка разойдётся по серверам Google")
    # Google пишет reason как ipRefererBlocked — с одной «r», как HTTP-заголовок
    # Referer. На всякий случай ловим и вариант с двумя.
    if r in ("iprefererblocked", "ipreferrerblocked", "referrernotallowed", "referernotallowed") \
            or "blocked" in m or "referer" in m:
        return ("ключ ограничен настройками (по IP, сайту или приложению) и не принимает "
                "запросы с этого компьютера. В Google Cloud Console откройте ключ и "
                "поставьте Application restrictions = None")
    if r == "forbidden" and ("unregistered callers" in m or "established identity" in m):
        return "запрос ушёл без API-ключа — вставьте ключ в окне входа (кружок «YT»)"
    if r in ("ratelimitexceeded", "userratelimitexceeded"):
        return "слишком много запросов подряд, YouTube временно притормозил — повторите сбор через минуту"
    if r == "playlistnotfound":
        return "у канала нет доступного списка загруженных роликов"
    if http_code == 404 or r in ("channelnotfound", "notfound", "videonotfound"):
        return "канал не найден — проверьте ссылку в экране «Аккаунты» (возможно, канал удалён или переименован)"
    return "ошибка YouTube API (HTTP %s%s)%s" % (
        http_code,
        ", " + reason if reason else "",
        ": " + message[:160] if message else "",
    )


def _parse_api_error(raw_body):
    """Достаёт reason/message из JSON-ответа об ошибке Google."""
    try:
        data = json.loads(raw_body)
        err = data.get("error", {}) or {}
        errors = err.get("errors") or []
        reason = (errors[0].get("reason") if errors else "") or err.get("status", "") or ""
        message = err.get("message") or (errors[0].get("message") if errors else "") or ""
        return reason, message
    except Exception:
        return "", (raw_body or "")[:200]


def _api_get(endpoint, params, api_key):
    """Один GET к YouTube Data API v3 с повторами при временных сбоях.

    Возвращает разобранный JSON или бросает YouTubeError с понятной причиной.
    """
    query = dict(params)
    query["key"] = api_key
    url = API_ROOT + endpoint + "?" + urllib.parse.urlencode(query, safe=",@")

    last_network_error = ""
    for attempt in range(HTTP_RETRIES):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))

        except urllib.error.HTTPError as e:
            # HTTPError — это ответ сервера с кодом ошибки, тело содержит подробности.
            try:
                body = e.read().decode("utf-8", "replace")
            except Exception:
                body = ""
            reason, message = _parse_api_error(body)
            transient = e.code in (500, 502, 503, 504) or \
                reason.lower() in ("backenderror", "ratelimitexceeded", "userratelimitexceeded")
            if transient and attempt < HTTP_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
                last_network_error = "HTTP %s %s" % (e.code, reason)
                continue
            raise YouTubeError(_friendly_error(e.code, reason, message), reason)

        except urllib.error.URLError as e:
            # Нет сети, DNS не отвечает, проблема с сертификатами.
            if isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
                raise YouTubeError(
                    "компьютер не может проверить сертификат Google. На macOS это лечится "
                    "запуском «Install Certificates.command» из папки установленного Python "
                    "(Программы -> Python 3.x)", "ssl",
                )
            last_network_error = str(getattr(e, "reason", e))
            if attempt < HTTP_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
                continue

        except (TimeoutError, OSError) as e:
            last_network_error = str(e)
            if attempt < HTTP_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
                continue

    raise YouTubeError(
        "нет связи с YouTube API после %d попыток (%s) — проверьте интернет"
        % (HTTP_RETRIES, last_network_error or "причина неизвестна"), "network",
    )


# ---------------------------------------------------------------- разбор ссылки
_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


def parse_channel_ref(raw):
    """Разбирает то, что пользователь вписал в колонку YouTube.

    Возвращает пару (тип, значение), где тип — один из:
        "id"       — готовый ID канала UCxxxxxxxx…
        "handle"   — современный хэндл @nickname
        "username" — старое имя пользователя (/user/Name)
        "custom"   — старый произвольный адрес (/c/Name), тип канала неизвестен
        "video"    — дали ссылку на ролик, канал вычислим по нему

    Понимает: полную ссылку с http/https и без, /channel/UC…, /@хэндл,
    /@хэндл/videos, /c/Название, /user/Имя, youtu.be/…, watch?v=…, /shorts/…,
    а также просто «@nickname» или «nickname» без ссылки вообще.
    """
    s = (raw or "").strip()
    if not s:
        raise YouTubeError("не заполнена ссылка на YouTube-канал (экран «Аккаунты»)", "empty")

    if _CHANNEL_ID_RE.match(s):
        return "id", s
    if s.startswith("@"):
        return "handle", s.split("/")[0].split("?")[0]

    low = s.lower()
    if not low.startswith(("http://", "https://")):
        # Голый ник без точек и слэшей — считаем хэндлом.
        if "/" not in s and "." not in s:
            return "handle", "@" + s
        s = "https://" + s

    parsed = urllib.parse.urlparse(s)
    host = parsed.netloc.lower()
    if "youtu" not in host:
        raise YouTubeError("это не похоже на ссылку YouTube: %s" % raw.strip()[:80], "not_youtube")

    parts = [p for p in parsed.path.split("/") if p]

    if host.endswith("youtu.be"):
        if parts:
            return "video", parts[0]
        raise YouTubeError("в короткой ссылке youtu.be нет идентификатора ролика", "bad_url")

    if not parts:
        raise YouTubeError("в ссылке нет имени канала: %s" % raw.strip()[:80], "bad_url")

    head = parts[0]
    if head.startswith("@"):
        return "handle", head
    if head == "channel" and len(parts) > 1:
        return "id", parts[1]
    if head == "user" and len(parts) > 1:
        return "username", parts[1]
    if head == "c" and len(parts) > 1:
        return "custom", parts[1]
    if head == "watch":
        video_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        if video_id:
            return "video", video_id
        raise YouTubeError("в ссылке на ролик нет параметра v=", "bad_url")
    if head in ("shorts", "live", "embed", "v") and len(parts) > 1:
        return "video", parts[1]

    # Что-то вроде youtube.com/SomeName — старая форма произвольного адреса.
    return "custom", head


# ---------------------------------------------------------------- кэш каналов
_cache_lock = threading.Lock()
_cache = None


def _load_cache():
    global _cache
    if _cache is None:
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    return _cache


def _cache_get(key):
    with _cache_lock:
        return _load_cache().get(key)


def _cache_put(key, value):
    with _cache_lock:
        cache = _load_cache()
        cache[key] = value
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # кэш — только ускорение, его потеря ничего не ломает


# ---------------------------------------------------------------- шаги сбора
def _channel_id_by(param_name, value, api_key, quota):
    """channels.list по одному из параметров поиска канала. None — если не нашлось."""
    data = _api_get("channels", {"part": "id", param_name: value}, api_key)
    quota.add(1)
    items = data.get("items") or []
    return items[0].get("id") if items else None


def _resolve_channel_id(kind, value, api_key, quota):
    """Превращает разобранную ссылку в ID канала (UC…)."""
    if kind == "id":
        return value

    if kind == "video":
        data = _api_get("videos", {"part": "snippet", "id": value}, api_key)
        quota.add(1)
        items = data.get("items") or []
        if not items:
            raise YouTubeError("ролик по этой ссылке не найден (удалён или ссылка неверна)", "videoNotFound")
        return (items[0].get("snippet") or {}).get("channelId")

    if kind == "handle":
        return _channel_id_by("forHandle", value, api_key, quota)

    if kind == "username":
        found = _channel_id_by("forUsername", value, api_key, quota)
        if not found:  # старое имя часто совпадает с современным хэндлом
            found = _channel_id_by("forHandle", "@" + value, api_key, quota)
        return found

    # kind == "custom": /c/Название. Сначала пробуем дешёвые варианты.
    found = _channel_id_by("forHandle", "@" + value, api_key, quota)
    if not found:
        found = _channel_id_by("forUsername", value, api_key, quota)
    if not found and YT_ALLOW_SEARCH_FALLBACK:
        data = _api_get(
            "search", {"part": "snippet", "type": "channel", "maxResults": "1", "q": value}, api_key
        )
        quota.add(100)  # search.list — самый дорогой вызов в API
        items = data.get("items") or []
        if items:
            found = (items[0].get("id") or {}).get("channelId") or \
                    (items[0].get("snippet") or {}).get("channelId")
            diagnostics.log("WARNING", "youtube.search_fallback",
                            "Канал найден дорогим поиском (100 юнитов) — впишите в «Аккаунты» "
                            "современную ссылку вида youtube.com/@ник, чтобы не тратить квоту",
                            query=value, channel_id=found)
    return found


def _fetch_channel_info(channel_id, api_key, quota):
    """statistics + contentDetails канала за один вызов."""
    data = _api_get(
        "channels", {"part": "statistics,contentDetails,snippet", "id": channel_id}, api_key
    )
    quota.add(1)
    items = data.get("items") or []
    if not items:
        raise YouTubeError(
            "канал не найден — проверьте ссылку в экране «Аккаунты» "
            "(возможно, канал удалён или переименован)", "channelNotFound",
        )
    item = items[0]
    stats = item.get("statistics") or {}
    uploads = ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
    return {
        "title": (item.get("snippet") or {}).get("title") or "",
        "uploads_playlist": uploads,
        "subscribers": None if stats.get("hiddenSubscriberCount") else _to_int(stats.get("subscriberCount")),
        "channel_views": _to_int(stats.get("viewCount")),
        "video_count": _to_int(stats.get("videoCount")),
    }


def parse_scope(scope_key):
    """Ключ охвата из app_state -> (режим, число). Неизвестное = вся история."""
    key = (scope_key or "all").strip()
    if key.startswith("last_"):
        try:
            return "last_n", int(key[5:])
        except ValueError:
            pass
    elif key.startswith("days_"):
        try:
            return "days", int(key[5:])
        except ValueError:
            pass
    return "all", 0


def _fetch_upload_ids(playlist_id, api_key, quota, scope_key="all"):
    """ID роликов из плейлиста «Загрузки», от свежих к старым.

    Плейлист отсортирован от новых к старым, а playlistItems отдаёт дату
    публикации ВМЕСТЕ со списком (videoPublishedAt). Поэтому при охвате
    «за N дней» чтение обрывается на первом же старом ролике — статистика
    по старым роликам вообще не запрашивается. На канале с 526 роликами это
    3 юнита и 1,5 секунды вместо 23 юнитов и 11 секунд.

    Возвращает (список_id, обрезано_ли_по_потолку).
    """
    mode, amount = parse_scope(scope_key)
    limit = YT_MAX_VIDEOS
    if mode == "last_n":
        limit = min(YT_MAX_VIDEOS, max(1, amount))
    cutoff = None
    if mode == "days":
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=max(1, amount))

    ids = []
    page_token = None
    while True:
        params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": "50"}
        if page_token:
            params["pageToken"] = page_token
        try:
            data = _api_get("playlistItems", params, api_key)
        except YouTubeError as e:
            if e.reason.lower() in ("playlistnotfound", "notfound"):
                return [], False  # канал есть, роликов нет — это не ошибка
            raise
        quota.add(1)
        for item in data.get("items") or []:
            details = item.get("contentDetails") or {}
            video_id = details.get("videoId")
            if not video_id:
                continue
            if cutoff is not None:
                published = _parse_ts(details.get("videoPublishedAt"))
                # Плейлист идёт от свежих к старым: первый ролик старше среза
                # означает, что дальше все старые — читать больше нечего.
                if published is not None and published < cutoff:
                    return ids, False
            ids.append(video_id)
            if len(ids) >= limit:
                return ids, mode == "all" and len(ids) >= YT_MAX_VIDEOS
        page_token = data.get("nextPageToken")
        if not page_token:
            return ids, False


def _parse_ts(value):
    """«2025-08-27T15:21:42Z» -> datetime с зоной UTC."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _sum_video_stats(video_ids, api_key, quota):
    """videos.list батчами по 50 ID -> суммы просмотров/лайков/комментариев.

    likeCount и commentCount отсутствуют, если автор скрыл лайки или отключил
    комментарии — такие ролики считаем нулём по этой метрике, но запоминаем
    их количество, чтобы честно написать об этом в тех.журнал.
    """
    totals = {"views": 0, "likes": 0, "comments": 0}
    counted = 0
    hidden_likes = 0
    hidden_comments = 0

    for start in range(0, len(video_ids), 50):
        batch = video_ids[start:start + 50]
        data = _api_get("videos", {"part": "statistics", "id": ",".join(batch)}, api_key)
        quota.add(1)
        for item in data.get("items") or []:
            stats = item.get("statistics") or {}
            totals["views"] += _to_int(stats.get("viewCount")) or 0
            if "likeCount" in stats:
                totals["likes"] += _to_int(stats.get("likeCount")) or 0
            else:
                hidden_likes += 1
            if "commentCount" in stats:
                totals["comments"] += _to_int(stats.get("commentCount")) or 0
            else:
                hidden_comments += 1
            counted += 1

    return totals, counted, hidden_likes, hidden_comments


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- точка входа
def collect(account, credentials, scope_key="all"):
    """Собирает метрики одного канала. Формат ответа — контракт mock_backend.

    Успех:  {"ok": True, "views": .., "likes": .., "comments": .., ...доп.поля}
    Неудача: {"ok": False, "error": "понятная человеку причина"}
    Настоящий сбой (баг, неожиданный формат ответа) — исключение наружу,
    его поймает main_window.py и запишет в тех.журнал с трассировкой.
    """
    api_key = ((credentials or {}).get("key") or "").strip()
    if not api_key:
        return {"ok": False, "error": "не введён API-ключ YouTube — нажмите кружок «YT» и вставьте ключ"}

    raw_link = (account.get("yt") or "").strip()
    account_name = account.get("name", "")
    quota = _Quota()

    try:
        kind, value = parse_channel_ref(raw_link)

        cache_key = "%s:%s" % (kind, value.lower())
        channel_id = _cache_get(cache_key) if kind != "id" else value
        if not channel_id:
            channel_id = _resolve_channel_id(kind, value, api_key, quota)
            if not channel_id:
                return {"ok": False, "error": "канал не найден по ссылке «%s» — проверьте её "
                                              "в экране «Аккаунты»" % raw_link[:60]}
            _cache_put(cache_key, channel_id)

        info = _fetch_channel_info(channel_id, api_key, quota)

        if not info["uploads_playlist"]:
            return {"ok": False, "error": "у канала нет доступного списка загруженных роликов"}

        video_ids, truncated = _fetch_upload_ids(info["uploads_playlist"], api_key, quota, scope_key)
        totals, counted, hidden_likes, hidden_comments = _sum_video_stats(video_ids, api_key, quota)

        views = totals["views"]
        # Накопительный счётчик канала относится ко ВСЕМ роликам, поэтому при
        # суженном охвате он смешал бы разные наборы — берём его только для «всей истории».
        if YT_VIEWS_SOURCE == "channel" and info["channel_views"] is not None \
                and parse_scope(scope_key)[0] == "all":
            views = info["channel_views"]

        diagnostics.log(
            "INFO", "youtube.channel", "Канал собран",
            account=account_name, channel=info["title"], channel_id=channel_id, scope=scope_key,
            subscribers=info["subscribers"], channel_views=info["channel_views"],
            videos_on_channel=info["video_count"], videos_counted=counted,
            truncated=truncated, hidden_likes=hidden_likes, hidden_comments=hidden_comments,
            quota_units=quota.units,
        )
        if truncated:
            diagnostics.log("WARNING", "youtube.truncated",
                            "Учтены только %d самых свежих роликов (потолок YT_MAX_VIDEOS)" % YT_MAX_VIDEOS,
                            account=account_name, channel=info["title"])

        return {
            "ok": True,
            "views": views,
            "likes": totals["likes"],
            "comments": totals["comments"],
            # Ниже — дополнительные поля. UI их не показывает (он читает только
            # views/likes/comments), но они видны в тех.журнале и пригодятся,
            # когда в таблицу добавят колонку подписчиков.
            "subscribers": info["subscribers"],
            "channel_views": info["channel_views"],
            "videos_counted": counted,
            "channel_title": info["title"],
            "channel_id": channel_id,
            "quota_units": quota.units,
        }

    except YouTubeError as e:
        diagnostics.log("WARNING", "youtube.fail", str(e), account=account_name,
                        link=raw_link[:120], reason=e.reason, quota_units=quota.units)
        return {"ok": False, "error": str(e)}


def check_api_key(api_key):
    """Быстрая проверка ключа одним дешёвым запросом (1 юнит).

    Возвращает (True, "") или (False, "причина"). Используется в selftest,
    а в дальнейшем может пригодиться и в окне входа.
    """
    key = (api_key or "").strip()
    if not key:
        return False, "ключ не введён"
    try:
        _api_get("channels", {"part": "id", "forHandle": "@YouTube"}, key)
        return True, ""
    except YouTubeError as e:
        return False, str(e)
