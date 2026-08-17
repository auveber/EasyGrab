# -*- coding: utf-8 -*-
"""Окно входа EasyGrab — три вкладки (YouTube/Instagram/TikTok).

Логика, зафиксированная в макетах:
  * Переключение вкладок не стирает уже введённое — значения хранятся
    в self.draft на время жизни этого окна.
  * У активной вкладки насыщенный цвет платформы и белый текст,
    у неактивных — нейтральный серый (адаптируется под тёмную/светлую тему).
  * Блок с полями имеет фиксированную высоту (под самый "длинный" таб —
    Instagram/TikTok с двумя полями), чтобы окно не "прыгало" при клике
    между вкладками, а содержимое стоит чуть выше геометрического центра
    между вкладками и текстом "Запомнить на этом устройстве".
  * Вкладки — фиксированной ширины (не "резиновые"), чтобы системный шрифт
    разной ширины на Windows/macOS/Linux не сжимал последнюю вкладку до
    нечитаемого вида — раньше здесь был именно такой баг.
"""
import threading

import customtkinter as ctk

import backend_instagram
from app_state import (state, PLATFORMS, PLATFORM_LABELS, PLATFORM_COLORS, APP_NAME,
                       APP_STAGE, NO_LOGIN_PLATFORMS, IG_STABILITY_HINT,
                       EXPERIMENTAL_PLATFORMS, platform_label)
from tooltip import ToolTip
from fonts import ui_font
import theme
from ui_utils import fade_in

WINDOW_WIDTH = 420
FIELDS_AREA_PADDING = 24  # воздух вокруг полей внутри отведённой им области
TAB_WIDTH = 100
# У Instagram в названии есть пометка «(exp.)» — вкладке нужно больше места.
TAB_WIDTH_EXPERIMENTAL = 138

TOOLTIP_TEXT = {
    "youtube": (
        "Нужен, чтобы бесплатно и легально получать статистику каналов. "
        "Берётся в Google Cloud Console -> включить «YouTube Data API v3» "
        "-> Credentials -> Create API key. Вход в личный Google-аккаунт не нужен."
    ),
    "instagram": (
        "Instagram — единственная из трёх площадок, которую нельзя собирать без "
        "входа: без него он отдаёт 429 на первом же запросе.\n\n"
        "Нужен отдельный аккаунт-бёрнер — заведённый только для просмотра "
        "и не входящий в ваши рабочие.\n\n"
        "Пароль спрашивается ОДИН раз: после входа сохраняется сессия вместе "
        "с отпечатком устройства, и дальше пароль не нужен. На диск он "
        "не записывается ни при каких условиях.\n\n"
        "Полный вход открывает вкладку Reels пачкой — один запрос на профиль "
        "вместо одного на каждый ролик. Сбор идёт минуты вместо десятков минут."
    ),
    "tiktok": (
        "Аккаунт-бёрнер — это одноразовый аккаунт, заведённый только для просмотра "
        "и никак не связанный с рабочими.\n\n"
        "Зачем разделять. Антифрод соцсетей связывает аккаунты по общим признакам: "
        "устройству, IP и, что важнее всего, по тому, кто на кого заходит. Если один "
        "аккаунт каждый день просматривает ровно ваши рабочие профили, он сам "
        "становится ниточкой, по которой их связывают между собой. Итог — теневой бан "
        "сразу по всей группе.\n\n"
        "Здесь этот риск снят целиком: TikTok собирается вообще без входа, связывать "
        "нечего. Если TikTok когда-нибудь начнёт требовать проверку, понадобится файл "
        "cookies — и это тоже будет отдельный бёрнер, а не один из ваших двадцати."
    ),
}


class LoginWindow(ctk.CTkToplevel):
    def __init__(self, master, initial_platform="youtube", on_saved=None):
        super().__init__(master)
        self.on_saved = on_saved
        self.title(APP_NAME)
        self.resizable(False, False)
        self.grab_set()  # модальное поведение поверх главного окна

        # Черновик значений по всем трём вкладкам — не теряется при переключении.
        self.draft = {p: dict(state.credentials.get(p, {})) for p in PLATFORMS}
        self.current = initial_platform if initial_platform in PLATFORMS else "youtube"

        self._build()
        self._select_tab(self.current)
        self._fit_to_content()
        fade_in(self)

    # ---------------------------------------------------------- построение UI
    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(20, 4))
        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(anchor="w")
        ctk.CTkLabel(title_row, text=APP_NAME, font=ui_font(16, "bold")).pack(side="left")
        ctk.CTkLabel(
            title_row, text="  " + APP_STAGE, font=ui_font(11), text_color=theme.MUTED_TEXT
        ).pack(side="left")
        ctk.CTkLabel(
            header, text="Выбери соц. сеть", font=ui_font(12), text_color=theme.MUTED_TEXT
        ).pack(anchor="w", pady=(2, 0))

        tabs_row = ctk.CTkFrame(self, fg_color="transparent")
        tabs_row.pack(pady=(12, 4))  # без fill="x" — вкладки центрируются своей суммарной шириной
        self.tab_buttons = {}
        for p in PLATFORMS:
            btn = ctk.CTkButton(
                tabs_row, text=platform_label(p, short=True), corner_radius=12,
                width=TAB_WIDTH_EXPERIMENTAL if p in EXPERIMENTAL_PLATFORMS else TAB_WIDTH,
                fg_color=theme.NEUTRAL_FG, text_color=theme.NEUTRAL_TEXT, hover_color=theme.NEUTRAL_FG_HOVER,
                command=lambda p=p: self._select_tab(p),
            )
            btn.pack(side="left", padx=4)
            self.tab_buttons[p] = btn

        # ПОРЯДОК УПАКОВКИ ВАЖЕН. Кнопку и галочку пакуем ПЕРВЫМИ и прижимаем
        # к низу: у Tk каждый следующий виджет получает место из того, что
        # осталось. Раньше они шли последними, и когда область полей выросла
        # до 200px, кнопке «Сохранить» места не хватило — её срезало нижним
        # краем окна. Теперь она получает своё место первой и видна всегда,
        # какой бы высокой ни стала вкладка.
        self.save_btn = ctk.CTkButton(
            self, text="Сохранить и продолжить", corner_radius=12, command=self._save,
        )
        self.save_btn.pack(side="bottom", fill="x", padx=24, pady=(0, 20))

        self.remember_var = ctk.BooleanVar(value=state.remember_on_device)
        ctk.CTkCheckBox(
            self, text="Запомнить на этом устройстве", variable=self.remember_var,
        ).pack(side="bottom", anchor="w", padx=24, pady=(6, 10))

        # Область под поля занимает то, что осталось между вкладками и кнопкой.
        self.fields_area = ctk.CTkFrame(self, fg_color="transparent")
        self.fields_area.pack(fill="both", expand=True, padx=24, pady=(4, 4))
        self.fields_area.pack_propagate(False)

        self.field_frames = {
            "youtube": self._build_youtube_fields(self.fields_area),
            "tiktok": self._build_info_fields(self.fields_area, "tiktok"),
            "instagram": self._build_instagram_fields(self.fields_area, "instagram"),
        }

    def _fit_to_content(self):
        """Подгоняет окно под самую высокую вкладку.

        Размер не задан числом: меряем каждую вкладку и берём максимум, плюс
        обвязку. Иначе при правке любой вкладки надо было бы не забыть
        поправить и высоту окна — а забыть легко, что один раз и случилось.
        """
        self.update_idletasks()
        tallest = max((f.winfo_reqheight() for f in self.field_frames.values()), default=0)
        chrome = self.winfo_reqheight() - self.fields_area.winfo_height()
        height = chrome + tallest + FIELDS_AREA_PADDING
        width = max(WINDOW_WIDTH, self.winfo_reqwidth())
        self.geometry("%dx%d" % (width, height))
        self.minsize(width, height)

    def _label_with_tip(self, parent, text, platform):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(row, text=text, font=ui_font(12), text_color=theme.MUTED_TEXT).pack(side="left")
        info = ctk.CTkLabel(row, text=" \u24d8", font=ui_font(12), text_color=theme.MUTED_TEXT, cursor="hand2")
        info.pack(side="left")
        ToolTip(info, TOOLTIP_TEXT[platform])
        return row

    def _build_youtube_fields(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._label_with_tip(frame, "API-ключ", "youtube")
        entry = ctk.CTkEntry(frame, placeholder_text="AIzaSy...", width=320)
        entry.pack(fill="x")
        if self.draft["youtube"].get("key"):
            entry.insert(0, self.draft["youtube"]["key"])
        frame.entries = {"key": entry}
        return frame

    def _build_instagram_fields(self, parent, platform):
        """Вкладка Instagram: логин и пароль бёрнера + запасной путь через браузер.

        Пароль здесь нужен по делу, а не по привычке: только полноценный вход
        ставит отпечаток устройства, а без него вкладка Reels отвечает
        login_required — и просмотры пришлось бы добирать по одному ролику,
        то есть в девять раз большим числом запросов.

        Сам пароль нигде не сохраняется: он уходит на вход и забывается,
        на диск ложится только сессия.
        """
        frame = ctk.CTkFrame(parent, fg_color="transparent")

        self._label_with_tip(frame, "Логин аккаунта-бёрнера", platform)
        user_entry = ctk.CTkEntry(frame, placeholder_text="username", width=320)
        user_entry.pack(fill="x", pady=(0, 6))
        pass_entry = ctk.CTkEntry(frame, placeholder_text="пароль (нужен один раз)",
                                  width=320, show="*")
        pass_entry.pack(fill="x")
        if self.draft[platform].get("user"):
            user_entry.insert(0, self.draft[platform]["user"])

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", pady=(8, 0))
        self.ig_login_btn = ctk.CTkButton(row, text="Войти", corner_radius=12, width=110,
                                          command=self._instagram_login)
        self.ig_login_btn.pack(side="left")
        self.browser_var = ctk.StringVar(
            value=backend_instagram.BROWSER_LABELS.get(
                self.draft[platform].get("browser", "chrome"), "Chrome"))
        ctk.CTkOptionMenu(row, values=[l for _k, l in backend_instagram.BROWSERS],
                          variable=self.browser_var, width=104).pack(side="left", padx=(8, 4))
        self.browser_btn = ctk.CTkButton(
            row, text="Из браузера", corner_radius=12, width=104,
            fg_color=theme.NEUTRAL_FG, text_color=theme.NEUTRAL_TEXT,
            hover_color=theme.NEUTRAL_FG_HOVER, command=self._import_browser_session,
        )
        self.browser_btn.pack(side="left")

        current = self.draft[platform].get("user")
        self.browser_status = ctk.CTkLabel(
            frame, text=("Вошли как @%s" % current) if current else "",
            font=ui_font(11), justify="left", wraplength=330,
            text_color="#1FA34C" if current else theme.MUTED_TEXT,
        )
        self.browser_status.pack(anchor="w", pady=(6, 0))

        # Предупреждение о нестабильности — видимой строкой, а не только
        # в подсказке: человек должен знать это до первого сбора.
        warn = ctk.CTkFrame(frame, fg_color="transparent")
        warn.pack(anchor="w", pady=(6, 0))
        ctk.CTkLabel(warn, text="Сбор Instagram нестабилен", font=ui_font(11),
                     text_color="#BA7517").pack(side="left")
        tip = ctk.CTkLabel(warn, text=" \u24d8", font=ui_font(11),
                           text_color="#BA7517", cursor="hand2")
        tip.pack(side="left")
        ToolTip(tip, IG_STABILITY_HINT, wraplength=380)

        frame.entries = {"user": user_entry, "pass": pass_entry}
        return frame

    def _instagram_login(self):
        """Полный вход по паролю — в фоне: сеть, занимает несколько секунд."""
        user = self.field_frames["instagram"].entries["user"].get().strip()
        password = self.field_frames["instagram"].entries["pass"].get()
        self.ig_login_btn.configure(state="disabled", text="Вхожу…")
        self.browser_status.configure(text="Выполняю вход…", text_color=theme.MUTED_TEXT)
        result = []

        def worker():
            result.append(backend_instagram.login_with_password(user, password))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if not self.winfo_exists():
                return
            if not result:
                self.after(200, poll)
                return
            ok, message = result[0]
            self.ig_login_btn.configure(state="normal", text="Войти")
            if ok:
                # Пароль дальше не нужен и нигде не остаётся.
                self.field_frames["instagram"].entries["pass"].delete(0, "end")
                self.draft["instagram"] = {"user": message}
                self.browser_status.configure(text="Вошли как @%s — пароль больше "
                                                   "не понадобится" % message,
                                              text_color="#1FA34C")
            else:
                self.browser_status.configure(text=message, text_color="#A32D2D")

        self.after(200, poll)

    def _import_browser_session(self):
        """Забирает сессию из выбранного браузера. Идёт в фоне: чтение файлов
        браузера и проверка входа занимают пару секунд, и окно бы подвисло."""
        browser_key = backend_instagram.BROWSER_KEYS.get(self.browser_var.get(), "safari")
        self.browser_btn.configure(state="disabled", text="Читаю…")
        self.browser_status.configure(text="Читаю сессию из %s…" % self.browser_var.get(),
                                      text_color=theme.MUTED_TEXT)
        result = []

        def worker():
            result.append(backend_instagram.import_browser_session(browser_key))

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            if not self.winfo_exists():
                return
            if not result:
                self.after(200, poll)
                return
            ok, message = result[0]
            self.browser_btn.configure(state="normal", text="Взять сессию")
            if ok:
                self.draft["instagram"] = {"user": message, "browser": browser_key}
                self.browser_status.configure(text="Вошли как @%s" % message,
                                              text_color="#1FA34C")
            else:
                self.browser_status.configure(text=message, text_color="#A32D2D")

        self.after(200, poll)

    def _build_info_fields(self, parent, platform):
        """Вкладка без полей ввода — для площадок, которым вход не нужен.

        У TikTok полей нет не для красоты: yt-dlp, которым он собирается,
        физически не умеет входить по логину и паролю (в его экстракторе
        TikTok нет ни одного упоминания username/password — только cookies).
        Поле, которое ни на что не влияет, хуже, чем честное объяснение.
        """
        frame = ctk.CTkFrame(parent, fg_color="transparent")

        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(anchor="w")
        ctk.CTkLabel(row, text="Вход не требуется", font=ui_font(13, "bold")).pack(side="left")
        info = ctk.CTkLabel(row, text=" \u24d8", font=ui_font(13),
                            text_color=theme.MUTED_TEXT, cursor="hand2")
        info.pack(side="left")
        ToolTip(info, TOOLTIP_TEXT[platform], wraplength=330)

        ctk.CTkLabel(
            frame,
            text=("%s собирается анонимно: приложение читает публичные\n"
                  "профили и не заходит ни в один аккаунт.\n\n"
                  "Так безопаснее для ваших рабочих аккаунтов — наведите\n"
                  "на значок \u24d8, там объяснение про антифрод." % PLATFORM_LABELS[platform]),
            font=ui_font(12), text_color=theme.MUTED_TEXT, justify="left",
        ).pack(anchor="w", pady=(8, 0))

        frame.entries = {}      # полей нет — _stash_current это учитывает
        return frame

    def _build_login_pass_fields(self, parent, platform):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        self._label_with_tip(frame, "Логин вьюер-аккаунта", platform)
        user_entry = ctk.CTkEntry(frame, placeholder_text="username", width=320)
        user_entry.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(frame, text="Пароль", font=ui_font(12), text_color=theme.MUTED_TEXT).pack(anchor="w", pady=(0, 4))
        pass_entry = ctk.CTkEntry(frame, placeholder_text="********", width=320, show="*")
        pass_entry.pack(fill="x")
        if self.draft[platform].get("user"):
            user_entry.insert(0, self.draft[platform]["user"])
        if self.draft[platform].get("pass"):
            pass_entry.insert(0, self.draft[platform]["pass"])
        frame.entries = {"user": user_entry, "pass": pass_entry}
        return frame

    # ---------------------------------------------------------- переключение вкладок
    def _stash_current(self):
        """Сохраняет то, что видно на экране прямо сейчас, в self.draft."""
        frame = self.field_frames[self.current]
        if not frame.entries:          # вкладка без полей (вход не требуется)
            return
        if self.current == "youtube":
            self.draft["youtube"]["key"] = frame.entries["key"].get()
        elif self.current == "instagram":
            # Пароль в черновик не кладём: он нужен только на момент входа
            # и не должен попасть ни в состояние приложения, ни в session.json.
            self.draft["instagram"]["user"] = frame.entries["user"].get()
        else:
            self.draft[self.current]["user"] = frame.entries["user"].get()
            self.draft[self.current]["pass"] = frame.entries["pass"].get()

    def _select_tab(self, platform):
        if hasattr(self, "field_frames"):
            self._stash_current()
            for f in self.field_frames.values():
                f.pack_forget()

        self.current = platform
        for p, btn in self.tab_buttons.items():
            if p == platform:
                btn.configure(fg_color=PLATFORM_COLORS[p], text_color="white", hover_color=PLATFORM_COLORS[p])
            else:
                btn.configure(fg_color=theme.NEUTRAL_FG, text_color=theme.NEUTRAL_TEXT, hover_color=theme.NEUTRAL_FG_HOVER)

        # pack(expand=True) центрирует блок по вертикали внутри фиксированной области
        # независимо от того, сколько в нём полей (1 у YouTube, 2 у Instagram/TikTok) —
        # раньше здесь было place() с процентным смещением, которое при двух полях
        # физически вылезало за пределы области и наезжало на чекбокс/кнопку ниже.
        # Небольшой нижний отступ (pady) визуально сдвигает центр чуть выше середины.
        self.field_frames[platform].pack(in_=self.fields_area, expand=True, pady=(0, 10))

    # ---------------------------------------------------------- сохранение
    def _save(self):
        self._stash_current()
        remember = self.remember_var.get()
        for p in PLATFORMS:
            if p in NO_LOGIN_PLATFORMS:
                filled = True          # площадка готова к сбору без всякого входа
            elif p == "youtube":
                filled = bool(self.draft["youtube"].get("key", "").strip())
            elif p == "instagram":
                # Пароля нет вовсе: подключён — значит сессия из браузера взята.
                filled = bool(self.draft["instagram"].get("user"))
            else:
                filled = bool(self.draft[p].get("user", "").strip()) and bool(self.draft[p].get("pass", "").strip())
            state.set_login(p, filled, data=self.draft[p], remember=remember)
        if self.on_saved:
            self.on_saved()
        self.destroy()
