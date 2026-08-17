# -*- coding: utf-8 -*-
"""Технический журнал EasyGrab — отдельно от дружелюбного лога в главном окне.

Дружелюбный лог (self.log_box в main_window.py) показывает пользователю
короткие понятные строки. Этот модуль параллельно копит куда более подробную
техническую картину: каждый вызов сбора (успех/неудача/длительность),
необработанные исключения (в том числе в фоновом потоке сбора) и падения
приложения — всё, что нужно для разбора проблемы, а не для повседневного
использования.

Использование:
    import diagnostics
    diagnostics.install_exception_hooks()   # один раз при старте (main.py)
    diagnostics.log("INFO", "collect.start", "Запуск сбора", platforms=["youtube"])
    ...
    diagnostics.export_report("/путь/к/файлу.txt")
"""
import datetime
import platform as platform_module
import sys
import threading
import traceback

_MAX_EVENTS = 5000
_events = []  # список dict: {"ts":.., "level":.., "category":.., "message":.., "fields":{...}}
_lock = threading.Lock()


def log(level, category, message="", **fields):
    """Добавить запись в технический журнал. level: DEBUG/INFO/WARNING/ERROR/CRITICAL."""
    entry = {
        "ts": datetime.datetime.now(),
        "level": level,
        "category": category,
        "message": message,
        "fields": fields,
    }
    with _lock:
        _events.append(entry)
        if len(_events) > _MAX_EVENTS:
            del _events[: len(_events) - _MAX_EVENTS]


def log_exception(category, message, exc):
    """Записать исключение вместе с полной трассировкой — для настоящих сбоев,
    в отличие от «ожидаемых» ошибок вида {"ok": False, "error": ...}."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log("ERROR", category, message, exception=str(exc), traceback=tb)


def install_exception_hooks():
    """Ловит необработанные исключения в основном потоке и в фоновых потоках
    (например, в потоке сбора метрик), чтобы падение приложения тоже попало
    в технический журнал, а не просто исчезло в консоли."""

    def _on_main_thread_exception(exc_type, exc_value, exc_tb):
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log("CRITICAL", "crash.main_thread", "Необработанное исключение в основном потоке",
            exception=str(exc_value), traceback=tb)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    def _on_thread_exception(args):
        tb = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        log("CRITICAL", "crash.thread", "Необработанное исключение в фоновом потоке (%s)" % args.thread.name,
            exception=str(args.exc_value), traceback=tb)

    sys.excepthook = _on_main_thread_exception
    threading.excepthook = _on_thread_exception


def _env_info():
    return (
        "ОС: %s %s\n"
        "Python: %s\n"
        % (platform_module.system(), platform_module.release(), platform_module.python_version())
    )


def _login_status_summary():
    """Только статус входа (залогинен/нет) — САМИ логины/пароли/API-ключи
    сюда никогда не попадают, чтобы диагностический файл можно было спокойно
    переслать без утечки секретов."""
    from app_state import state, PLATFORMS, PLATFORM_LABELS
    lines = []
    for p in PLATFORMS:
        status = "залогинен" if state.login_status.get(p) else "нет входа"
        lines.append("%s: %s" % (PLATFORM_LABELS[p], status))
    return "\n".join(lines)


def build_report_text():
    from app_state import APP_NAME, APP_STAGE, state

    parts = []
    parts.append("=== %s — диагностический отчёт ===" % APP_NAME)
    parts.append("Сформирован: %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    parts.append("Версия приложения: %s" % APP_STAGE)
    parts.append("")
    parts.append(_env_info())
    parts.append("--- Статус входа (без самих данных логина) ---")
    parts.append(_login_status_summary())
    parts.append("Аккаунтов в списке: %d" % len(state.accounts))
    parts.append("")
    parts.append("--- Журнал событий (%d записей) ---" % len(_events))

    with _lock:
        events_copy = list(_events)

    for e in events_copy:
        stamp = e["ts"].strftime("%H:%M:%S.%f")[:-3]
        fields_str = " ".join("%s=%s" % (k, v) for k, v in e["fields"].items() if k != "traceback")
        line = "[%s] %-8s %-20s %s %s" % (stamp, e["level"], e["category"], e["message"], fields_str)
        parts.append(line.rstrip())
        if "traceback" in e["fields"]:
            parts.append(e["fields"]["traceback"].rstrip())
            parts.append("-" * 60)

    return "\n".join(parts) + "\n"


def export_report(path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(build_report_text())
        return True
    except Exception:
        return False
