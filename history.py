# -*- coding: utf-8 -*-
"""История замеров и дневной прирост.

Зачем это нужно. Публичные API соцсетей отдают только НАКОПИТЕЛЬНЫЕ счётчики
(«просмотров за всё время»), без разбивки по дням. Посуточная динамика есть
только в YouTube Analytics API, а он требует OAuth-входа в аккаунт владельца
канала — то есть связал бы 20 рабочих аккаунтов в одну систему, чего делать
нельзя. Поэтому прирост считаем сами: сохраняем снимок после каждого сбора
и вычитаем из сегодняшнего вчерашний. Ровно как в таблице «Продакшн»,
где значения записаны в виде «2611 (+239)».

Файл history.json лежит рядом с приложением. Секретов в нём нет — только
названия аккаунтов и числа, его можно спокойно пересылать.

ВАЖНО про охват. Снимок запоминает, с каким охватом он снят («вся история»,
«последние 7 роликов» и т.д.). Прирост считается только между снимками
с ОДИНАКОВЫМ охватом — иначе вычитание «7 роликов» из «всей истории» дало бы
бессмысленное число.
"""
import datetime
import json
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(HERE, "history.json")

MAX_SNAPSHOTS = 500  # с запасом на полтора года ежедневных замеров
METRICS = ("views", "likes", "comments")

_lock = threading.Lock()


def _load():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"snapshots": []}
    except Exception:
        return {"snapshots": []}


def _save(data):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False


def append_snapshot(results, scope_key):
    """Сохраняет успешно собранные числа как один снимок с отметкой времени.

    results — та же структура, что в main_window: results[аккаунт][площадка].
    Аккаунты со статусом «ошибка» в снимок не попадают: иначе завтрашний
    прирост считался бы от несуществующего нуля и получился бы огромным.
    """
    payload = {}
    for name, platforms in (results or {}).items():
        for platform, cell in (platforms or {}).items():
            if cell.get("status") != "done":
                continue
            payload.setdefault(name, {})[platform] = {m: cell.get(m) for m in METRICS}

    if not payload:
        return None  # собирать нечего — пустой снимок не пишем

    snapshot = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "scope": scope_key,
        "data": payload,
    }
    with _lock:
        data = _load()
        data.setdefault("snapshots", []).append(snapshot)
        if len(data["snapshots"]) > MAX_SNAPSHOTS:
            del data["snapshots"][: len(data["snapshots"]) - MAX_SNAPSHOTS]
        _save(data)
    return snapshot


def find_baseline(scope_key):
    """Снимок, с которым сравнивать текущий сбор.

    Берём последний снимок с тем же охватом, сделанный в ПРЕДЫДУЩИЙ
    календарный день — тогда прирост читается как «за сегодня». Если сегодня
    первый день замеров, но раньше сегодня уже собирали, берём тот замер
    (и честно подписываем, что сравнение внутридневное).

    Возвращает (данные, подпись_периода) или (None, "").
    """
    with _lock:
        snapshots = [s for s in _load().get("snapshots", []) if s.get("scope") == scope_key]
    if not snapshots:
        return None, ""

    today = datetime.date.today()
    earlier_days = []
    same_day = []
    for s in snapshots:
        try:
            ts = datetime.datetime.fromisoformat(s["ts"])
        except Exception:
            continue
        (same_day if ts.date() >= today else earlier_days).append((ts, s))

    chosen = max(earlier_days or same_day, key=lambda pair: pair[0], default=None)
    if not chosen:
        return None, ""

    ts, snapshot = chosen
    if ts.date() >= today:
        label = "с %s сегодня" % ts.strftime("%H:%M")
    else:
        days = (today - ts.date()).days
        label = "за сутки" if days == 1 else "за %d дн. (с %s)" % (days, ts.strftime("%d.%m"))
    return snapshot.get("data", {}), label


def delta_for(baseline, name, platform, result):
    """Прирост по одному аккаунту и площадке: сегодня минус базовый снимок.

    Возвращает {"views": +239, "likes": +5, "comments": 0} либо None, если
    сравнивать не с чем (аккаунт новый или в прошлый раз не собрался).
    """
    if not baseline:
        return None
    previous = (baseline.get(name) or {}).get(platform)
    if not previous:
        return None

    out = {}
    for metric in METRICS:
        now_value, was_value = result.get(metric), previous.get(metric)
        if isinstance(now_value, int) and isinstance(was_value, int):
            out[metric] = now_value - was_value
    return out or None


def summarize_growth(results, platforms):
    """Суммарный прирост по каждой площадке и по всем сразу.

    Считается по тем же дельтам, что показаны в таблице, поэтому цифры
    в итоговом окне и в ячейках всегда сходятся — второй раз ничего
    не пересчитывается.

    Для каждой площадки возвращает:
        collected  — сколько аккаунтов собралось
        with_delta — у скольких было с чем сравнивать
        views/likes/comments — суммы прироста
    Плюс ключ "total" с суммой по всем площадкам.
    """
    out = {}
    total = {m: 0 for m in METRICS}
    total_collected = total_with_delta = 0

    for platform in platforms:
        row = {m: 0 for m in METRICS}
        collected = with_delta = 0
        for cell in (results or {}).values():
            data = (cell or {}).get(platform) or {}
            if data.get("status") != "done":
                continue
            collected += 1
            delta = data.get("delta")
            if not delta:
                continue
            with_delta += 1
            for m in METRICS:
                value = delta.get(m)
                if isinstance(value, int):
                    row[m] += value
        row["collected"] = collected
        row["with_delta"] = with_delta
        out[platform] = row

        total_collected += collected
        total_with_delta += with_delta
        for m in METRICS:
            total[m] += row[m]

    total["collected"] = total_collected
    total["with_delta"] = total_with_delta
    out["total"] = total
    return out


def snapshot_count(scope_key=None):
    """Сколько замеров уже накоплено — показывается в тех.журнале."""
    with _lock:
        snapshots = _load().get("snapshots", [])
    if scope_key is None:
        return len(snapshots)
    return sum(1 for s in snapshots if s.get("scope") == scope_key)
