# -*- coding: utf-8 -*-
"""Итоговое окно после сбора — суммарный прирост по площадкам.

Показывается сразу по завершении сбора. Отвечает на вопрос, ради которого
всё и затевалось: сколько прибавили за сутки.

Цифры берутся из тех же дельт, что нарисованы в ячейках таблицы
(history.summarize_growth), поэтому окно и таблица не могут разойтись —
ничего не пересчитывается второй раз.

Размер окна НЕ задан числом. Строки разложены по grid: каждая колонка берёт
ровно столько ширины, сколько просит самое длинное значение в ней, а окно
подгоняется под получившееся содержимое. Поэтому при мелких числах окно
компактное, а когда метрики вырастут до миллионов — расширится само.

Кнопки: «ОК» закрывает окно, «Экспорт» открывает то же самое меню выгрузки,
что и в главном окне (копировать в буфер, xlsx, csv, txt, pdf) — цифры видны,
и тут же можно унести их в таблицу.
"""
import customtkinter as ctk

from app_state import APP_NAME, PLATFORMS, PLATFORM_COLORS, platform_label
from fonts import ui_font
import theme
from ui_utils import fade_in

METRIC_ICONS = (("\U0001F441", "views"), ("❤", "likes"), ("\U0001F4AC", "comments"))

PAD_X = 24            # поля окна по бокам
PAD_Y = 20
# Ширины кнопок задают нижнюю границу окна: при обычных числах таблица метрик
# просит меньше, чем ряд кнопок (242px против 258px), поэтому именно они
# определяют, насколько узким окно может стать.
OK_WIDTH = 88
EXPORT_WIDTH = 122
BUTTON_GAP = 20       # минимальный просвет между кнопками


def format_signed(value):
    """239 -> «+239», -12 -> «−12», 0 -> «0». Минус типографский, а не дефис."""
    if not value:
        return "0"
    return "%s%s" % ("+" if value > 0 else "−", "{:,}".format(abs(value)).replace(",", " "))


class SummaryWindow(ctk.CTkToplevel):
    def __init__(self, master, growth, period_label="", stopped=False):
        super().__init__(master)
        self.growth = growth
        self.period_label = period_label
        self.stopped = stopped

        self.title(APP_NAME)
        self.resizable(False, False)
        self.grab_set()

        self._build()
        self._fit_to_content()
        fade_in(self)

    # ---------------------------------------------------------- построение UI
    def _build(self):
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(fill="both", expand=True, padx=PAD_X, pady=PAD_Y)

        heading = "Сбор метрик остановлен" if self.stopped else "Сбор метрик завершён"
        ctk.CTkLabel(box, text=heading, font=ui_font(15, "bold")).pack(anchor="w")

        subtitle = ("Прирост %s" % self.period_label) if self.period_label else \
                   "Это первый замер — прирост появится со следующего раза"
        ctk.CTkLabel(box, text=subtitle, font=ui_font(11),
                     text_color=theme.MUTED_TEXT).pack(anchor="w", pady=(2, 14))

        # Ключевое место: grid вместо pack с зашитыми ширинами. Колонка
        # «название площадки» и колонка «метрики» подстраиваются под самое
        # длинное содержимое, лишнего места справа не остаётся.
        table = ctk.CTkFrame(box, fg_color="transparent")
        table.pack(anchor="w", fill="x")

        for row, platform in enumerate(PLATFORMS):
            self._platform_row(table, row, platform)

        # Черта отделяет итог и тянется по ширине содержимого, а не окна —
        # поля по 24px с боков остаются, поэтому она не режет окно насквозь.
        ctk.CTkFrame(table, height=1, fg_color=theme.NEUTRAL_FG).grid(
            row=len(PLATFORMS), column=0, columnspan=3, sticky="ew", pady=(12, 10))

        self._total_row(table, len(PLATFORMS) + 1)

        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.pack(side="bottom", fill="x", pady=(18, 0))
        ctk.CTkButton(
            buttons, text="ОК", corner_radius=12, width=OK_WIDTH, fg_color=theme.NEUTRAL_FG,
            text_color=theme.NEUTRAL_TEXT, hover_color=theme.NEUTRAL_FG_HOVER,
            command=self.destroy,
        ).pack(side="left")
        self.export_btn = ctk.CTkButton(
            buttons, text="Экспорт \u25be", corner_radius=12, width=EXPORT_WIDTH,
            command=self._export,
        )
        self.export_btn.pack(side="right", padx=(BUTTON_GAP, 0))

    def _platform_row(self, parent, row, platform):
        dot = ctk.CTkFrame(parent, width=8, height=8, corner_radius=4,
                           fg_color=PLATFORM_COLORS[platform])
        dot.grid(row=row, column=0, padx=(0, 8), pady=4)
        dot.grid_propagate(False)

        ctk.CTkLabel(parent, text=platform_label(platform, short=True), font=ui_font(12),
                     anchor="w").grid(row=row, column=1, sticky="w", padx=(0, 18))

        data = self.growth.get(platform) or {}
        if not data.get("collected"):
            text, muted = "не собиралось", True
        elif not data.get("with_delta"):
            text, muted = "первый замер, сравнивать не с чем", True
        else:
            text, muted = self._metrics_text(data), False

        label = ctk.CTkLabel(parent, text=text, font=ui_font(12), anchor="w")
        if muted:
            label.configure(text_color=theme.MUTED_TEXT)
        label.grid(row=row, column=2, sticky="w")

    def _total_row(self, parent, row):
        ctk.CTkLabel(parent, text="Всего", font=ui_font(13, "bold"), anchor="w").grid(
            row=row, column=0, columnspan=2, sticky="w", padx=(0, 18))

        total = self.growth.get("total") or {}
        if not total.get("with_delta"):
            ctk.CTkLabel(parent, text="прироста пока нет", font=ui_font(12),
                         text_color=theme.MUTED_TEXT, anchor="w").grid(
                row=row, column=2, sticky="w")
            return
        ctk.CTkLabel(parent, text=self._metrics_text(total), font=ui_font(13, "bold"),
                     anchor="w").grid(row=row, column=2, sticky="w")

    def _metrics_text(self, data):
        return "   ".join("%s %s" % (icon, format_signed(data.get(key, 0)))
                          for icon, key in METRIC_ICONS)

    def _fit_to_content(self):
        """Подгоняет окно под содержимое.

        Ширину и высоту считает сам Tk по запросам виджетов — мы только следим,
        чтобы окно не оказалось у́же кнопок (иначе они наехали бы друг на друга
        при коротких строках вроде «не собиралось»).
        """
        self.update_idletasks()
        min_by_buttons = OK_WIDTH + BUTTON_GAP + EXPORT_WIDTH + PAD_X * 2
        width = max(self.winfo_reqwidth(), min_by_buttons)
        height = self.winfo_reqheight()
        self.geometry("%dx%d" % (width, height))
        self.minsize(width, height)

    # ---------------------------------------------------------- действия
    def _export(self):
        """То же меню экспорта, что в главном окне, — открывается под кнопкой
        здесь. Один набор пунктов на два окна, рассинхронизироваться нечему."""
        self.master.open_export_menu(self.export_btn)
