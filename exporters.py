# -*- coding: utf-8 -*-
"""Экспорт собранных метрик — Excel / CSV / TXT / PDF.

Все четыре функции имеют одинаковую сигнатуру (accounts, results) -> путь_к_файлу
(или None, если пользователь отменил диалог сохранения или запись не удалась) —
main_window.py вызывает нужную по выбору пользователя во всплывающем меню кнопки
"Экспорт", не заботясь о том, что происходит внутри.
"""
import csv
import datetime
from tkinter import filedialog

import openpyxl
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm

from app_state import PLATFORMS, PLATFORM_LABELS

HEADERS = ["Аккаунт", "Тематика", "Платформа", "Просмотры", "Прирост просмотров",
           "Лайки", "Прирост лайков", "Комментарии", "Прирост комментариев", "Статус"]

STATUS_LABELS = {
    "none": "нет входа", "idle": "ожидает сбора", "pending": "в процессе",
    "done": "собрано", "error": "ошибка",
}


def _rows(accounts, results):
    """Общая подготовка строк — одна и та же таблица для всех форматов.

    Колонки прироста заполняются только со второго замера: сравнивать первый
    сбор не с чем. Пустая ячейка честнее нуля — ноль означал бы «не выросло».
    """
    out = []
    for acc in accounts:
        name = acc["name"]
        for p in PLATFORMS:
            r = results.get(name, {}).get(p, {"status": "none"})
            delta = r.get("delta") or {}

            def value(metric):
                return r.get(metric) if r.get(metric) is not None else ""

            def growth(metric):
                return delta.get(metric) if delta.get(metric) is not None else ""

            out.append([
                name, acc.get("topic", ""), PLATFORM_LABELS[p],
                value("views"), growth("views"),
                value("likes"), growth("likes"),
                value("comments"), growth("comments"),
                STATUS_LABELS.get(r.get("status"), r.get("status")),
            ])
    return out


def _ask_path(ext, filetype_label):
    return filedialog.asksaveasfilename(
        defaultextension="." + ext, initialfile="easygrab_export." + ext,
        filetypes=[(filetype_label, "*." + ext)],
    )


# ------------------------------------------------------- буфер обмена (TSV)
def build_tsv(accounts, results):
    """Та же таблица, но текстом с разделителем-табуляцией.

    Табуляция выбрана не случайно: Google Таблицы и Excel при вставке из
    буфера раскладывают такой текст по колонкам сами, без «Мастера импорта».
    Заголовки включены — чтобы вставлять на чистый лист одним движением.
    """
    lines = ["\t".join(HEADERS)]
    for row in _rows(accounts, results):
        lines.append("\t".join("" if cell is None else str(cell) for cell in row))
    return "\n".join(lines)


# ---------------------------------------------------------------- Excel
def export_xlsx(accounts, results):
    path = _ask_path("xlsx", "Excel")
    if not path:
        return None
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Метрики"
    ws.append(HEADERS)
    for row in _rows(accounts, results):
        ws.append(row)
    try:
        wb.save(path)
        return path
    except Exception:
        return None


# ---------------------------------------------------------------- CSV
def export_csv(accounts, results):
    path = _ask_path("csv", "CSV")
    if not path:
        return None
    try:
        with open(path, "w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig — чтобы Excel не путал кириллицу
            writer = csv.writer(f)
            writer.writerow(HEADERS)
            writer.writerows(_rows(accounts, results))
        return path
    except Exception:
        return None


# ---------------------------------------------------------------- TXT
def export_txt(accounts, results):
    path = _ask_path("txt", "Текстовый файл")
    if not path:
        return None
    rows = _rows(accounts, results)
    widths = [max(len(str(HEADERS[i])), *(len(str(r[i])) for r in rows)) if rows else len(HEADERS[i])
             for i in range(len(HEADERS))]
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("EasyGrab — метрики (%s)\n\n" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
            f.write("  ".join(str(HEADERS[i]).ljust(widths[i]) for i in range(len(HEADERS))) + "\n")
            f.write("-" * (sum(widths) + 2 * (len(HEADERS) - 1)) + "\n")
            for row in rows:
                f.write("  ".join(str(row[i]).ljust(widths[i]) for i in range(len(row))) + "\n")
        return path
    except Exception:
        return None


# ---------------------------------------------------------------- PDF
def export_pdf(accounts, results):
    path = _ask_path("pdf", "PDF")
    if not path:
        return None
    rows = _rows(accounts, results)
    try:
        doc = SimpleDocTemplate(path, pagesize=landscape(A4),
                                topMargin=1.5 * cm, bottomMargin=1.5 * cm)
        styles = getSampleStyleSheet()
        elements = [
            Paragraph("EasyGrab — метрики", styles["Title"]),
            Paragraph(datetime.datetime.now().strftime("Сформировано: %Y-%m-%d %H:%M"), styles["Normal"]),
            Spacer(1, 0.5 * cm),
        ]
        table_data = [HEADERS] + [[str(c) for c in row] for row in rows]
        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2B2B2B")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        elements.append(table)
        doc.build(elements)
        return path
    except Exception:
        return None
