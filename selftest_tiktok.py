# -*- coding: utf-8 -*-
"""Самопроверка сбора TikTok — без запуска интерфейса.

1) Без аргументов — проверка логики на подставном yt-dlp. Интернет не нужен.

       python3 selftest_tiktok.py

2) С ссылкой — живая проверка настоящего профиля через yt-dlp.

       python3 selftest_tiktok.py https://www.tiktok.com/@ИмяПрофиля
"""
import datetime
import json
import subprocess
import sys

import backend_tiktok
from backend_tiktok import TikTokError

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


# ------------------------------------------------------------ подставной yt-dlp
class FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeRun:
    """Подменяет subprocess.run — то есть настоящий вызов yt-dlp.

    Так проверяется реальный разбор JSON и реальный перевод ошибок,
    а не только код над ними.
    """

    def __init__(self, videos=21, stderr="", stdout=None, timeout=False, zero_views=False):
        self.videos = videos
        self.stderr = stderr
        self.stdout = stdout
        self.timeout = timeout
        self.zero_views = zero_views
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if self.timeout:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 90))
        if self.stdout is not None:
            return FakeProc(stdout=self.stdout, stderr=self.stderr)
        if self.stderr:
            return FakeProc(stdout="", stderr=self.stderr, returncode=1)

        # yt-dlp отдаёт ролики от свежих к старым; ролик i опубликован i дней назад
        now = datetime.datetime.now(datetime.timezone.utc)
        limit = int(args[args.index("--playlist-end") + 1]) if "--playlist-end" in args else self.videos
        entries = []
        for i in range(min(self.videos, limit)):
            entries.append({
                "id": "vid%03d" % i,
                "title": "ролик %d" % i,
                "view_count": 0 if self.zero_views else 100,
                "like_count": 10,
                "comment_count": 2,
                "timestamp": (now - datetime.timedelta(days=i)).timestamp(),
                "channel": "Тестовый профиль",
            })
        return FakeProc(stdout=json.dumps({"title": "Тестовый профиль", "entries": entries}))


def with_fake(fake, func):
    original = subprocess.run
    subprocess.run = fake
    try:
        return func()
    finally:
        subprocess.run = original


# ------------------------------------------------------------------- проверки
def test_profile_parsing():
    print("\nРазбор ссылок на профиль")
    cases = [
        ("https://www.tiktok.com/@freedive.shadows", "@freedive.shadows"),
        ("https://www.tiktok.com/@freedive.shadows?_r=1&_t=ZS-98oy9OD9ISm", "@freedive.shadows"),
        ("https://www.tiktok.com/@coldcase.files_", "@coldcase.files_"),
        ("tiktok.com/@nick", "@nick"),
        ("www.tiktok.com/@nick/", "@nick"),
        ("@nick", "@nick"),
        ("nick", "@nick"),
        ("https://www.tiktok.com/@user/video/7673049027490876680", "@user"),
        ("  https://www.tiktok.com/@nick  ", "@nick"),
    ]
    for raw, expected in cases:
        try:
            got = backend_tiktok.parse_profile(raw)
        except TikTokError as e:
            got = "ошибка: %s" % e
        check("%-52s -> %s" % (raw.strip()[:52], expected), got == expected, "получено %r" % (got,))

    for bad in ("", "   ", "https://youtube.com/@x", "https://www.tiktok.com/foo/bar"):
        try:
            backend_tiktok.parse_profile(bad)
            check("отвергает %r" % bad, False, "ошибки не было")
        except TikTokError:
            check("отвергает %r" % bad, True)


def test_happy_path():
    print("\nОбычный сбор (21 ролик)")
    fake = FakeRun(videos=21)
    r = with_fake(fake, lambda: backend_tiktok.collect(
        {"name": "Блогер 1", "tt": "https://www.tiktok.com/@nick"}, {}, "all"))
    check("ok = True", r.get("ok") is True, r.get("error", ""))
    check("просмотры 21 x 100", r.get("views") == 2100, str(r.get("views")))
    check("лайки 21 x 10", r.get("likes") == 210, str(r.get("likes")))
    check("комментарии 21 x 2", r.get("comments") == 42, str(r.get("comments")))
    check("учтён 21 ролик", r.get("videos_counted") == 21, str(r.get("videos_counted")))
    check("ровно ОДИН вызов yt-dlp на профиль", len(fake.calls) == 1, str(len(fake.calls)))
    check("используется --flat-playlist", "--flat-playlist" in fake.calls[0])
    check("yt-dlp запускается как модуль текущего Python",
          fake.calls[0][:3] == [sys.executable, "-m", "yt_dlp"], str(fake.calls[0][:3]))


def test_scope():
    print("\nОхват сбора")
    fake = FakeRun(videos=50)
    r = with_fake(fake, lambda: backend_tiktok.collect(
        {"name": "X", "tt": "@nick"}, {}, "last_7"))
    check("«7 роликов» -> учтено 7", r.get("videos_counted") == 7, str(r.get("videos_counted")))
    check("у yt-dlp запрошено только 7", "--playlist-end" in fake.calls[0]
          and fake.calls[0][fake.calls[0].index("--playlist-end") + 1] == "7", str(fake.calls[0]))

    fake = FakeRun(videos=50)
    r = with_fake(fake, lambda: backend_tiktok.collect(
        {"name": "X", "tt": "@nick"}, {}, "days_7"))
    check("«7 дней» -> учтены только свежие", r.get("videos_counted") == 7,
          str(r.get("videos_counted")))

    fake = FakeRun(videos=50)
    r = with_fake(fake, lambda: backend_tiktok.collect(
        {"name": "X", "tt": "@nick"}, {}, "all"))
    check("«вся история» -> учтены все 50", r.get("videos_counted") == 50,
          str(r.get("videos_counted")))


def test_errors():
    print("\nОшибки — каждая со своей понятной причиной")
    r = backend_tiktok.collect({"name": "X", "tt": ""}, {}, "all")
    check("пустая ссылка -> отправляют в «Аккаунты»",
          r.get("ok") is False and "Аккаунты" in r["error"], str(r))

    def run(fake):
        return with_fake(fake, lambda: backend_tiktok.collect(
            {"name": "X", "tt": "@nick"}, {}, "all"))

    # Настоящий текст yt-dlp про несуществующий профиль.
    r = run(FakeRun(stdout="null",
                    stderr="ERROR: [tiktok:user] zzz: Unable to extract secondary user ID"))
    check("несуществующий профиль -> «профиль не найден»",
          r.get("ok") is False and "не найден" in r["error"], str(r))

    r = run(FakeRun(stdout="null", stderr="ERROR: This account is private"))
    check("закрытый профиль -> про приватность",
          r.get("ok") is False and "закрыт" in r["error"], str(r))

    r = run(FakeRun(stderr="ERROR: HTTP Error 429: Too Many Requests"))
    check("429 -> просят подождать",
          r.get("ok") is False and "ограничил" in r["error"], str(r))

    r = run(FakeRun(stderr="ERROR: captcha required to verify"))
    check("капча -> объясняют, что делать",
          r.get("ok") is False and "робот" in r["error"], str(r))

    r = run(FakeRun(timeout=True))
    check("таймаут не роняет сбор", r.get("ok") is False, str(r))

    r = run(FakeRun(stdout='{"entries": []}'))
    check("пустой профиль -> понятная причина",
          r.get("ok") is False and "нет роликов" in r["error"], str(r))

    r = run(FakeRun(stdout="не json вовсе", stderr="ERROR: broken"))
    check("мусор вместо JSON не роняет приложение", r.get("ok") is False, str(r))


def test_zero_views():
    print("\nНулевые просмотры при живых лайках (признак теневого бана)")
    fake = FakeRun(videos=17, zero_views=True)
    r = with_fake(fake, lambda: backend_tiktok.collect(
        {"name": "Блогер 4", "tt": "@nick"}, {}, "all"))
    check("сбор НЕ проваливается", r.get("ok") is True, r.get("error", ""))
    check("просмотры 0", r.get("views") == 0, str(r.get("views")))
    check("лайки всё равно собраны", r.get("likes") == 170, str(r.get("likes")))
    check("количество таких роликов отмечено", r.get("zero_view_videos") == 17,
          str(r.get("zero_view_videos")))


def test_versions():
    print("\nВерсии и даты сборки")
    check("2026.07.04 -> 04.07.2026", backend_tiktok.version_date("2026.07.04") == "04.07.2026",
          backend_tiktok.version_date("2026.07.04"))
    check("2026.7.4 (без нулей) -> та же дата", backend_tiktok.version_date("2026.7.4") == "04.07.2026")
    check("мусор -> пустая строка", backend_tiktok.version_date("абвгд") == "")
    check("неполная версия -> пустая строка", backend_tiktok.version_date("2026.7") == "")
    check("нереальный месяц -> пустая строка", backend_tiktok.version_date("2026.99.1") == "")

    vt = backend_tiktok._version_tuple
    check("сравнение чисел, а не строк: 2026.07.04 == 2026.7.4",
          vt("2026.07.04") == vt("2026.7.4"))
    check("2026.9.1 новее, чем 2026.07.04", vt("2026.9.1") > vt("2026.07.04"))
    check("2027.1.1 новее, чем 2026.12.31", vt("2027.1.1") > vt("2026.12.31"))
    # Вот случай, где сравнение строками врёт: "2026.10.1" < "2026.9.1" как текст,
    # то есть октябрьская версия «старше» сентябрьской. Числами — правильно.
    check("октябрь новее сентября (числами)", vt("2026.10.1") > vt("2026.9.1"))
    check("а строками это сравнение врёт", "2026.10.1" < "2026.9.1")


def test_no_login():
    print("\nTikTok без входа")
    from app_state import state, NO_LOGIN_PLATFORMS
    check("tiktok в списке площадок без входа", "tiktok" in NO_LOGIN_PLATFORMS)
    check("готов к сбору сразу", state.login_status.get("tiktok") is True)
    # Пустой «вход» не должен выключать площадку.
    state.set_login("tiktok", False, data={}, remember=False)
    check("пустой вход не выключает TikTok", state.login_status.get("tiktok") is True)
    check("сбор не требует данных входа",
          backend_tiktok.collect.__code__.co_argcount == 3)


def test_contract():
    print("\nКонтракт с интерфейсом")
    import mock_backend
    from app_state import state, NO_LOGIN_PLATFORMS
    check("tiktok подключён к диспетчеру", "tiktok" in mock_backend._COLLECTORS)
    check("instagram ещё честно говорит, что не готов",
          mock_backend.simulate_collect({"name": "X"}, "instagram").get("ok") is False)
    check("TikTok не требует входа", "tiktok" in NO_LOGIN_PLATFORMS)
    check("TikTok готов к сбору сразу при старте", state.login_status.get("tiktok") is True)

    fake = FakeRun(videos=3)
    r = with_fake(fake, lambda: mock_backend.simulate_collect(
        {"name": "X", "tt": "@nick"}, "tiktok"))
    check("через диспетчер возвращается нужный формат",
          r.get("ok") is True and set(("views", "likes", "comments")) <= set(r), str(r))


def live_test(url):
    print("\nЖивая проверка настоящего профиля")
    ok, version = backend_tiktok.check_available()
    check("yt-dlp установлен (%s)" % version, ok, version)
    if not ok:
        return
    r = backend_tiktok.collect({"name": "живой тест", "tt": url}, {}, "all")
    if r.get("ok"):
        print("  Профиль:     %s" % r.get("profile"))
        print("  Роликов:     %s" % r.get("videos_counted"))
        print("  Просмотры:   %s" % r.get("views"))
        print("  Лайки:       %s" % r.get("likes"))
        print("  Комментарии: %s" % r.get("comments"))
        if r.get("zero_view_videos"):
            print("  ⚠ роликов с нулевыми просмотрами: %s" % r.get("zero_view_videos"))
        check("данные получены", True)
    else:
        check("данные получены", False, r.get("error", ""))


def main():
    print("=" * 64)
    print("EasyGrab — самопроверка сбора TikTok")
    print("=" * 64)

    test_profile_parsing()
    test_happy_path()
    test_scope()
    test_errors()
    test_zero_views()
    test_versions()
    test_no_login()
    test_contract()

    if len(sys.argv) > 1:
        live_test(sys.argv[1])

    print("\n" + "=" * 64)
    print("Успешно: %d    Провалено: %d" % (_passed, _failed))
    print("=" * 64)
    if _failed == 0 and len(sys.argv) == 1:
        print("Логика в порядке. Теперь проверьте живой профиль:")
        print("    python3 selftest_tiktok.py https://www.tiktok.com/@ВашПрофиль")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
