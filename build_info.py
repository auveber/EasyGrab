# -*- coding: utf-8 -*-
"""Версия и дата сборки — считаются сами, а не правятся руками.

Раньше и то, и другое было вписано константами в app_state.py. Дата так
и осталась на 12.08, когда код правился 17-го: про неё просто забывали.
Забывать будут всегда, поэтому теперь она вычисляется.

Как это работает. При запуске снимается отпечаток исходников — хэш содержимого
всех .py рядом с приложением. Если он отличается от сохранённого, значит код
изменился: номер сборки увеличивается на единицу, дата ставится сегодняшняя.
Если не отличается — версия и дата остаются прежними, сколько бы раз
приложение ни запускали.

Стадия («beta») остаётся ручной: это решение о зрелости продукта, его
не вычислить из файлов. Меняется одной строкой в app_state.py.

Всё хранится в build.json рядом с приложением. Если файл не удаётся записать
(например, приложение лежит в папке только для чтения) — версия просто
не растёт, ничего не ломается.
"""
import datetime
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD_FILE = os.path.join(HERE, "build.json")

# С какого номера продолжаем. Меняется только при смене стадии
# («beta 0.x» -> «release 1.x»), в остальное время растёт сам.
FIRST_BUILD = 4


def _source_fingerprint():
    """Отпечаток исходников: хэш содержимого всех .py рядом с приложением.

    Именно содержимого, а не времени изменения: время меняется от любого
    копирования папки, а нас интересуют настоящие правки кода.
    """
    digest = hashlib.sha256()
    for name in sorted(os.listdir(HERE)):
        if not name.endswith(".py"):
            continue
        try:
            with open(os.path.join(HERE, name), "rb") as f:
                digest.update(name.encode("utf-8"))
                digest.update(f.read())
        except OSError:
            continue
    return digest.hexdigest()


def _load():
    try:
        with open(BUILD_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data):
    try:
        with open(BUILD_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False        # только для чтения — не беда, версия просто не вырастет


def resolve():
    """Возвращает (номер_сборки, дата_строкой).

    Вызывается один раз при импорте app_state, дальше значения не меняются
    в течение работы приложения.
    """
    stored = _load()
    fingerprint = _source_fingerprint()
    today = datetime.date.today().strftime("%d.%m.%Y")

    if stored.get("fingerprint") == fingerprint and stored.get("build"):
        return stored["build"], stored.get("date", today)

    build = int(stored.get("build", FIRST_BUILD - 1)) + 1 if stored else FIRST_BUILD
    _save({"build": build, "date": today, "fingerprint": fingerprint})
    return build, today
