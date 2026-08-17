# -*- coding: utf-8 -*-
"""Окно-предупреждение перед сбором с экспериментальной площадки.

Всплывает, когда в сборе участвует Instagram. Задача — дать принять решение
осознанно, а не отговорить: сбор там правда нестабилен, и человек должен
знать это заранее, а не когда половина строк вернёт ошибку.

Галочка «больше не спрашивать» уважает выбор: если человек прочитал и понял,
показывать то же самое каждый день — неуважение к его времени.
"""
import customtkinter as ctk

from app_state import APP_NAME
from fonts import ui_font
import theme
from ui_utils import fade_in

PAD_X = 24
PAD_Y = 20
CANCEL_WIDTH = 104
CONFIRM_WIDTH = 150
BUTTON_GAP = 20


class ConfirmWindow(ctk.CTkToplevel):
    def __init__(self, master, title, text, confirm_text="Собрать всё равно",
                 on_confirm=None, on_dont_ask=None):
        super().__init__(master)
        self.on_confirm = on_confirm
        self.on_dont_ask = on_dont_ask
        self._heading = title
        self._text = text
        self._confirm_text = confirm_text

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

        # Кнопки пакуем первыми и прижимаем к низу — тогда при любом объёме
        # текста они остаются на месте и не срезаются краем окна.
        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.pack(side="bottom", fill="x", pady=(18, 0))
        ctk.CTkButton(
            buttons, text="Отмена", corner_radius=12, width=CANCEL_WIDTH,
            fg_color=theme.NEUTRAL_FG, text_color=theme.NEUTRAL_TEXT,
            hover_color=theme.NEUTRAL_FG_HOVER, command=self.destroy,
        ).pack(side="left")
        ctk.CTkButton(
            buttons, text=self._confirm_text, corner_radius=12, width=CONFIRM_WIDTH,
            command=self._confirm,
        ).pack(side="right", padx=(BUTTON_GAP, 0))

        self.dont_ask_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            box, text="Больше не спрашивать", variable=self.dont_ask_var,
            font=ui_font(11),
        ).pack(side="bottom", anchor="w", pady=(14, 0))

        ctk.CTkLabel(box, text=self._heading, font=ui_font(15, "bold"),
                     justify="left", anchor="w").pack(anchor="w")
        ctk.CTkLabel(box, text=self._text, font=ui_font(12), justify="left",
                     anchor="w", wraplength=400, text_color=theme.MUTED_TEXT
                     ).pack(anchor="w", pady=(10, 0))

    def _fit_to_content(self):
        self.update_idletasks()
        min_by_buttons = CANCEL_WIDTH + BUTTON_GAP + CONFIRM_WIDTH + PAD_X * 2
        width = max(self.winfo_reqwidth(), min_by_buttons)
        height = self.winfo_reqheight()
        self.geometry("%dx%d" % (width, height))
        self.minsize(width, height)

    # ---------------------------------------------------------- действия
    def _confirm(self):
        if self.dont_ask_var.get() and self.on_dont_ask:
            self.on_dont_ask()
        self.destroy()
        if self.on_confirm:
            self.on_confirm()
