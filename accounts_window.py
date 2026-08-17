# -*- coding: utf-8 -*-
"""Экран "Аккаунты" — таблица-редактор: одна строка на аккаунт.

Колонки: Название, Тематика, YouTube, Instagram, TikTok, удаление строки.
Пагинация: выбор "показывать по" (5/10/20/50) + постраничная навигация,
сама таблица дополнительно прокручивается (CTkScrollableFrame), если даже
выбранное число строк не помещается по высоте.

Колонки выровнены через grid с общим "uniform"-тегом (см. main_window.py) —
заголовок и поля ввода в каждой строке всегда совпадают по ширине независимо
от системного шрифта конкретной ОС.
"""
import copy

import customtkinter as ctk

from app_state import state
from ui_utils import fade_in, fit_window_height
from fonts import ui_font
import theme

PAGE_SIZES = (5, 10, 20, 50)
COLS = ("name", "topic", "yt", "ig", "tt")
COL_LABELS = {"name": "Название", "topic": "Тематика", "yt": "YouTube", "ig": "Instagram", "tt": "TikTok"}
COL_PLACEHOLDER = {"yt": "youtube.com/@...", "ig": "instagram.com/...", "tt": "tiktok.com/@..."}
# Три колонки со ссылками одинаковой ширины: раньше TikTok имел вес 2 против
# 3 у YouTube и Instagram, и на окне 890px ему доставалось 133px против 200px.
# Замер: хвосты ссылок просят 197-231px, название — 63px, тематика — до 135px.
COL_WEIGHTS = {"name": 2, "topic": 3, "yt": 4, "ig": 4, "tt": 4}
LINK_COLS = ("yt", "ig", "tt")
COLUMN_UNIFORM = "easygrab_accounts_cols"


class AccountsWindow(ctk.CTkToplevel):
    def __init__(self, master, on_saved=None):
        super().__init__(master)
        self.on_saved = on_saved
        self.title("EasyGrab — Аккаунты")
        self.geometry("900x560")     # как у главного окна; ссылкам нужна ширина
        self.minsize(720, 420)
        self.resizable(True, True)
        self.grab_set()

        self.rows = copy.deepcopy(state.accounts)
        self.page_size = 10
        self.page = 1
        self.row_widgets = []  # виджеты текущей страницы, для чтения значений перед перерисовкой

        self._build()
        self._render()
        fade_in(self)
        # Высоту подгоняем после первой отрисовки: до неё виджеты ещё не знают
        # своих размеров, и считать было бы не по чему.
        self.after_idle(self._fit_height)

    # ---------------------------------------------------------- построение UI
    def _configure_columns(self, frame):
        for i, c in enumerate(COLS):
            frame.grid_columnconfigure(i, weight=COL_WEIGHTS[c], uniform=COLUMN_UNIFORM)
        frame.grid_columnconfigure(len(COLS), weight=0)  # колонка под кнопку удаления — фиксированная

    def _build(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(16, 8))
        self.count_label = ctk.CTkLabel(top, text="Аккаунты", font=ui_font(15, "bold"))
        self.count_label.pack(side="left")
        ctk.CTkButton(top, text="+ Добавить аккаунт", corner_radius=12, width=160,
                      command=self._add_row).pack(side="right")

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20)
        self._configure_columns(header)
        for i, c in enumerate(COLS):
            ctk.CTkLabel(header, text=COL_LABELS[c], font=ui_font(11), text_color=theme.MUTED_TEXT,
                        anchor="w").grid(row=0, column=i, sticky="ew", padx=4)
        ctk.CTkLabel(header, text="", width=28).grid(row=0, column=len(COLS))

        self.table_area = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.table_area.pack(fill="both", expand=True, padx=20, pady=(2, 8))

        pager = ctk.CTkFrame(self, fg_color="transparent")
        pager.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkLabel(pager, text="Показывать по", font=ui_font(11), text_color=theme.MUTED_TEXT).pack(side="left")
        self.page_size_var = ctk.StringVar(value=str(self.page_size))
        size_menu = ctk.CTkOptionMenu(
            pager, values=[str(s) for s in PAGE_SIZES], variable=self.page_size_var,
            width=70, command=self._change_page_size,
        )
        size_menu.pack(side="left", padx=(6, 0))

        nav = ctk.CTkFrame(pager, fg_color="transparent")
        nav.pack(side="right")
        ctk.CTkButton(nav, text="<", width=32, command=self._prev_page).pack(side="left", padx=2)
        self.page_label = ctk.CTkLabel(nav, text="1 / 1", font=ui_font(11))
        self.page_label.pack(side="left", padx=6)
        ctk.CTkButton(nav, text=">", width=32, command=self._next_page).pack(side="left", padx=2)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkButton(bottom, text="Отмена", corner_radius=12, fg_color=theme.NEUTRAL_FG,
                      text_color=theme.NEUTRAL_TEXT, hover_color=theme.NEUTRAL_FG_HOVER,
                      command=self._cancel).pack(side="left", expand=True, fill="x", padx=(0, 6))
        ctk.CTkButton(bottom, text="Сохранить", corner_radius=12,
                      command=self._save).pack(side="left", expand=True, fill="x", padx=(6, 0))
        self.saved_label = ctk.CTkLabel(self, text="", text_color="#1FA34C", font=ui_font(11))
        self.saved_label.pack(pady=(0, 6))

    # ---------------------------------------------------------- пагинация / рендер
    def _total_pages(self):
        return max(1, -(-len(self.rows) // self.page_size))  # округление вверх

    def _sync_current_page_from_widgets(self):
        """Считывает значения полей текущей страницы обратно в self.rows перед сменой страницы."""
        for idx, entries in self.row_widgets:
            for c in COLS:
                self.rows[idx][c] = entries[c].get()

    def _render(self):
        for w in self.table_area.winfo_children():
            w.destroy()
        self.row_widgets = []

        total = len(self.rows)
        tp = self._total_pages()
        if self.page > tp:
            self.page = tp
        self.count_label.configure(text="Аккаунты  (%d из %d)" % (total, total))
        self.page_label.configure(text="%d / %d" % (self.page, tp))

        start = (self.page - 1) * self.page_size
        chunk = list(enumerate(self.rows))[start:start + self.page_size]

        for global_idx, row in chunk:
            row_frame = ctk.CTkFrame(self.table_area, fg_color="transparent")
            row_frame.pack(fill="x", pady=2)
            self._configure_columns(row_frame)
            entries = {}
            for i, c in enumerate(COLS):
                entry = ctk.CTkEntry(row_frame, placeholder_text=COL_PLACEHOLDER.get(c, ""))
                entry.insert(0, row.get(c, ""))
                entry.grid(row=0, column=i, sticky="ew", padx=4)
                entries[c] = entry
            del_btn = ctk.CTkButton(
                row_frame, text="\u2715", width=28, fg_color=theme.NEUTRAL_FG,
                text_color=theme.NEUTRAL_TEXT, hover_color=theme.DANGER_HOVER,
                command=lambda i=global_idx: self._delete_row(i),
            )
            del_btn.grid(row=0, column=len(COLS), padx=(4, 0))
            self.row_widgets.append((global_idx, entries))

        # Прокручиваем ссылки к концу после того, как grid расставит колонки:
        # до этого поля ещё не знают своей настоящей ширины.
        self.after_idle(self._show_link_endings)

    def _fit_height(self):
        """Растягивает окно под выбранное «показывать по». Расчёт общий
        с главным окном — см. ui_utils.fit_window_height."""
        fit_window_height(self, self.table_area)

    def _show_link_endings(self):
        """Показывает КОНЕЦ ссылки вместо начала.

        Начало у всех строк одинаковое — «https://www.youtube.com/», — и на
        экране видно только его. Различает аккаунты как раз хвост с юзернеймом,
        поэтому поле прокручивается вправо. Сам текст не меняется: это
        прокрутка внутри поля, при клике и правке всё ведёт себя как обычно.
        """
        for _idx, entries in self.row_widgets:
            for c in LINK_COLS:
                entry = entries.get(c)
                if entry is not None and entry.get():
                    try:
                        entry.xview_moveto(1.0)
                    except Exception:
                        pass   # поле уже уничтожено (сменили страницу) — не беда

    # ---------------------------------------------------------- обработчики
    def _change_page_size(self, value):
        self._sync_current_page_from_widgets()
        self.page_size = int(value)
        self.page = 1
        self._render()
        # Подгоняем высоту только при смене «показывать по», но НЕ при
        # перелистывании страниц: прыгающее окно при каждом «>» раздражало бы.
        self.after_idle(self._fit_height)

    def _prev_page(self):
        self._sync_current_page_from_widgets()
        if self.page > 1:
            self.page -= 1
        self._render()

    def _next_page(self):
        self._sync_current_page_from_widgets()
        if self.page < self._total_pages():
            self.page += 1
        self._render()

    def _add_row(self):
        self._sync_current_page_from_widgets()
        self.rows.append({"name": "Новый аккаунт", "topic": "", "yt": "", "ig": "", "tt": ""})
        self.page = self._total_pages()
        self._render()

    def _delete_row(self, global_idx):
        self._sync_current_page_from_widgets()
        del self.rows[global_idx]
        self._render()

    def _save(self):
        """Сохраняет и закрывает окно.

        Раньше окно оставалось открытым, и после сохранения его приходилось
        закрывать крестиком — ровно та же беда, что была у «Отмены».
        Галочку показываем на мгновение, чтобы сохранение было заметно.
        """
        self._sync_current_page_from_widgets()
        state.save_accounts(self.rows)
        self.saved_label.configure(text="Сохранено \u2713")
        if self.on_saved:
            self.on_saved()
        self.after(700, self.destroy)

    def _cancel(self):
        """Отменяет правки и ЗАКРЫВАЕТ окно.

        Раньше здесь был только откат изменений без закрытия: таблица на глазах
        возвращалась к сохранённому виду, а окно оставалось — и выйти можно было
        только крестиком.
        """
        state.reload_accounts()      # возвращаем в память то, что на диске
        self.destroy()
