# -*- coding: utf-8 -*-
"""Главное окно EasyGrab.

Собирает воедино всё, что зафиксировано в макетах:
  * статус-бар из трёх кружков — первый элемент общего ряда с кнопками;
  * "Собрать метрики" (акцент), "Экспорт", пустое пространство, "Аккаунты" у края;
  * переключатель тёмной/светлой темы (по умолчанию тёмная);
  * таблица сгруппирована по аккаунту (одна строка = один блогер, три
    колонки-платформы), с постраничной навигацией и статусами
    "нет входа" / часы (в процессе) / галочка+число / крестик (ошибка);
  * обновление статуса — построчно и вживую по мере готовности данных,
    не одним пакетом в конце.

Колонки таблицы выровнены через grid с общим "uniform"-тегом — это гарантирует,
что заголовки и ячейки совпадают по ширине независимо от шрифта конкретной ОС
(на Windows/macOS/Linux системные шрифты имеют разную метрику, из-за которой
раньше "плыли" фиксированные пиксельные ширины).

ПРИМЕЧАНИЕ ПРО ИКОНКИ ПЛАТФОРМ: в веб-макетах использовались иконки
из шрифта Tabler — в нативном Tkinter такого шрифта нет из коробки,
поэтому здесь стоят текстовые сокращения "YT"/"IG"/"TT". Заменить на
CTkImage с PNG-иконками можно позже без переделки остальной логики.
"""
import datetime
import queue
import threading
import time
from tkinter import filedialog, Menu

import customtkinter as ctk

import backend_tiktok
import diagnostics
import history
from app_state import (state, PLATFORMS, PLATFORM_LABELS, PLATFORM_COLORS,
                       SCOPE_PRESETS, SCOPE_LABELS, SCOPE_KEYS, SCOPE_HINT,
                       NO_LOGIN_PLATFORMS, EXPERIMENTAL_PLATFORMS, platform_label,
                       IG_CONFIRM_TITLE, IG_CONFIRM_TEXT)
from about_window import AboutWindow
from confirm_window import ConfirmWindow
from summary_window import SummaryWindow
from update_window import UpdateWindow
from login_window import LoginWindow
from accounts_window import AccountsWindow
from mock_backend import simulate_collect
import exporters
from fonts import ui_font, mono_font
from tooltip import ToolTip
from ui_utils import animate_color, fit_window_height, flash_text_color
import theme

PAGE_SIZES = (5, 10, 20, 50)
PLATFORM_SHORT = {"youtube": "YT", "instagram": "IG", "tiktok": "TT"}
COLUMN_UNIFORM = "easygrab_cols"
# Аккаунт / YouTube / Instagram / TikTok.
# Было (3,1,1,1): под имя уходило 331-464px при реальной ширине текста 63px,
# а колонке площадки оставалось 110-154px — метрики не влезали в строку и
# приходилось ставить их столбцом. Замерено, не подобрано на глаз.
COLUMN_WEIGHTS = (2, 3, 3, 3)


def format_compact(n):
    """1234 -> '1.2K', 128463 -> '128.5K', 3400000 -> '3.4M'. Мелкие числа — как есть."""
    if n is None:
        return "—"
    if n >= 1_000_000:
        value, suffix = n / 1_000_000, "M"
    elif n >= 1_000:
        value, suffix = n / 1_000, "K"
        if round(value, 1) >= 1000:  # напр. 999 950 -> 1000.0K, переводим в M
            value, suffix = n / 1_000_000, "M"
    else:
        return str(n)
    s = ("%.1f" % value).rstrip("0").rstrip(".")
    return s + suffix


def plural_views(n):
    """Правильное склонение: 1 просмотр, 3 просмотра, 5 просмотров."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return "просмотров"
    return {1: "просмотр", 2: "просмотра", 3: "просмотра", 4: "просмотра"}.get(n % 10, "просмотров")


def format_delta(d):
    """Прирост в компактном виде: 239 -> " +239", -12 -> " -12", 0/None -> "".

    Ноль намеренно не показываем — иначе таблица зарябит "+0" у полутора
    десятков аккаунтов, которые за сутки не сдвинулись.
    """
    if not d:
        return ""
    return " %s%s" % ("+" if d > 0 else "-", format_compact(abs(d)))


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("EasyGrab")
        self.geometry("900x600")
        # 720, а не 700: при 700 «Аккаунты» и «Экспорт» смыкаются вплотную,
        # без просвета между ними. Замерено, не на глаз.
        self.minsize(720, 480)
        self.resizable(True, True)

        # results[account_name][platform] = {"status": "none"/"pending"/"done"/"error",
        #                                     "views":.., "likes":.., "comments":..}
        self.results = {}
        self._rebuild_results_skeleton()

        self.page_size = 10
        self.page = 1
        self.visible_cells = {}  # account_name -> {platform: label_widget}, только для текущей страницы

        self.queue = queue.Queue()
        self.collecting = False
        self.stop_flag = False  # взводится кнопкой «Стоп», читается фоновым потоком
        self.ytdlp_version = None   # узнаётся фоновой проверкой при запуске
        self.progress_done = 0      # сколько запросов уже отработало
        self.progress_total = 0     # сколько всего предстоит
        # Точка отсчёта для прироста — заполняется при запуске сбора.
        self.baseline, self.baseline_label = None, ""

        self._build()
        self._refresh_status_dots()
        self._render_table()
        # Высоту подгоняем после первой отрисовки: до неё виджеты ещё
        # не знают своих размеров, и считать было бы не по чему.
        self.after_idle(self._fit_height)
        self.after(150, self._poll_queue)
        self._check_ytdlp_version()

    # ---------------------------------------------------------- построение UI
    def _configure_columns(self, frame):
        """Общая настройка колонок — тот же uniform-тег синхронизирует ширины
        между заголовком и каждой строкой таблицы, даже если это разные фреймы."""
        for i, w in enumerate(COLUMN_WEIGHTS):
            frame.grid_columnconfigure(i, weight=w, uniform=COLUMN_UNIFORM)

    def _build(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 6))

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", anchor="w")
        top_row = ctk.CTkFrame(title_box, fg_color="transparent")
        top_row.pack(anchor="w")
        # Версии и авторство переехали в окно «О программе»: нужны они редко,
        # а место в шапке занимали постоянно. Открывается кликом по названию.
        title = ctk.CTkLabel(top_row, text="EasyGrab", font=ui_font(18, "bold"), cursor="hand2")
        title.pack(side="left")
        title.bind("<Button-1>", lambda _e: self._open_about())
        ToolTip(title, "Нажмите, чтобы посмотреть версию приложения,\nверсию yt-dlp и разработчика")

        self.last_collect_label = ctk.CTkLabel(
            title_box, text="Последний сбор: ещё не запускался", font=ui_font(12), text_color=theme.MUTED_TEXT
        )
        self.last_collect_label.pack(anchor="w", pady=(2, 0))

        self.theme_btn = ctk.CTkButton(
            header, text=self._theme_btn_text(), corner_radius=12, width=120,
            fg_color=theme.NEUTRAL_FG, text_color=theme.NEUTRAL_TEXT, hover_color=theme.NEUTRAL_FG_HOVER,
            command=self._toggle_theme,
        )
        self.theme_btn.pack(side="right", anchor="ne")

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=(0, 10))

        # ПОРЯДОК УПАКОВКИ ВАЖЕН. Прижатую вправо кнопку пакуем ПЕРВОЙ:
        # у Tk каждый следующий виджет получает место из того, что осталось,
        # поэтому раньше распорка с expand=True успевала забрать всю ширину,
        # а кнопке "Аккаунты" доставалось 30px и её уносило за правый край
        # окна (при ширине 709px она была на x=750 — то есть не видна вообще).
        # Распорка теперь не нужна совсем: side="left" и side="right"
        # расходятся к своим краям сами, а пустота остаётся посередине.
        self.export_btn = ctk.CTkButton(
            toolbar, text="Экспорт \u25be", corner_radius=12, width=104, fg_color=theme.NEUTRAL_FG,
            text_color=theme.NEUTRAL_TEXT, hover_color=theme.NEUTRAL_FG_HOVER, command=self._export,
        )
        self.export_btn.pack(side="right")

        dots_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        dots_frame.pack(side="left")
        self.status_dots = {}
        for p in PLATFORMS:
            dot = ctk.CTkButton(
                dots_frame, text=PLATFORM_SHORT[p], width=34, height=34, corner_radius=17,
                fg_color=theme.NEUTRAL_FG, text_color=theme.NEUTRAL_TEXT, hover_color=theme.NEUTRAL_FG_HOVER,
                command=lambda p=p: self._open_login(p),
            )
            # Отступ только справа: левый край первого кружка должен совпадать
            # с левым краем таблицы, иначе поля окна выглядят разными.
            dot.pack(side="left", padx=(0, 6))
            self.status_dots[p] = dot

        self.collect_btn = ctk.CTkButton(
            toolbar, text="Собрать метрики", corner_radius=12, width=142,
            command=self._start_collect,
        )
        self.collect_btn.pack(side="left", padx=(6, 6))
        # Родной акцентный цвет темы — чтобы после «Стоп» вернуть именно его,
        # а не вписывать синий вручную (он разный в светлой и тёмной теме).
        self._collect_btn_color = self.collect_btn.cget("fg_color")
        self._collect_btn_hover = self.collect_btn.cget("hover_color")
        self._accent_text_color = self.collect_btn.cget("text_color")
        self._export_active = False
        self._refresh_export_button()

        # Охват сбора — сразу за кнопкой сбора, потому что относится именно
        # к ней, а не к отображению таблицы.
        self.scope_var = ctk.StringVar(value=SCOPE_LABELS.get(state.collect_scope, "Вся история"))
        self.scope_menu = ctk.CTkOptionMenu(
            toolbar, values=[label for _key, label in SCOPE_PRESETS], variable=self.scope_var,
            width=116, command=self._change_scope,
        )
        self.scope_menu.pack(side="left", padx=(0, 6))
        ToolTip(self.scope_menu, SCOPE_HINT)

        # Тонкая полоса хода сбора. Она НЕ появляется и не исчезает: место под
        # неё занято всегда, иначе при старте сбора таблица дёргалась бы вниз.
        # В покое это просто разделительная линия под панелью кнопок.
        self.progress = ctk.CTkProgressBar(self, height=4, corner_radius=2,
                                           fg_color=theme.NEUTRAL_FG)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=20, pady=(0, 8))

        col_header = ctk.CTkFrame(self, fg_color="transparent")
        col_header.pack(fill="x", padx=20)
        self._configure_columns(col_header)
        ctk.CTkLabel(col_header, text="Аккаунт", font=ui_font(11), text_color=theme.MUTED_TEXT, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=4
        )
        for i, p in enumerate(PLATFORMS, start=1):
            ctk.CTkLabel(col_header, text=platform_label(p, short=True), font=ui_font(11),
                        text_color=theme.MUTED_TEXT,
                        anchor="center").grid(row=0, column=i, sticky="ew", padx=4)

        self.table_area = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.table_area.pack(fill="both", expand=True, padx=20, pady=(4, 8))
        # Предохранитель: у самых крупных каналов строка метрик с приростом
        # («\U0001F441 168.7K +5.8K  \u2764 2.2K +12  \U0001F4AC 11 +2» — 242px) может не влезть
        # в узкое окно. Тогда пусть переносится на вторую строку, а не
        # обрезается — потерять цифру хуже, чем занять лишние 20px.
        self.table_area.bind("<Configure>", self._update_cell_wrap)

        pager = ctk.CTkFrame(self, fg_color="transparent")
        pager.pack(fill="x", padx=20, pady=(0, 8))

        # Навигация по страницам пакуется первой — см. комментарий про порядок
        # упаковки в панели кнопок выше.
        nav = ctk.CTkFrame(pager, fg_color="transparent")
        nav.pack(side="right")

        ctk.CTkLabel(pager, text="Показывать по", font=ui_font(11), text_color=theme.MUTED_TEXT).pack(side="left")
        self.page_size_var = ctk.StringVar(value=str(self.page_size))
        ctk.CTkOptionMenu(
            pager, values=[str(s) for s in PAGE_SIZES], variable=self.page_size_var,
            width=70, command=self._change_page_size,
        ).pack(side="left", padx=(6, 0))

        # «Аккаунты» переехали сюда из верхнего ряда: это настройка списка,
        # а не действие над метриками, и наверху они только занимали место.
        self.accounts_btn = ctk.CTkButton(
            pager, text="Аккаунты", corner_radius=12, width=104, height=28,
            fg_color=theme.NEUTRAL_FG, text_color=theme.NEUTRAL_TEXT,
            hover_color=theme.NEUTRAL_FG_HOVER, command=self._open_accounts,
        )
        self.accounts_btn.pack(side="left", padx=(14, 0))
        ctk.CTkButton(nav, text="<", width=32, command=self._prev_page).pack(side="left", padx=2)
        self.page_label = ctk.CTkLabel(nav, text="1 / 1", font=ui_font(11))
        self.page_label.pack(side="left", padx=6)
        ctk.CTkButton(nav, text=">", width=32, command=self._next_page).pack(side="left", padx=2)

        log_header = ctk.CTkFrame(self, fg_color="transparent")
        log_header.pack(fill="x", padx=20, pady=(0, 2))
        ctk.CTkLabel(log_header, text="Лог", font=ui_font(11), text_color=theme.MUTED_TEXT).pack(side="left")
        ctk.CTkButton(
            log_header, text="Собрать тех.данные", corner_radius=12, width=160, height=24,
            font=ui_font(11), fg_color=theme.NEUTRAL_FG, text_color=theme.NEUTRAL_TEXT,
            hover_color=theme.NEUTRAL_FG_HOVER, command=self._export_diagnostics,
        ).pack(side="right")

        self.log_box = ctk.CTkTextbox(self, height=90, font=mono_font(11))
        self.log_box.pack(fill="x", padx=20, pady=(0, 16))
        self.log_box.configure(state="disabled")

    def _refresh_export_button(self, animate=False):
        """«Экспорт» горит акцентным цветом, только когда есть что выгружать.

        Пока ни один аккаунт не собран, выгружать нечего — кнопка остаётся
        нейтральной и не зовёт на себя нажать. Как появляется первый результат,
        она плавно загорается.
        """
        has_data = any(cell.get("status") == "done"
                       for platforms in self.results.values()
                       for cell in platforms.values())
        if has_data == self._export_active:
            return                       # состояние не изменилось, не дёргаем виджет
        self._export_active = has_data

        if has_data:
            self.export_btn.configure(hover_color=self._collect_btn_hover,
                                      text_color=self._accent_text_color)
            if animate:
                animate_color(self.export_btn, "fg_color",
                              self._resolve_color(theme.NEUTRAL_FG),
                              self._resolve_color(self._collect_btn_color))
            else:
                self.export_btn.configure(fg_color=self._collect_btn_color)
        else:
            self.export_btn.configure(fg_color=theme.NEUTRAL_FG,
                                      hover_color=theme.NEUTRAL_FG_HOVER,
                                      text_color=theme.NEUTRAL_TEXT)

    def _open_about(self):
        AboutWindow(self, ytdlp_version=self.ytdlp_version)

    # ------------------------------------------------------ версия yt-dlp
    def _remember_ytdlp_version(self, installed=None):
        """Запоминает версию yt-dlp для окна «О программе».

        После обновления перечитываем РЕАЛЬНО установленную версию, а не
        подставляем ту, которую ожидали получить.
        """
        if installed is None:
            ok, installed = backend_tiktok.check_available()
            installed = installed if ok else None
        self.ytdlp_version = installed

    def _check_ytdlp_version(self):
        """Один раз при запуске, в фоне: не устарел ли yt-dlp (движок сбора TikTok).

        Только СООБЩАЕТ, ничего не устанавливает. Тихое обновление посреди
        наблюдений подменило бы движок сбора без ведома пользователя — а он
        сравнивает цифры день ко дню и не смог бы отличить просадку каналов
        от смены версии. Проверка в фоне, чтобы не задерживать запуск окна.
        """
        def worker():
            try:
                outdated, installed, latest = backend_tiktok.check_for_update()
            except Exception:
                return          # нет сети — молчим, это не повод беспокоить
            self.queue.put(("__YTDLP__", outdated, installed, latest))

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------- тема оформления
    def _theme_btn_text(self):
        return "\u2600 Светлая" if state.appearance_mode == "dark" else "\u263D Тёмная"

    def _toggle_theme(self):
        new_mode = "light" if state.appearance_mode == "dark" else "dark"
        ctk.set_appearance_mode(new_mode)   # CTk сам перекрашивает все открытые окна живьём
        state.set_appearance_mode(new_mode)
        self.theme_btn.configure(text=self._theme_btn_text())

    # ---------------------------------------------------------- статус-бар входа
    def _refresh_status_dots(self):
        for p in PLATFORMS:
            if state.login_status.get(p):
                self.status_dots[p].configure(fg_color=PLATFORM_COLORS[p], text_color="white", hover_color=PLATFORM_COLORS[p])
            else:
                self.status_dots[p].configure(fg_color=theme.NEUTRAL_FG, text_color=theme.NEUTRAL_TEXT, hover_color=theme.NEUTRAL_FG_HOVER)

    def _change_scope(self, label):
        """Смена охвата сбора. Прирост считается только между замерами
        с одинаковым охватом, поэтому базовый снимок ищется заново."""
        state.set_collect_scope(SCOPE_KEYS.get(label, "all"))
        self._log("Охват сбора: %s" % label)
        diagnostics.log("INFO", "scope.change", "Смена охвата", scope=state.collect_scope)

    def _open_login(self, platform):
        if platform in NO_LOGIN_PLATFORMS:
            # Открывать окно входа незачем: площадка собирается анонимно,
            # и введённые логин с паролем всё равно никуда не пойдут.
            self._log("%s собирается без входа — публичные профили читаются анонимно."
                      % PLATFORM_LABELS[platform])
            return
        LoginWindow(self, initial_platform=platform, on_saved=self._refresh_status_dots)

    def _open_accounts(self):
        AccountsWindow(self, on_saved=self._on_accounts_saved)

    def _on_accounts_saved(self):
        self._rebuild_results_skeleton()
        self._refresh_export_button()
        self.page = 1
        self._render_table()

    # ---------------------------------------------------------- данные / таблица
    def _rebuild_results_skeleton(self):
        """Пересоздаёт results под текущий список аккаунтов, статус по умолчанию
        зависит от того, выполнен ли вход для платформы."""
        new_results = {}
        for acc in state.accounts:
            name = acc["name"]
            new_results[name] = {}
            for p in PLATFORMS:
                new_results[name][p] = {
                    "status": "none" if not state.login_status.get(p) else "idle",
                    "views": None, "likes": None, "comments": None,
                }
        self.results = new_results

    def _total_pages(self):
        return max(1, -(-len(state.accounts) // self.page_size))

    def _render_table(self):
        for w in self.table_area.winfo_children():
            w.destroy()
        self.visible_cells = {}

        tp = self._total_pages()
        if self.page > tp:
            self.page = tp
        self.page_label.configure(text="%d / %d" % (self.page, tp))

        start = (self.page - 1) * self.page_size
        chunk = state.accounts[start:start + self.page_size]

        for acc in chunk:
            name = acc["name"]
            row = ctk.CTkFrame(self.table_area, fg_color="transparent")
            row.pack(fill="x", pady=2)
            self._configure_columns(row)
            ctk.CTkLabel(row, text=name, anchor="w").grid(row=0, column=0, sticky="ew", padx=4)
            cells = {}
            for i, p in enumerate(PLATFORMS, start=1):
                lbl = ctk.CTkLabel(row, text=self._cell_text(name, p), justify="left",
                                   anchor="center", text_color=self._cell_color(name, p), cursor="hand2")
                lbl.grid(row=0, column=i, sticky="ew", padx=4)
                lbl.bind("<Button-1>", lambda _e, p=p: self._cell_clicked(p))
                cells[p] = lbl
            self.visible_cells[name] = cells

        self._update_cell_wrap()

    def _update_cell_wrap(self, _event=None):
        """Пересчитывает предельную ширину текста ячейки под текущий размер окна."""
        total = sum(COLUMN_WEIGHTS)
        column_px = self.table_area.winfo_width() * COLUMN_WEIGHTS[1] / total
        wrap = max(80, int(column_px) - 10)  # минус внутренние отступы grid
        for cells in self.visible_cells.values():
            for label in cells.values():
                label.configure(wraplength=wrap)

    def _cell_clicked(self, platform):
        if not state.login_status.get(platform):
            self._open_login(platform)

    def _cell_text(self, name, platform):
        r = self.results.get(name, {}).get(platform, {"status": "none"})
        status = r["status"]
        if status == "none":
            return "нет входа"
        if status == "idle":
            return "—"
        if status == "pending":
            return "\u23F3 …"
        if status == "error":
            return "\u2715 ошибка"
        if status == "done":
            # В строку, а не столбцом: по вертикали место дороже — строк на
            # экране помещается втрое больше. Прирост дописывается прямо
            # к числу: "\U0001F441 4.7K +239".
            delta = r.get("delta") or {}
            return "  ".join(
                "%s %s%s" % (icon, format_compact(r[metric]), format_delta(delta.get(metric)))
                for icon, metric in (("\U0001F441", "views"), ("\u2764", "likes"), ("\U0001F4AC", "comments"))
            )
        return "—"

    def _cell_color(self, name, platform):
        status = self.results.get(name, {}).get(platform, {}).get("status")
        return {"none": theme.MUTED_TEXT, "idle": theme.MUTED_TEXT, "pending": "#BA7517",
               "done": theme.PRIMARY_TEXT, "error": "#A32D2D"}.get(status, theme.MUTED_TEXT)

    # ---------------------------------------------------------- пагинация
    def _change_page_size(self, value):
        self.page_size = int(value)
        self.page = 1
        self._render_table()
        # Подгоняем высоту только при смене «показывать по», но НЕ при
        # перелистывании страниц: прыгающее окно на каждом «>» раздражало бы.
        self.after_idle(self._fit_height)

    def _fit_height(self):
        """Растягивает окно так, чтобы выбранное число строк поместилось
        целиком. Расчёт общий с экраном «Аккаунты» — см. ui_utils."""
        fit_window_height(self, self.table_area)

    def _prev_page(self):
        if self.page > 1:
            self.page -= 1
            self._render_table()

    def _next_page(self):
        if self.page < self._total_pages():
            self.page += 1
            self._render_table()

    # ---------------------------------------------------------- сбор метрик
    def _log(self, text):
        self.log_box.configure(state="normal")
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_box.insert("end", "[%s] %s\n" % (stamp, text))
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _start_collect(self):
        if self.collecting:
            return
        active_platforms = [p for p in PLATFORMS if state.login_status.get(p)]
        if not active_platforms:
            self._log("Нет ни одной платформы со входом — нечего собирать. Нажмите на кружок статуса, чтобы войти.")
            return

        # Если в сборе участвует экспериментальная площадка — предупреждаем
        # один раз и запускаем только после подтверждения.
        risky = [p for p in active_platforms if p in EXPERIMENTAL_PLATFORMS]
        if risky and state.warn_experimental:
            ConfirmWindow(
                self, IG_CONFIRM_TITLE, IG_CONFIRM_TEXT,
                confirm_text="Собрать всё равно",
                on_confirm=self._begin_collect,
                on_dont_ask=lambda: state.set_warn_experimental(False),
            )
            return
        self._begin_collect()

    def _begin_collect(self):
        """Собственно запуск сбора — отделён от _start_collect, чтобы
        предупреждение могло вызвать его после подтверждения."""
        if self.collecting:
            return
        active_platforms = [p for p in PLATFORMS if state.login_status.get(p)]
        if not active_platforms:
            return
        self.collecting = True
        self.stop_flag = False
        self.progress_done = 0
        self.progress_total = len(state.accounts) * len(active_platforms)
        self.progress.set(0)
        # Кнопка не гаснет, а превращается в красную «Стоп» — сбор можно прервать.
        self.collect_btn.configure(
            text="Стоп", fg_color=theme.DANGER_FG, hover_color=theme.DANGER_FG_HOVER,
            command=self._stop_collect,
        )
        # Снимок, с которым сравниваем: последний замер с ТАКИМ ЖЕ охватом
        # за предыдущий день. Берём один раз на весь прогон, чтобы все строки
        # сравнивались с одной и той же точкой отсчёта.
        self.baseline, self.baseline_label = history.find_baseline(state.collect_scope)
        self._log("Начинаю сбор: %s (охват: %s)"
                  % (", ".join(PLATFORM_LABELS[p] for p in active_platforms),
                     SCOPE_LABELS.get(state.collect_scope, state.collect_scope)))
        if self.baseline:
            self._log("Прирост считается %s." % self.baseline_label)
        else:
            self._log("Это первый замер с таким охватом — прирост появится со следующего раза.")
        diagnostics.log("INFO", "collect.start", "Запуск сбора",
                        platforms=",".join(active_platforms), accounts=len(state.accounts))

        for acc in state.accounts:
            for p in active_platforms:
                self.results[acc["name"]][p]["status"] = "pending"
        self._refresh_visible_cells()

        thread = threading.Thread(target=self._collect_worker, args=(list(state.accounts), active_platforms), daemon=True)
        thread.start()

    def _stop_collect(self):
        """Просит фоновый поток остановиться. Уже начатый запрос к площадке
        доводится до конца — обрывать его на полпути нечем, зато следующий
        аккаунт не начнётся, и ждать останется секунду-две, а не минуту."""
        if not self.collecting or self.stop_flag:
            return
        self.stop_flag = True
        self.collect_btn.configure(text="Останавливаю…", state="disabled")
        self._log("Останавливаю сбор — дожидаюсь текущего аккаунта…")
        diagnostics.log("INFO", "collect.stop", "Остановка по кнопке «Стоп»")

    def _reset_collect_button(self):
        self.collect_btn.configure(
            text="Собрать метрики", state="normal", fg_color=self._collect_btn_color,
            hover_color=self._collect_btn_hover, command=self._start_collect,
        )

    def _collect_worker(self, accounts, platforms):
        for acc in accounts:
            for p in platforms:
                if self.stop_flag:
                    self.queue.put(("__DONE__", None, None, None))
                    return
                t0 = time.perf_counter()
                try:
                    result = simulate_collect(acc, p)
                except Exception as e:
                    duration = time.perf_counter() - t0
                    # Настоящее необработанное исключение — не то же самое, что штатный
                    # {"ok": False}: это баг/сбой сети, и он попадает в тех.данные с трассировкой.
                    diagnostics.log_exception(
                        "collect.crash", "Исключение при сборе account=%s platform=%s" % (acc["name"], p), e,
                    )
                    result = {"ok": False, "error": str(e)}
                else:
                    duration = time.perf_counter() - t0
                self.queue.put((acc["name"], p, result, duration))
        self.queue.put(("__DONE__", None, None, None))

    def _poll_queue(self):
        # Окно могли закрыть между двумя тиками — тогда планировать следующий
        # незачем, иначе Tk ругается в консоль на висящий таймер.
        if not self.winfo_exists():
            return
        try:
            while True:
                name, platform, result, duration = self.queue.get_nowait()
                if name == "__YTDLP__":
                    outdated, installed, latest = platform, result, duration
                    self._remember_ytdlp_version(installed)
                    diagnostics.log("INFO", "ytdlp.version", "Проверка версии yt-dlp",
                                    installed=installed, latest=latest, outdated=outdated)
                    if installed is None:
                        self._log("yt-dlp не установлен — TikTok собираться не будет. "
                                  "Установите командой:  pip install -U yt-dlp")
                    elif outdated:
                        # Спрашиваем, а не обновляем молча: пользователь сравнивает
                        # цифры день ко дню, и подмена движка сбора без его ведома
                        # смешала бы просадку каналов со сменой версии.
                        self._log("Доступна новая версия yt-dlp: %s (у вас %s)." % (latest, installed))
                        UpdateWindow(self, installed, latest,
                                     on_updated=lambda: self._remember_ytdlp_version(None))
                    continue
                if name == "__DONE__":
                    self.collecting = False
                    self._reset_collect_button()
                    self.progress.set(0)
                    if self.stop_flag:
                        # Аккаунты, до которых не дошли, не должны навсегда
                        # остаться в статусе «в процессе».
                        for cell in self.results.values():
                            for data in cell.values():
                                if data.get("status") == "pending":
                                    data["status"] = "idle"
                        self._refresh_visible_cells()
                    self.last_collect_label.configure(
                        text="Последний сбор: " + datetime.datetime.now().strftime("%d.%m.%Y, %H:%M")
                    )
                    snapshot = history.append_snapshot(self.results, state.collect_scope)
                    head = "Сбор остановлен" if self.stop_flag else "Сбор завершён"
                    if snapshot:
                        self._log("%s. Замер сохранён в историю (всего замеров с этим охватом: %d)."
                                  % (head, history.snapshot_count(state.collect_scope)))
                    else:
                        self._log("%s, но сохранять нечего — ни один аккаунт не собрался." % head)
                    diagnostics.log("INFO", "collect.finish", "Сбор завершён",
                                    scope=state.collect_scope,
                                    snapshots=history.snapshot_count(state.collect_scope))

                    # Итог показываем после сохранения снимка: цифры берутся
                    # из тех же дельт, что уже нарисованы в таблице, поэтому
                    # окно и таблица не могут разойтись.
                    growth = history.summarize_growth(self.results, PLATFORMS)
                    diagnostics.log("INFO", "collect.growth", "Суммарный прирост",
                                    **{k: v for k, v in (growth.get("total") or {}).items()})
                    SummaryWindow(self, growth, period_label=self.baseline_label,
                                  stopped=self.stop_flag)
                    continue
                if result.get("ok"):
                    delta = history.delta_for(getattr(self, "baseline", None), name, platform, result)
                    self.results[name][platform] = {
                        "status": "done", "views": result["views"],
                        "likes": result["likes"], "comments": result["comments"],
                        "delta": delta,
                    }
                    growth = ""
                    if delta and delta.get("views"):
                        growth = "  (%+d %s %s)" % (delta["views"], plural_views(delta["views"]),
                                                   self.baseline_label)
                    self._log("%s: %s — \U0001F441 %s \u2764 %s \U0001F4AC %s%s" % (
                        PLATFORM_LABELS[platform], name,
                        format(result["views"], ","), format(result["likes"], ","), format(result["comments"], ","),
                        growth,
                    ))
                    diagnostics.log("INFO", "collect.success", "", account=name, platform=platform,
                                    views=result["views"], likes=result["likes"], comments=result["comments"],
                                    duration="%.2fs" % duration)
                else:
                    self.results[name][platform] = {
                        "status": "error", "views": None, "likes": None, "comments": None,
                    }
                    self._log("%s: %s — %s" % (PLATFORM_LABELS[platform], name, result.get("error", "ошибка")))
                    diagnostics.log("WARNING", "collect.fail", result.get("error", "ошибка"),
                                    account=name, platform=platform, duration="%.2fs" % duration)
                self.progress_done += 1
                if self.progress_total:
                    self.progress.set(self.progress_done / float(self.progress_total))
                    self.last_collect_label.configure(
                        text="Собираю: %d из %d" % (self.progress_done, self.progress_total))
                self._refresh_one_cell(name, platform, flash=True)
                self._refresh_export_button(animate=True)
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def _refresh_one_cell(self, name, platform, flash=False):
        cells = self.visible_cells.get(name)
        if not cells:
            return  # аккаунт не на текущей странице — данные всё равно обновлены, покажутся при переходе
        lbl = cells[platform]
        target = self._cell_color(name, platform)
        lbl.configure(text=self._cell_text(name, platform), text_color=target)
        if flash:
            # Загорается цветом площадки и плавно гаснет до обычного: при сборе
            # 20 аккаунтов строки заполняются вразнобой, и без подсветки трудно
            # заметить, куда именно пришёл результат.
            flash_text_color(lbl, PLATFORM_COLORS[platform], self._resolve_color(target))

    def _resolve_color(self, color):
        """Цвет под текущую тему: CustomTkinter хранит пары (светлый, тёмный),
        а смешивать оттенки можно только с одиночным hex."""
        if isinstance(color, (tuple, list)):
            return color[1] if state.appearance_mode == "dark" else color[0]
        return color

    def _refresh_visible_cells(self):
        for name, cells in self.visible_cells.items():
            for p, lbl in cells.items():
                lbl.configure(text=self._cell_text(name, p), text_color=self._cell_color(name, p))

    # ---------------------------------------------------------- экспорт
    def _export(self):
        self.open_export_menu(self.export_btn)

    def open_export_menu(self, anchor):
        """Выпадающее меню экспорта под указанной кнопкой.

        Вынесено отдельно, потому что тем же меню пользуется итоговое окно
        после сбора — второй набор пунктов рассинхронизировался бы с этим.
        Меню создаём на том окне, где кнопка: итоговое окно модальное
        (grab_set), и меню, привязанное к другому окну, не получило бы событий.
        """
        menu = Menu(anchor.winfo_toplevel(), tearoff=0)
        # Копирование — первым пунктом: путь «собрал -> вставил в Google Таблицы»
        # используется чаще, чем сохранение файла на диск.
        menu.add_command(label="Копировать в буфер обмена", command=self._copy_to_clipboard)
        menu.add_separator()
        menu.add_command(label="Excel (.xlsx)", command=lambda: self._do_export(exporters.export_xlsx))
        menu.add_command(label="CSV (.csv)", command=lambda: self._do_export(exporters.export_csv))
        menu.add_command(label="Текст (.txt)", command=lambda: self._do_export(exporters.export_txt))
        menu.add_command(label="PDF (.pdf)", command=lambda: self._do_export(exporters.export_pdf))
        menu.tk_popup(anchor.winfo_rootx(),
                      anchor.winfo_rooty() + anchor.winfo_height())

    def _copy_to_clipboard(self):
        """Кладёт таблицу в буфер с табуляцией — вставляется прямо в Google Таблицы."""
        text = exporters.build_tsv(state.accounts, self.results)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()  # без этого содержимое буфера не доживает до другого приложения
        rows = len(text.splitlines()) - 1
        self._log("Скопировано в буфер: %d строк. Вставьте в Google Таблицы (Cmd+V)." % rows)
        diagnostics.log("INFO", "export.clipboard", "Копирование в буфер", rows=rows)

    def _do_export(self, export_func):
        path = export_func(state.accounts, self.results)
        if path:
            self._log("Экспортировано в: %s" % path)
        else:
            self._log("Не удалось выполнить экспорт (см. тех.данные).")

    def _export_diagnostics(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile="easygrab_diagnostics.txt",
            filetypes=[("Текстовый файл", "*.txt")],
        )
        if not path:
            return
        ok = diagnostics.export_report(path)
        if ok:
            self._log("Технические данные сохранены в: %s" % path)
        else:
            self._log("Не удалось сохранить технические данные.")
