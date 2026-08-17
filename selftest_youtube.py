# -*- coding: utf-8 -*-
"""Самопроверка сбора YouTube — без запуска интерфейса.

Два режима.

1) Без аргументов — проверка логики на подставных ответах API.
   Интернет и ключ не нужны. Прогоняет разбор всех форм ссылок, сложение
   статистики батчами, обрезку по потолку роликов, скрытые лайки и все
   разновидности ошибок (кончилась квота, канал не найден, неверный ключ).

       python3 selftest_youtube.py

2) С настоящим ключом — живая проверка того, что ключ рабочий, а канал
   отдаёт цифры. Тратит несколько юнитов квоты из 10 000.

       python3 selftest_youtube.py AIzaSy... https://www.youtube.com/@ИмяКанала

   Ссылку можно не указывать — тогда проверяется только сам ключ.
"""
import sys

import backend_youtube
from backend_youtube import YouTubeError

_passed = 0
_failed = 0


def check(name, condition, detail=""):
    global _passed, _failed
    if condition:
        _passed += 1
        print("  ✓ %s" % name)
    else:
        _failed += 1
        print("  ✗ %s %s" % (name, detail))


# ------------------------------------------------------------ подставной API
class FakeApi:
    """Заменяет собой сетевой слой: отдаёт заранее заготовленные ответы."""

    def __init__(self, channel_videos=3, hide_likes=False, raise_error=None, items_empty=False):
        self.channel_videos = channel_videos
        self.hide_likes = hide_likes
        self.raise_error = raise_error
        self.items_empty = items_empty
        self.calls = []

    def __call__(self, endpoint, params, api_key):
        self.calls.append((endpoint, dict(params)))
        if self.raise_error:
            raise self.raise_error

        if endpoint == "channels":
            if self.items_empty:
                return {"items": []}
            if params.get("part") == "id":
                return {"items": [{"id": "UCaaaaaaaaaaaaaaaaaaaaaa"}]}
            return {"items": [{
                "snippet": {"title": "Тестовый канал"},
                "statistics": {"viewCount": "999999", "subscriberCount": "1234", "videoCount": str(self.channel_videos)},
                "contentDetails": {"relatedPlaylists": {"uploads": "UUaaaaaaaaaaaaaaaaaaaaaa"}},
            }]}

        if endpoint == "playlistItems":
            page = int(params.get("pageToken", "0"))
            remaining = self.channel_videos - page * 50
            take = max(0, min(50, remaining))
            items = [{"contentDetails": {"videoId": "vid%05d" % (page * 50 + i)}} for i in range(take)]
            out = {"items": items}
            if self.channel_videos > (page + 1) * 50:
                out["nextPageToken"] = str(page + 1)
            return out

        if endpoint == "videos":
            ids = params["id"].split(",")
            items = []
            for _ in ids:
                stats = {"viewCount": "100", "commentCount": "3"}
                if not self.hide_likes:
                    stats["likeCount"] = "10"
                items.append({"statistics": stats})
            return {"items": items}

        raise AssertionError("неожиданный вызов API: %s" % endpoint)


def with_fake(fake, func):
    """Подменяет сетевой слой на время одного вызова."""
    original = backend_youtube._api_get
    backend_youtube._api_get = fake
    # кэш каналов сбивал бы счётчик вызовов — отключаем его на время теста
    original_get, original_put = backend_youtube._cache_get, backend_youtube._cache_put
    backend_youtube._cache_get = lambda key: None
    backend_youtube._cache_put = lambda key, value: None
    try:
        return func()
    finally:
        backend_youtube._api_get = original
        backend_youtube._cache_get = original_get
        backend_youtube._cache_put = original_put


def http_error(code, reason, message=""):
    """Собирает настоящий HTTPError с телом ответа Google."""
    import io
    import json
    import urllib.error
    body = json.dumps({"error": {"code": code, "message": message,
                                 "errors": [{"reason": reason, "message": message}]}}).encode("utf-8")
    return urllib.error.HTTPError("http://test", code, reason, {}, io.BytesIO(body))


class _FakeResponse:
    """Минимальный ответ, который умеет работать как контекстный менеджер."""

    def __init__(self, payload):
        import json
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHttp:
    """Подменяет urlopen — то есть САМЫЙ низкий уровень.

    Так проверяется настоящий разбор ошибок и настоящие повторы внутри
    _api_get, а не только код выше него.

    make_error — фабрика (вызывается на каждую попытку, чтобы у повторов было
    своё непрочитанное тело ответа); fail_times — сколько первых попыток
    провалить, дальше отдаётся payload.
    """

    def __init__(self, make_error=None, fail_times=None, payload=None):
        self.make_error = make_error
        self.fail_times = fail_times
        self.payload = payload if payload is not None else {"items": []}
        self.attempts = 0

    def __call__(self, req, timeout=None):
        self.attempts += 1
        if self.make_error and (self.fail_times is None or self.attempts <= self.fail_times):
            raise self.make_error()
        return _FakeResponse(self.payload)


class _NoSleep:
    """Заглушка модуля time — чтобы повторы в тесте не ждали по-настоящему."""

    @staticmethod
    def sleep(_seconds):
        return None

    @staticmethod
    def perf_counter():
        return 0.0


def with_fake_http(fake_http, func):
    """Подменяет сетевой слой на уровне urlopen (и убирает паузы повторов)."""
    import urllib.request
    original_urlopen = urllib.request.urlopen
    original_time = backend_youtube.time
    original_get, original_put = backend_youtube._cache_get, backend_youtube._cache_put
    urllib.request.urlopen = fake_http
    backend_youtube.time = _NoSleep
    backend_youtube._cache_get = lambda key: None
    backend_youtube._cache_put = lambda key, value: None
    try:
        return func()
    finally:
        urllib.request.urlopen = original_urlopen
        backend_youtube.time = original_time
        backend_youtube._cache_get = original_get
        backend_youtube._cache_put = original_put


# ------------------------------------------------------------------- проверки
def test_link_parsing():
    print("\nРазбор ссылок на канал")
    cases = [
        ("https://www.youtube.com/@trappedunderwater", ("handle", "@trappedunderwater")),
        ("https://www.youtube.com/@trappedunderwater/videos", ("handle", "@trappedunderwater")),
        ("http://www.youtube.com/@CeSomething", ("handle", "@CeSomething")),
        ("youtube.com/@nick", ("handle", "@nick")),
        ("@nick", ("handle", "@nick")),
        ("nick", ("handle", "@nick")),
        ("UCaaaaaaaaaaaaaaaaaaaaaa", ("id", "UCaaaaaaaaaaaaaaaaaaaaaa")),
        ("https://www.youtube.com/channel/UCbbbbbbbbbbbbbbbbbbbbbb", ("id", "UCbbbbbbbbbbbbbbbbbbbbbb")),
        ("https://www.youtube.com/c/SomeOldName", ("custom", "SomeOldName")),
        ("https://www.youtube.com/user/LegacyName", ("username", "LegacyName")),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", ("video", "dQw4w9WgXcQ")),
        ("https://youtu.be/dQw4w9WgXcQ", ("video", "dQw4w9WgXcQ")),
        ("https://www.youtube.com/shorts/abc123", ("video", "abc123")),
        ("  https://www.youtube.com/@nick/  ", ("handle", "@nick")),
    ]
    for raw, expected in cases:
        try:
            got = backend_youtube.parse_channel_ref(raw)
        except YouTubeError as e:
            got = "ошибка: %s" % e
        check("%-52s -> %s" % (raw.strip()[:52], expected[0]), got == expected, "получено %r" % (got,))

    for bad in ("", "   ", "https://vimeo.com/12345"):
        try:
            backend_youtube.parse_channel_ref(bad)
            check("отвергает %r" % bad, False, "ошибки не было")
        except YouTubeError:
            check("отвергает %r" % bad, True)


def test_happy_path():
    print("\nОбычный сбор (3 ролика)")
    fake = FakeApi(channel_videos=3)
    result = with_fake(fake, lambda: backend_youtube.collect(
        {"name": "Блогер 1", "yt": "https://www.youtube.com/@nick"}, {"key": "TESTKEY"}))
    check("ok = True", result.get("ok") is True, result.get("error", ""))
    check("просмотры 3 x 100 = 300", result.get("views") == 300, "получено %s" % result.get("views"))
    check("лайки 3 x 10 = 30", result.get("likes") == 30, "получено %s" % result.get("likes"))
    check("комментарии 3 x 3 = 9", result.get("comments") == 9, "получено %s" % result.get("comments"))
    check("подписчики попали в доп.поля", result.get("subscribers") == 1234)
    check("накопительные просмотры канала", result.get("channel_views") == 999999)
    endpoints = [c[0] for c in fake.calls]
    check("порядок вызовов channels -> playlistItems -> videos",
          endpoints == ["channels", "channels", "playlistItems", "videos"], str(endpoints))
    check("квота 4 юнита", result.get("quota_units") == 4, "получено %s" % result.get("quota_units"))


def test_batching():
    print("\nБатчи по 50 (120 роликов)")
    fake = FakeApi(channel_videos=120)
    result = with_fake(fake, lambda: backend_youtube.collect(
        {"name": "Блогер 2", "yt": "UCaaaaaaaaaaaaaaaaaaaaaa"}, {"key": "TESTKEY"}))
    check("ok = True", result.get("ok") is True, result.get("error", ""))
    check("учтено 120 роликов", result.get("videos_counted") == 120, "получено %s" % result.get("videos_counted"))
    check("просмотры 120 x 100", result.get("views") == 12000, "получено %s" % result.get("views"))
    video_calls = [c for c in fake.calls if c[0] == "videos"]
    check("3 вызова videos.list (50+50+20)", len(video_calls) == 3, "получено %d" % len(video_calls))
    check("в первом батче ровно 50 ID",
          len(video_calls[0][1]["id"].split(",")) == 50, video_calls[0][1]["id"][:40])
    playlist_calls = [c for c in fake.calls if c[0] == "playlistItems"]
    check("3 страницы плейлиста", len(playlist_calls) == 3, "получено %d" % len(playlist_calls))


def test_cap():
    print("\nПотолок YT_MAX_VIDEOS")
    original = backend_youtube.YT_MAX_VIDEOS
    backend_youtube.YT_MAX_VIDEOS = 60
    try:
        fake = FakeApi(channel_videos=500)
        result = with_fake(fake, lambda: backend_youtube.collect(
            {"name": "Блогер 3", "yt": "@nick"}, {"key": "TESTKEY"}))
        check("учтено ровно 60 роликов", result.get("videos_counted") == 60,
              "получено %s" % result.get("videos_counted"))
        check("плейлист не читался дальше нужного",
              len([c for c in fake.calls if c[0] == "playlistItems"]) == 2)
    finally:
        backend_youtube.YT_MAX_VIDEOS = original


def test_hidden_likes():
    print("\nЛайки скрыты автором")
    fake = FakeApi(channel_videos=2, hide_likes=True)
    result = with_fake(fake, lambda: backend_youtube.collect(
        {"name": "Блогер 4", "yt": "@nick"}, {"key": "TESTKEY"}))
    check("сбор не падает", result.get("ok") is True, result.get("error", ""))
    check("лайки = 0", result.get("likes") == 0, "получено %s" % result.get("likes"))
    check("просмотры всё равно посчитаны", result.get("views") == 200)


def test_views_source_channel():
    print("\nПереключатель YT_VIEWS_SOURCE = channel")
    original = backend_youtube.YT_VIEWS_SOURCE
    backend_youtube.YT_VIEWS_SOURCE = "channel"
    try:
        fake = FakeApi(channel_videos=3)
        result = with_fake(fake, lambda: backend_youtube.collect(
            {"name": "Блогер 5", "yt": "@nick"}, {"key": "TESTKEY"}))
        check("просмотры берутся у канала (999999)", result.get("views") == 999999,
              "получено %s" % result.get("views"))
        check("лайки по-прежнему по роликам", result.get("likes") == 30)
    finally:
        backend_youtube.YT_VIEWS_SOURCE = original


def test_errors():
    print("\nОшибки — каждая со своей понятной причиной")

    result = backend_youtube.collect({"name": "X", "yt": "@nick"}, {})
    check("пустой ключ -> просят ввести ключ",
          result.get("ok") is False and "ключ" in result["error"], str(result))

    result = backend_youtube.collect({"name": "X", "yt": ""}, {"key": "TESTKEY"})
    check("пустая ссылка -> отправляют в «Аккаунты»",
          result.get("ok") is False and "Аккаунты" in result["error"], str(result))

    def collect_via(fake_http):
        return with_fake_http(fake_http, lambda: backend_youtube.collect(
            {"name": "X", "yt": "@nick"}, {"key": "TESTKEY"}))

    result = collect_via(FakeHttp(lambda: http_error(403, "quotaExceeded", "quota exceeded")))
    check("403 quotaExceeded -> про дневную квоту",
          result.get("ok") is False and "квота" in result["error"], str(result))

    result = collect_via(FakeHttp(lambda: http_error(404, "channelNotFound")))
    check("404 -> канал не найден",
          result.get("ok") is False and "не найден" in result["error"], str(result))

    result = collect_via(FakeHttp(lambda: http_error(400, "keyInvalid", "API key not valid")))
    check("400 keyInvalid -> неверный ключ",
          result.get("ok") is False and "ключ" in result["error"], str(result))

    result = collect_via(FakeHttp(lambda: http_error(403, "accessNotConfigured",
                                                    "has not been used in project")))
    check("403 accessNotConfigured -> просят включить API",
          result.get("ok") is False and "не включён" in result["error"], str(result))

    result = collect_via(FakeHttp(lambda: http_error(403, "ipRefererBlocked", "requests from this IP")))
    check("403 ipRefererBlocked -> про ограничения ключа",
          result.get("ok") is False and "ограничен" in result["error"], str(result))

    # 503 — временный сбой: должны быть повторы, а не мгновенная сдача.
    fake = FakeHttp(lambda: http_error(503, "backendError", "backend error"))
    result = with_fake_http(fake, lambda: backend_youtube.collect(
        {"name": "X", "yt": "@nick"}, {"key": "TESTKEY"}))
    check("503 -> было %d попытки, не одна" % backend_youtube.HTTP_RETRIES,
          fake.attempts == backend_youtube.HTTP_RETRIES, "попыток: %d" % fake.attempts)
    check("503 после повторов -> ошибка, а не падение", result.get("ok") is False, str(result))

    # Сеть моргнула один раз — сбор всё равно должен завершиться успехом.
    fake = FakeHttp(lambda: http_error(503, "backendError"), fail_times=1,
                    payload={"items": [{"id": "UCaaaaaaaaaaaaaaaaaaaaaa"}]})
    with_fake_http(fake, lambda: backend_youtube._api_get("channels", {"part": "id"}, "K"))
    check("одиночный сбой сети переживается повтором", fake.attempts == 2, "попыток: %d" % fake.attempts)

    fake = FakeApi(items_empty=True)
    result = with_fake(fake, lambda: backend_youtube.collect(
        {"name": "X", "yt": "@несуществующий"}, {"key": "TESTKEY"}))
    check("пустой ответ -> канал не найден",
          result.get("ok") is False and "не найден" in result["error"], str(result))

    result = backend_youtube.collect({"name": "X", "yt": "https://vimeo.com/1"}, {"key": "TESTKEY"})
    check("чужая ссылка -> понятная причина",
          result.get("ok") is False and "не похоже" in result["error"], str(result))


def test_contract():
    print("\nКонтракт с интерфейсом")
    import mock_backend
    check("simulate_collect на месте", callable(mock_backend.simulate_collect))
    # Все три площадки подключены — «не подключён» больше не ждём ни от кого.
    for platform in ("youtube", "tiktok", "instagram"):
        check("%s подключён к диспетчеру" % platform, platform in mock_backend._COLLECTORS)
    check("площадок ровно три", len(mock_backend._COLLECTORS) == 3)
    # Незаполненная ссылка должна давать понятную причину, а не случайные числа.
    result = mock_backend.simulate_collect({"name": "X", "ig": ""}, "instagram")
    check("пустая ссылка -> понятная причина, а не число",
          result.get("ok") is False and "Аккаунты" in result.get("error", ""), str(result))
    result = mock_backend.simulate_collect({"name": "X"}, "myspace")
    check("неизвестная площадка не роняет приложение", result.get("ok") is False, str(result))


def test_scope():
    print("\nОхват сбора")
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)

    class DatedApi(FakeApi):
        """Плейлист с датами: ролик i опубликован i дней назад."""
        def __call__(self, endpoint, params, api_key):
            if endpoint == "playlistItems":
                page = int(params.get("pageToken", "0"))
                take = max(0, min(50, self.channel_videos - page * 50))
                items = []
                for i in range(take):
                    n = page * 50 + i
                    items.append({"contentDetails": {
                        "videoId": "vid%05d" % n,
                        "videoPublishedAt": (now - datetime.timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }})
                self.calls.append((endpoint, dict(params)))
                out = {"items": items}
                if self.channel_videos > (page + 1) * 50:
                    out["nextPageToken"] = str(page + 1)
                return out
            return FakeApi.__call__(self, endpoint, params, api_key)

    check("parse_scope: all", backend_youtube.parse_scope("all") == ("all", 0))
    check("parse_scope: last_7", backend_youtube.parse_scope("last_7") == ("last_n", 7))
    check("parse_scope: days_30", backend_youtube.parse_scope("days_30") == ("days", 30))
    check("parse_scope: мусор -> вся история", backend_youtube.parse_scope("абвгд") == ("all", 0))

    fake = DatedApi(channel_videos=120)
    r = with_fake(fake, lambda: backend_youtube.collect(
        {"name": "X", "yt": "@nick"}, {"key": "K"}, "last_7"))
    check("«7 роликов» -> учтено ровно 7", r.get("videos_counted") == 7, str(r.get("videos_counted")))
    check("«7 роликов» -> одна страница плейлиста, не три",
          len([c for c in fake.calls if c[0] == "playlistItems"]) == 1)

    fake = DatedApi(channel_videos=120)
    r = with_fake(fake, lambda: backend_youtube.collect(
        {"name": "X", "yt": "@nick"}, {"key": "K"}, "days_30"))
    check("«30 дней» -> учтены только ролики за 30 дней", r.get("videos_counted") == 30,
          str(r.get("videos_counted")))
    check("«30 дней» -> чтение оборвалось на первом старом ролике",
          len([c for c in fake.calls if c[0] == "playlistItems"]) == 1)

    fake = DatedApi(channel_videos=120)
    r = with_fake(fake, lambda: backend_youtube.collect(
        {"name": "X", "yt": "@nick"}, {"key": "K"}, "all"))
    check("«вся история» -> учтены все 120", r.get("videos_counted") == 120, str(r.get("videos_counted")))

    # Накопительный счётчик канала относится ко всем роликам — при суженном
    # охвате подставлять его нельзя.
    original = backend_youtube.YT_VIEWS_SOURCE
    backend_youtube.YT_VIEWS_SOURCE = "channel"
    try:
        fake = DatedApi(channel_videos=120)
        r = with_fake(fake, lambda: backend_youtube.collect(
            {"name": "X", "yt": "@nick"}, {"key": "K"}, "last_7"))
        check("при суженном охвате счётчик канала не подставляется",
              r.get("views") == 700, "получено %s" % r.get("views"))
    finally:
        backend_youtube.YT_VIEWS_SOURCE = original


def test_history():
    print("\nИстория замеров и прирост")
    import datetime, os, tempfile
    import history

    tmp = tempfile.mkdtemp()
    original_file = history.HISTORY_FILE
    history.HISTORY_FILE = os.path.join(tmp, "history.json")
    try:
        base, label = history.find_baseline("all")
        check("на пустой истории базового снимка нет", base is None and label == "")

        vchera = {"Блогер 1": {"youtube": {"status": "done", "views": 2372, "likes": 30, "comments": 1}}}
        history.append_snapshot(vchera, "all")
        # состариваем снимок на сутки, чтобы это был «вчерашний» замер
        data = history._load()
        data["snapshots"][0]["ts"] = (datetime.datetime.now() - datetime.timedelta(days=1)).isoformat(timespec="seconds")
        history._save(data)

        base, label = history.find_baseline("all")
        check("вчерашний снимок найден", base is not None)
        check("подпись периода «за сутки»", label == "за сутки", label)

        d = history.delta_for(base, "Блогер 1", "youtube", {"views": 2611, "likes": 38, "comments": 1})
        check("прирост просмотров +239", d and d["views"] == 239, str(d))
        check("прирост лайков +8", d and d["likes"] == 8, str(d))
        check("прирост комментариев 0", d and d["comments"] == 0, str(d))

        check("незнакомый аккаунт -> прироста нет",
              history.delta_for(base, "Блогер 99", "youtube", {"views": 5}) is None)

        # Главное: снимки с разным охватом не смешиваются.
        base7, _ = history.find_baseline("last_7")
        check("охват «7 роликов» не видит снимок «вся история»", base7 is None)

        # Аккаунты с ошибкой в снимок не попадают.
        history.append_snapshot({"Блогер 2": {"youtube": {"status": "error", "views": None}}}, "all")
        latest = history._load()["snapshots"][-1]
        check("ошибочный аккаунт не сохранён", "Блогер 2" not in latest.get("data", {}), str(latest))

        check("пустой сбор не создаёт снимок", history.append_snapshot({}, "all") is None)
    finally:
        history.HISTORY_FILE = original_file


def test_clipboard_tsv():
    print("\nКопирование в буфер (TSV)")
    import exporters
    results = {"Блогер 1": {"youtube": {"status": "done", "views": 2611, "likes": 38,
                                        "comments": 1, "delta": {"views": 239, "likes": 8, "comments": 0}},
                            "instagram": {"status": "error"}, "tiktok": {"status": "none"}}}
    text = exporters.build_tsv([{"name": "Блогер 1", "topic": "Дайвинг"}], results)
    lines = text.splitlines()
    check("шапка + строка на каждую площадку", len(lines) == 4, str(len(lines)))
    check("разделитель — табуляция", "\t" in lines[0])
    check("колонок столько же, сколько заголовков",
          all(len(l.split("\t")) == len(exporters.HEADERS) for l in lines), str(len(lines[1].split("\t"))))
    check("заголовок начинается с «Аккаунт»", lines[0].startswith("Аккаунт"), lines[0][:30])
    cells = lines[1].split("\t")
    check("просмотры на своём месте", cells[3] == "2611", cells[3])
    check("прирост на своём месте", cells[4] == "239", cells[4])
    check("None не просачивается в текст", "None" not in text)


def test_growth_summary():
    print("\nИтоговое окно: суммарный прирост")
    import history
    from summary_window import format_signed
    PL = ("youtube", "instagram", "tiktok")

    results = {
        "Б1": {"youtube": {"status": "done", "delta": {"views": 239, "likes": 8, "comments": 1}},
               "tiktok": {"status": "done", "delta": {"views": 1200, "likes": 45, "comments": 0}},
               "instagram": {"status": "none"}},
        "Б2": {"youtube": {"status": "done", "delta": {"views": 61, "likes": 2, "comments": 0}},
               "tiktok": {"status": "error"},
               "instagram": {"status": "none"}},
        "Б3": {"youtube": {"status": "done"},          # собрался, но сравнивать не с чем
               "tiktok": {"status": "done", "delta": {"views": -5, "likes": 0, "comments": 0}},
               "instagram": {"status": "none"}},
    }
    g = history.summarize_growth(results, PL)
    check("YouTube: 239 + 61 = 300", g["youtube"]["views"] == 300, str(g["youtube"]))
    check("TikTok: 1200 - 5 = 1195 (минус вычитается)", g["tiktok"]["views"] == 1195, str(g["tiktok"]))
    check("Instagram не собирался -> collected = 0", g["instagram"]["collected"] == 0)
    check("итог по всем = 1495", g["total"]["views"] == 1495, str(g["total"]))
    check("аккаунт без дельты посчитан как собранный", g["youtube"]["collected"] == 3,
          str(g["youtube"]["collected"]))
    check("но в прирост он не попал", g["youtube"]["with_delta"] == 2,
          str(g["youtube"]["with_delta"]))
    check("ошибочный аккаунт вообще не учтён", g["tiktok"]["collected"] == 2,
          str(g["tiktok"]["collected"]))

    empty = history.summarize_growth({}, PL)
    check("пустой сбор не роняет подсчёт", empty["total"]["collected"] == 0, str(empty["total"]))

    check("формат +239", format_signed(239) == "+239", format_signed(239))
    check("формат −12 (типографский минус)", format_signed(-12) == "−12", format_signed(-12))
    check("формат нуля", format_signed(0) == "0", format_signed(0))
    check("тысячи с пробелом: +1 495", format_signed(1495) == "+1 495", format_signed(1495))


def test_export_columns():
    print("\nЭкспорт с колонками прироста")
    import exporters
    results = {"Блогер 1": {"youtube": {"status": "done", "views": 2611, "likes": 38,
                                        "comments": 1, "delta": {"views": 239, "likes": 8, "comments": 0}},
                            "instagram": {"status": "error"},
                            "tiktok": {"status": "none"}}}
    rows = exporters._rows([{"name": "Блогер 1", "topic": "Дайвинг"}], results)
    check("строк = аккаунт x 3 площадки", len(rows) == 3, str(len(rows)))
    check("колонок столько же, сколько заголовков",
          all(len(r) == len(exporters.HEADERS) for r in rows), str(len(rows[0])))
    yt = rows[0]
    check("просмотры на месте", yt[3] == 2611, str(yt))
    check("прирост просмотров на месте", yt[4] == 239, str(yt))
    check("прирост лайков на месте", yt[6] == 8, str(yt))
    check("у несобранной площадки прирост пустой, а не 0", rows[1][4] == "", repr(rows[1][4]))


def live_test(api_key, channel_link):
    print("\nЖивая проверка настоящим ключом")
    ok, error = backend_youtube.check_api_key(api_key)
    check("ключ принят YouTube", ok, error)
    if not ok:
        return
    if not channel_link:
        print("  (ссылка на канал не указана — проверен только ключ)")
        return
    result = backend_youtube.collect({"name": "живой тест", "yt": channel_link}, {"key": api_key})
    if result.get("ok"):
        print("  Канал:       %s" % result.get("channel_title"))
        print("  Подписчики:  %s" % result.get("subscribers"))
        print("  Роликов:     %s" % result.get("videos_counted"))
        print("  Просмотры:   %s" % result.get("views"))
        print("  Лайки:       %s" % result.get("likes"))
        print("  Комментарии: %s" % result.get("comments"))
        print("  Потрачено квоты: %s юнитов из 10 000" % result.get("quota_units"))
        check("данные получены", True)
    else:
        check("данные получены", False, result.get("error", ""))


def main():
    print("=" * 64)
    print("EasyGrab — самопроверка сбора YouTube")
    print("=" * 64)

    test_link_parsing()
    test_happy_path()
    test_batching()
    test_cap()
    test_hidden_likes()
    test_views_source_channel()
    test_errors()
    test_scope()
    test_history()
    test_growth_summary()
    test_export_columns()
    test_clipboard_tsv()
    test_contract()

    if len(sys.argv) > 1:
        live_test(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")

    print("\n" + "=" * 64)
    print("Успешно: %d    Провалено: %d" % (_passed, _failed))
    print("=" * 64)
    if _failed == 0 and len(sys.argv) == 1:
        print("Логика в порядке. Теперь проверьте настоящий ключ:")
        print("    python3 selftest_youtube.py ВАШ_КЛЮЧ https://www.youtube.com/@ВашКанал")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
