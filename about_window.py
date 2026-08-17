# -*- coding: utf-8 -*-
"""Окно «О программе» — версии, авторство, использованные библиотеки и риски.

Открывается кликом по названию «EasyGrab» в шапке главного окна.

Здесь же живёт предупреждение о том, что аккаунты для сбора могут быть
заблокированы. Это не мелкий шрифт для галочки: человек должен знать, чем
платит за автоматизацию, до того как это случится, а не после.
"""
import webbrowser

import customtkinter as ctk

import backend_instagram
import backend_tiktok
from app_state import (APP_NAME, APP_STAGE, APP_BUILD_DATE, DEVELOPER_CONTACT,
                       DEVELOPER_URL, DEVELOPER_URL_APP, GITHUB_URL,
                       LIBRARIES_HINT, RISK_HINT, YTDLP_HINT)
from fonts import ui_font
from tooltip import ToolTip
import theme
from ui_utils import fade_in

LINK_COLOR = ("#1F6AA5", "#5AA9E6")


def open_link(url, app_url=None):
    """Открывает ссылку. Если задан адрес для приложения (например, tg://),
    сперва пробует его: у кого установлен Telegram, откроется он, а не браузер.
    """
    if app_url:
        try:
            if webbrowser.open(app_url):
                return
        except Exception:
            pass
    webbrowser.open(url)


class AboutWindow(ctk.CTkToplevel):
    def __init__(self, master, ytdlp_version=None):
        super().__init__(master)
        # Версию yt-dlp главное окно уже знает из фоновой проверки при запуске.
        self.ytdlp_version = ytdlp_version
        if self.ytdlp_version is None:
            ok, version = backend_tiktok.check_available()
            self.ytdlp_version = version if ok else None

        self.title(APP_NAME)
        self.geometry("420x400")
        self.resizable(False, False)
        self.grab_set()

        self._build()
        fade_in(self)

    # ---------------------------------------------------------- построение UI
    def _build(self):
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(fill="both", expand=True, padx=24, pady=(22, 16))

        ctk.CTkLabel(box, text=APP_NAME, font=ui_font(22, "bold")).pack()
        ctk.CTkLabel(box, text="Версия %s  ·  %s" % (APP_STAGE, APP_BUILD_DATE),
                     font=ui_font(12), text_color=theme.MUTED_TEXT).pack(pady=(6, 0))
        self._hint_row(box, self._ytdlp_text(), YTDLP_HINT, pady=(2, 0), size=12)

        # ------------------------------------------------ авторство
        ctk.CTkLabel(box, text="Разработчик", font=ui_font(11),
                     text_color=theme.MUTED_TEXT).pack(pady=(18, 2))
        self._link(box, DEVELOPER_CONTACT, DEVELOPER_URL, DEVELOPER_URL_APP, size=14)
        # Про ИИ отдельной строки нет: это сказано в подсказке к строке
        # «Сторонние библиотеки и ресурсы» ниже, и повторять незачем.
        if GITHUB_URL:
            self._link(box, GITHUB_URL.replace("https://", ""), GITHUB_URL)
        else:
            ctk.CTkLabel(box, text="GitHub — ссылка появится позже", font=ui_font(11),
                         text_color=theme.MUTED_TEXT).pack(pady=(2, 0))

        # ------------------------------------------------ риск блокировки
        self._hint_row(box, "Аккаунты для сбора могут быть заблокированы",
                       RISK_HINT, pady=(18, 0))

        # ------------------------------------------------ библиотеки
        # Раньше здесь был прокручиваемый список на пол-окна. Он нужен раз
        # в жизни, а место занимал всегда — убран в подсказку, как и риск.
        self._hint_row(box, "Сторонние библиотеки и ресурсы", LIBRARIES_HINT, pady=(10, 0))

        ctk.CTkButton(
            box, text="Закрыть", corner_radius=12, width=120, fg_color=theme.NEUTRAL_FG,
            text_color=theme.NEUTRAL_TEXT, hover_color=theme.NEUTRAL_FG_HOVER,
            command=self.destroy,
        ).pack(side="bottom", pady=(14, 0))

    def _hint_row(self, parent, text, hint, pady=(0, 0), size=11):
        """Строка с значком ⓘ и подсказкой — общий вид для всех таких строк."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(pady=pady)
        ctk.CTkLabel(row, text=text, font=ui_font(size),
                     text_color=theme.MUTED_TEXT).pack(side="left")
        info = ctk.CTkLabel(row, text=" ⓘ", font=ui_font(12),
                            text_color=theme.MUTED_TEXT, cursor="hand2")
        info.pack(side="left")
        ToolTip(info, hint, wraplength=380)
        return row

    def _link(self, parent, text, url, app_url=None, size=11):
        label = ctk.CTkLabel(parent, text=text, font=ui_font(size),
                             text_color=LINK_COLOR, cursor="hand2")
        label.pack(pady=(2, 0))
        label.bind("<Button-1>", lambda _e: open_link(url, app_url))
        return label

    def _ytdlp_text(self):
        """Только номер версии, без даты.

        Раньше здесь было «yt-dlp 2026.07.04 · 04.07.2026» — одна и та же дата
        дважды: у yt-dlp номер версии И ЕСТЬ дата сборки. Что это значит,
        объясняет подсказка ⓘ рядом.
        """
        if not self.ytdlp_version:
            return "yt-dlp не установлен"
        return "yt-dlp %s" % self.ytdlp_version
