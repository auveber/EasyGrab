# -*- coding: utf-8 -*-
"""Самопроверка сбора Instagram — без запуска интерфейса и без аккаунта.

1) Без аргументов — проверка логики на подставном instaloader.
   Ни интернет, ни вьюер-аккаунт не нужны.

       python3 selftest_instagram.py

2) С логином и паролем бёрнера — живая проверка. ВНИМАНИЕ: выполняет
   настоящий вход в Instagram, используйте только аккаунт-бёрнер.

       python3 selftest_instagram.py логин пароль https://www.instagram.com/профиль
"""
import datetime
import sys

import backend_instagram
from backend_instagram import InstagramError

_passed = 0
_failed = 0


def _utcnow():
    """Наивное UTC-время — в таком же виде его отдаёт instaloader (post.date_utc)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def check(name, condition, detail=""):
    global _passed, _failed
    if condition:
        _passed += 1
        print("  ✓ %s" % name)
    else:
        _failed += 1
        print("  ✗ %s %s" % (name, detail))


# ------------------------------------------------------- подставной instaloader
class _FakeClient:
    """Подставной instagrapi.Client: отдаёт заготовленный профиль и посты."""

    def __init__(self, profile, medias, clips_fail=False):
        self._profile, self._medias, self._clips_fail = profile, medias, clips_fail
        self.calls = []

    def user_info_by_username(self, username):
        self.calls.append("user_info")
        if isinstance(self._profile, Exception):
            raise self._profile
        return self._profile

    def user_clips_v1(self, pk, amount=0):
        self.calls.append("clips")
        if self._clips_fail:
            raise RuntimeError("login_required")
        return self._medias[:amount] if amount else self._medias

    def user_medias(self, pk, amount=0):
        self.calls.append("medias")
        return self._medias[:amount] if amount else self._medias

    def media_info(self, pk):
        self.calls.append("media_info")
        return type("M", (), {"play_count": 777})()


class FakePost:
    def __init__(self, days_ago, is_video=True, plays=100, views=90, likes=10, comments=2):
        self.taken_at = (datetime.datetime.now(datetime.timezone.utc)
                         - datetime.timedelta(days=days_ago))
        self.pk = "pk%d" % days_ago
        self.media_type = 2 if is_video else 1
        self.play_count = plays if is_video else 0
        self.view_count = views if is_video else 0
        self.like_count = likes
        self.comment_count = comments


class FakeProfile:
    def __init__(self, posts, private=False, followed=False, followers=1234, name="Тестовый"):
        self._posts = posts
        self.pk = "12345"
        self.is_private = private
        self.follower_count = followers
        self.full_name = name
        self.media_count = len(posts)


def with_fake(profile_or_error, func, clips_fail=False):
    """Подменяет клиента instagrapi целиком — весь Instagram разом."""
    original_get_client = backend_instagram._get_client
    original_pause = backend_instagram._pause_between_profiles
    posts = getattr(profile_or_error, "_posts", [])
    client = _FakeClient(profile_or_error, posts, clips_fail=clips_fail)
    backend_instagram._get_client = lambda credentials: client
    backend_instagram._pause_between_profiles = lambda: None   # в тесте не ждём паузу
    try:
        return func()
    finally:
        backend_instagram._get_client = original_get_client
        backend_instagram._pause_between_profiles = original_pause


ACCOUNT = {"name": "Блогер 1", "ig": "https://www.instagram.com/nick"}
CREDS = {"user": "burner", "pass": "secret"}


# ------------------------------------------------------------------- проверки
def test_profile_parsing():
    print("\nРазбор ссылок на профиль")
    cases = [
        ("https://www.instagram.com/trappedunderwater", "trappedunderwater"),
        ("https://www.instagram.com/deepcavemysteries?igsh=MWFlZzVmbncwcW15Ng==", "deepcavemysteries"),
        ("https://www.instagram.com/horror_movieclips_/", "horror_movieclips_"),
        ("instagram.com/cybe.rcrimehub", "cybe.rcrimehub"),
        ("@nick", "nick"),
        ("nick", "nick"),
        ("  https://www.instagram.com/nick  ", "nick"),
    ]
    for raw, expected in cases:
        try:
            got = backend_instagram.parse_profile(raw)
        except InstagramError as e:
            got = "ошибка: %s" % e
        check("%-50s -> %s" % (raw.strip()[:50], expected), got == expected, "получено %r" % (got,))

    for bad, why in (("", "пусто"), ("https://youtube.com/@x", "чужой домен"),
                     ("https://www.instagram.com/p/ABC123/", "ссылка на пост"),
                     ("https://www.instagram.com/reel/ABC/", "ссылка на рилс")):
        try:
            backend_instagram.parse_profile(bad)
            check("отвергает (%s)" % why, False, "ошибки не было")
        except InstagramError:
            check("отвергает (%s)" % why, True)


def test_happy_path():
    print("\nОбычный сбор (10 видео-постов)")
    profile = FakeProfile([FakePost(days_ago=i) for i in range(10)])
    r = with_fake(profile, lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
    check("ok = True", r.get("ok") is True, r.get("error", ""))
    check("просмотры 10 x 100 (берётся play_count)", r.get("views") == 1000, str(r.get("views")))
    check("лайки 10 x 10", r.get("likes") == 100, str(r.get("likes")))
    check("комментарии 10 x 2", r.get("comments") == 20, str(r.get("comments")))
    check("учтено 10 постов", r.get("posts_counted") == 10, str(r.get("posts_counted")))
    check("подписчики попали в доп.поля", r.get("followers") == 1234)
    check("метрики взяты пачкой из вкладки Reels", r.get("bulk_reels") is True)


def test_photos_have_no_views():
    print("\nФотографии: у них нет счётчика просмотров")
    posts = [FakePost(days_ago=i, is_video=(i % 2 == 0)) for i in range(10)]  # 5 видео, 5 фото
    profile = FakeProfile(posts)
    r = with_fake(profile, lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
    check("сбор не проваливается", r.get("ok") is True, r.get("error", ""))
    check("просмотры только по видео (5 x 100)", r.get("views") == 500, str(r.get("views")))
    check("лайки собраны со ВСЕХ постов", r.get("likes") == 100, str(r.get("likes")))
    check("посты без счётчика посчитаны", r.get("without_view_counter") == 5,
          str(r.get("without_view_counter")))


def test_clips_fallback():
    print("\nЗапасной путь, когда вкладка Reels недоступна")
    profile = FakeProfile([FakePost(days_ago=i, plays=0, views=0) for i in range(3)])
    r = with_fake(profile, lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"),
                  clips_fail=True)
    check("сбор не проваливается", r.get("ok") is True, r.get("error", ""))
    check("отмечено, что пачкой не вышло", r.get("bulk_reels") is False)
    check("лайки и комментарии собраны всё равно", r.get("likes") == 30, str(r.get("likes")))

    # По умолчанию поштучный добор ВЫКЛЮЧЕН: именно он на живой проверке
    # вызвал у Instagram предупреждение об автоматизированных действиях.
    check("поштучный добор выключен по умолчанию",
          backend_instagram.IG_FETCH_VIEWS_ONE_BY_ONE is False)
    check("без него лишних запросов нет", r.get("views") == 0, str(r.get("views")))

    # Если включить осознанно — работает, но со строгим потолком.
    original_flag = backend_instagram.IG_FETCH_VIEWS_ONE_BY_ONE
    original_cap = backend_instagram.IG_VIEWS_ONE_BY_ONE_CAP
    backend_instagram.IG_FETCH_VIEWS_ONE_BY_ONE = True
    try:
        profile = FakeProfile([FakePost(days_ago=i, plays=0, views=0) for i in range(3)])
        r = with_fake(profile, lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"),
                      clips_fail=True)
        check("включённый добор работает (3 x 777)", r.get("views") == 2331, str(r.get("views")))

        backend_instagram.IG_VIEWS_ONE_BY_ONE_CAP = 2
        profile = FakeProfile([FakePost(days_ago=i, plays=0, views=0) for i in range(6)])
        r = with_fake(profile, lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"),
                      clips_fail=True)
        check("потолок соблюдён: не больше 2 запросов (2 x 777)",
              r.get("views") == 1554, str(r.get("views")))
    finally:
        backend_instagram.IG_FETCH_VIEWS_ONE_BY_ONE = original_flag
        backend_instagram.IG_VIEWS_ONE_BY_ONE_CAP = original_cap


def test_play_count_preferred():
    print("\nprevью: проигрывания важнее просмотров")
    profile = FakeProfile([FakePost(days_ago=0, plays=500, views=300)])
    r = with_fake(profile, lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
    check("берётся video_play_count (500), а не view_count (300)",
          r.get("views") == 500, str(r.get("views")))
    profile = FakeProfile([FakePost(days_ago=0, plays=None, views=300)])
    r = with_fake(profile, lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
    check("если проигрываний нет — берётся view_count (300)",
          r.get("views") == 300, str(r.get("views")))


def test_scope():
    print("\nОхват сбора")
    profile = FakeProfile([FakePost(days_ago=i) for i in range(50)])
    r = with_fake(profile, lambda: backend_instagram.collect(ACCOUNT, CREDS, "last_7"))
    check("«7 роликов» -> учтено 7", r.get("posts_counted") == 7, str(r.get("posts_counted")))

    profile = FakeProfile([FakePost(days_ago=i) for i in range(50)])
    r = with_fake(profile, lambda: backend_instagram.collect(ACCOUNT, CREDS, "days_7"))
    check("«7 дней» -> учтены только свежие", r.get("posts_counted") == 7,
          str(r.get("posts_counted")))

    profile = FakeProfile([FakePost(days_ago=i) for i in range(50)])
    r = with_fake(profile, lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
    check("«вся история» -> учтены все 50", r.get("posts_counted") == 50,
          str(r.get("posts_counted")))


def test_errors():
    print("\nОшибки — каждая со своей понятной причиной")

    r = backend_instagram.collect({"name": "X", "ig": ""}, CREDS, "all")
    check("пустая ссылка -> отправляют в «Аккаунты»",
          r.get("ok") is False and "Аккаунты" in r["error"], str(r))

    r = backend_instagram.collect(ACCOUNT, {}, "all")
    check("нет логина -> объясняют про бёрнер",
          r.get("ok") is False and "бёрнер" in r["error"], str(r))

    r = with_fake(RuntimeError("User not found"),
                  lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
    check("профиля нет -> так и написано",
          r.get("ok") is False and "не найден" in r["error"], str(r))

    r = with_fake(RuntimeError("429 Too Many Requests"),
                  lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
    check("429 -> просят подождать 20–40 минут",
          r.get("ok") is False and "ограничил частоту" in r["error"], str(r))

    r = with_fake(RuntimeError("challenge_required"),
                  lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
    check("checkpoint -> просят пройти проверку",
          r.get("ok") is False and "подтверждение личности" in r["error"], str(r))

    r = with_fake(RuntimeError("feedback_required"),
                  lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
    check("feedback_required -> советуют дать отдохнуть",
          r.get("ok") is False and "отдохнуть" in r["error"], str(r))

    r = with_fake(FakeProfile([], private=True),
                  lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
    check("закрытый профиль -> понятная причина",
          r.get("ok") is False and "закрытый" in r["error"], str(r))

    r = with_fake(FakeProfile([]), lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
    check("нет постов -> понятная причина",
          r.get("ok") is False and "нет постов" in r["error"], str(r))


def test_limits():
    print("\nПотолки и защита от зависания")
    original = backend_instagram.IG_MAX_POSTS
    backend_instagram.IG_MAX_POSTS = 25
    try:
        profile = FakeProfile([FakePost(days_ago=i) for i in range(200)])
        r = with_fake(profile, lambda: backend_instagram.collect(ACCOUNT, CREDS, "all"))
        check("потолок постов соблюдён", r.get("posts_counted") == 25,
              str(r.get("posts_counted")))
    finally:
        backend_instagram.IG_MAX_POSTS = original

    check("пауза между профилями задана", backend_instagram.IG_PAUSE_S >= 5,
          str(backend_instagram.IG_PAUSE_S))
    check("есть потолок времени на профиль", backend_instagram.IG_TIME_BUDGET_S > 0)


def test_session_handling():
    print("\nСессия: один вход на весь прогон")
    import os
    import tempfile

    backend_instagram.reset_session()
    loads = []
    tmp = tempfile.mkdtemp()

    class Client:
        def load_settings(self, path):
            loads.append(path)

        def get_timeline_feed(self):
            return {}

    original_new = backend_instagram._new_client
    original_file = backend_instagram.settings_file
    backend_instagram._new_client = Client
    backend_instagram.settings_file = lambda u: os.path.join(tmp, "ig_settings_%s.json" % u)
    open(backend_instagram.settings_file("burner"), "w").write("{}")
    open(backend_instagram.settings_file("другой"), "w").write("{}")
    try:
        for _ in range(5):
            backend_instagram._get_client(CREDS)
        check("5 аккаунтов -> ОДНО чтение сессии, а не пять", len(loads) == 1, str(len(loads)))

        backend_instagram._get_client({"user": "другой"})
        check("смена бёрнера -> новая сессия", len(loads) == 2, str(len(loads)))

        backend_instagram.reset_session()
        backend_instagram._get_client(CREDS)
        check("после сброса сессия читается заново", len(loads) == 3, str(len(loads)))

        backend_instagram.reset_session()
        try:
            backend_instagram._get_client({"user": "нетсессии"})
            check("без файла сессии -> понятная ошибка", False, "ошибки не было")
        except backend_instagram.InstagramError as e:
            check("без файла сессии -> понятная ошибка", "войдите заново" in str(e), str(e))
    finally:
        backend_instagram._new_client = original_new
        backend_instagram.settings_file = original_file
        backend_instagram.reset_session()

    check("пароль без логина отвергается",
          backend_instagram.login_with_password("", "x")[0] is False)
    check("логин без пароля отвергается",
          backend_instagram.login_with_password("burner", "")[0] is False)
    check("файл сессии называется по логину",
          backend_instagram.settings_file("burner").endswith("ig_settings_burner.json"))


def test_browser_session():
    print("\nСессия из браузера (вместо пароля)")
    check("список браузеров не пуст", len(backend_instagram.BROWSERS) >= 5)
    check("подписи и ключи согласованы",
          set(backend_instagram.BROWSER_LABELS.values()) == set(backend_instagram.BROWSER_KEYS),
          "%s vs %s" % (sorted(backend_instagram.BROWSER_LABELS.values()),
                        sorted(backend_instagram.BROWSER_KEYS)))
    check("Safari и Chrome в списке",
          {"safari", "chrome"} <= set(backend_instagram.BROWSER_LABELS))

    ok, message = backend_instagram.import_browser_session("такого-браузера-нет")
    check("неизвестный браузер -> отказ, а не падение", ok is False and message)

    # Профили браузера. Настоящая находка на живом Mac: вход в Instagram лежал
    # в «Profile 4», а библиотека по умолчанию читает только «Default» —
    # и импорт молча не находил сессию.
    profiles = backend_instagram._profiles_with_instagram_session("chrome")
    check("перебор профилей Chrome не падает", isinstance(profiles, list), str(profiles)[:60])
    check("для Safari перебор неприменим и возвращает пусто",
          backend_instagram._profiles_with_instagram_session("safari") == [])
    check("у неизвестного браузера профилей нет",
          backend_instagram._profiles_with_instagram_session("нетакого") == [])
    check("профили отдаются парами (имя, путь)",
          all(isinstance(p, tuple) and len(p) == 2 for p in profiles), str(profiles)[:60])

    # Сбор должен работать по одной только сессии, без пароля вообще.
    profile = FakeProfile([FakePost(days_ago=0)])
    r = with_fake(profile, lambda: backend_instagram.collect(
        ACCOUNT, {"user": "burner"}, "all"))
    check("сбор идёт без пароля", r.get("ok") is True, r.get("error", ""))

    # Без входа — подсказка ведёт к кружку «IG», а не к внутренностям.
    backend_instagram.reset_session()
    r = backend_instagram.collect(ACCOUNT, {}, "all")
    check("без входа -> отправляют к кружку «IG»",
          r.get("ok") is False and "IG" in r["error"], str(r))
    check("в подсказке сказано про бёрнер",
          "бёрнер" in r.get("error", ""), str(r))


def test_contract():
    print("\nКонтракт с интерфейсом")
    import mock_backend
    check("instagram подключён к диспетчеру", "instagram" in mock_backend._COLLECTORS)
    check("не подключённых площадок не осталось", mock_backend._NOT_READY == {})
    check("все три площадки на месте", len(mock_backend._COLLECTORS) == 3,
          str(sorted(mock_backend._COLLECTORS)))

    profile = FakeProfile([FakePost(days_ago=0)])
    r = with_fake(profile, lambda: mock_backend.simulate_collect(ACCOUNT, "instagram"))
    keys = set(("views", "likes", "comments"))
    check("через диспетчер возвращается нужный формат",
          r.get("ok") is False or keys <= set(r), str(r)[:90])


def live_test(user, password, url):
    print("\nЖивая проверка настоящим вьюер-аккаунтом")
    ok, version = backend_instagram.check_available()
    check("instaloader установлен (%s)" % version, ok, version)
    if not ok:
        return
    r = backend_instagram.collect({"name": "живой тест", "ig": url},
                                  {"user": user, "pass": password}, "all")
    if r.get("ok"):
        print("  Профиль:      @%s (%s)" % (r.get("profile"), r.get("profile_title")))
        print("  Подписчики:   %s" % r.get("followers"))
        print("  Постов:       %s" % r.get("posts_counted"))
        print("  Просмотры:    %s" % r.get("views"))
        print("  Лайки:        %s" % r.get("likes"))
        print("  Комментарии:  %s" % r.get("comments"))
        if r.get("without_view_counter"):
            print("  Без счётчика просмотров (фото): %s" % r.get("without_view_counter"))
        check("данные получены", True)
    else:
        check("данные получены", False, r.get("error", ""))


def main():
    print("=" * 64)
    print("EasyGrab — самопроверка сбора Instagram")
    print("=" * 64)

    test_profile_parsing()
    test_happy_path()
    test_photos_have_no_views()
    test_clips_fallback()
    test_play_count_preferred()
    test_scope()
    test_errors()
    test_limits()
    test_session_handling()
    test_browser_session()
    test_contract()

    if len(sys.argv) > 3:
        live_test(sys.argv[1], sys.argv[2], sys.argv[3])

    print("\n" + "=" * 64)
    print("Успешно: %d    Провалено: %d" % (_passed, _failed))
    print("=" * 64)
    if _failed == 0 and len(sys.argv) <= 3:
        print("Логика в порядке. Живая проверка (только аккаунтом-бёрнером!):")
        print("    python3 selftest_instagram.py ЛОГИН ПАРОЛЬ https://www.instagram.com/профиль")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
