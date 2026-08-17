# -*- coding: utf-8 -*-
"""Выбор шрифтов по ОС — чтобы не хардкодить Windows-шрифты вроде Segoe UI,
которых нет на macOS/Linux. Использовать вместо литеральных ("Segoe UI", 12).
"""
import platform

_SYSTEM = platform.system()  # "Windows" / "Darwin" (macOS) / "Linux"

if _SYSTEM == "Darwin":
    _UI_FAMILY = "Helvetica"
    _MONO_FAMILY = "Menlo"
elif _SYSTEM == "Windows":
    _UI_FAMILY = "Segoe UI"
    _MONO_FAMILY = "Consolas"
else:
    _UI_FAMILY = "Helvetica"
    _MONO_FAMILY = "Courier New"


def ui_font(size=12, weight="normal"):
    return (_UI_FAMILY, size, weight) if weight != "normal" else (_UI_FAMILY, size)


def mono_font(size=11):
    return (_MONO_FAMILY, size)
