# -*- coding: utf-8 -*-
"""Окно «доступна новая версия yt-dlp».

Показывается при запуске, только если найдена версия новее установленной.
Две кнопки: «Пропустить» — работаем на текущей, «Обновить» — ставим новую
и сразу на ней работаем.

Почему перезапуск приложения НЕ нужен: yt-dlp вызывается отдельным процессом
(`sys.executable -m yt_dlp`), а не импортируется внутрь приложения. Значит
следующий же сбор возьмёт уже обновлённую версию — перезапускаться не за чем.
Это прямое следствие того, как устроен backend_tiktok.py.

Само обновление идёт в фоновом потоке: pip качает пакет из сети, и в главном
потоке это подвесило бы окно на несколько секунд.
"""
import threading

import customtkinter as ctk

import backend_tiktok
import diagnostics
from app_state import APP_NAME
from fonts import ui_font
import theme
from ui_utils import fade_in


class UpdateWindow(ctk.CTkToplevel):
    def __init__(self, master, installed, latest, on_updated=None):
        super().__init__(master)
        self.installed = installed
        self.latest = latest
        self.on_updated = on_updated      # колбэк: обновить подпись версии в шапке
        self.result_queue = []

        self.title(APP_NAME)
        self.geometry("440x300")
        self.resizable(False, False)
        self.grab_set()                   # модальное поведение поверх главного окна

        self._build()
        fade_in(self)

    # ---------------------------------------------------------- построение UI
    def _build(self):
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.pack(fill="both", expand=True, padx=24, pady=20)

        ctk.CTkLabel(box, text="Доступна новая версия yt-dlp",
                     font=ui_font(15, "bold")).pack(anchor="w")
        ctk.CTkLabel(
            box, text="yt-dlp — это движок, которым собирается TikTok.",
            font=ui_font(12), text_color=theme.MUTED_TEXT,
        ).pack(anchor="w", pady=(2, 12))

        versions = ctk.CTkFrame(box, fg_color="transparent")
        versions.pack(fill="x")
        self._version_row(versions, "Сейчас установлена:", self.installed)
        self._version_row(versions, "Доступна:", self.latest, accent=True)

        ctk.CTkLabel(
            box,
            text=("Обновление не потребует перезапуска: сбор запускает yt-dlp\n"
                  "отдельно, поэтому новая версия заработает сразу."),
            font=ui_font(11), text_color=theme.MUTED_TEXT, justify="left",
        ).pack(anchor="w", pady=(12, 0))

        self.status_label = ctk.CTkLabel(box, text="", font=ui_font(11),
                                         text_color=theme.MUTED_TEXT, justify="left")
        self.status_label.pack(anchor="w", pady=(8, 0))

        buttons = ctk.CTkFrame(box, fg_color="transparent")
        buttons.pack(side="bottom", fill="x", pady=(12, 0))
        self.skip_btn = ctk.CTkButton(
            buttons, text="Пропустить", corner_radius=12, fg_color=theme.NEUTRAL_FG,
            text_color=theme.NEUTRAL_TEXT, hover_color=theme.NEUTRAL_FG_HOVER,
            command=self._skip,
        )
        self.skip_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
        self.update_btn = ctk.CTkButton(
            buttons, text="Обновить", corner_radius=12, command=self._update,
        )
        self.update_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))

    def _version_row(self, parent, caption, version, accent=False):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=1)
        ctk.CTkLabel(row, text=caption, font=ui_font(12),
                     text_color=theme.MUTED_TEXT, width=150, anchor="w").pack(side="left")
        date = backend_tiktok.version_date(version)
        text = "%s%s" % (version or "—", "  ·  %s" % date if date else "")
        ctk.CTkLabel(row, text=text, font=ui_font(12), anchor="w",
                     text_color=theme.PRIMARY_TEXT if accent else theme.MUTED_TEXT).pack(side="left")

    # ---------------------------------------------------------- действия
    def _skip(self):
        diagnostics.log("INFO", "ytdlp.skip", "Обновление пропущено пользователем",
                        installed=self.installed, latest=self.latest)
        self.destroy()

    def _update(self):
        self.update_btn.configure(state="disabled", text="Обновляю…")
        self.skip_btn.configure(state="disabled")
        self.status_label.configure(text="Скачиваю и устанавливаю, это займёт до минуты…",
                                    text_color=theme.MUTED_TEXT)

        def worker():
            ok, message = backend_tiktok.update()
            self.result_queue.append((ok, message))

        threading.Thread(target=worker, daemon=True).start()
        self.after(300, self._poll_result)

    def _poll_result(self):
        if not self.result_queue:
            self.after(300, self._poll_result)
            return

        ok, message = self.result_queue.pop()
        diagnostics.log("INFO" if ok else "WARNING", "ytdlp.update", message,
                        installed=self.installed, latest=self.latest, success=ok)
        if ok:
            self.status_label.configure(text=message + ". Окно закроется само.",
                                        text_color="#1FA34C")
            if self.on_updated:
                self.on_updated()
            self.after(1600, self.destroy)
        else:
            # Не закрываем окно: пользователь должен увидеть причину и решить,
            # работать ли на старой версии.
            self.status_label.configure(
                text="Не удалось обновить: %s\nМожно продолжить на текущей версии." % message,
                text_color="#A32D2D",
            )
            self.update_btn.configure(state="normal", text="Попробовать снова")
            self.skip_btn.configure(state="normal", text="Продолжить без обновления")
