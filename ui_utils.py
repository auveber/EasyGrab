# -*- coding: utf-8 -*-
"""Общие приёмы разметки для окон EasyGrab.

Пока здесь одна вещь — подгонка высоты окна под содержимое таблицы. Она нужна
и главному окну, и экрану «Аккаунты», причём считать надо одинаково, а числа
у окон разные (у главного обвязка больше из-за лога внизу). Поэтому логика
живёт в одном месте, а всё остальное измеряется на ходу.
"""

FADE_MS = 170        # длительность плавного появления окна
FADE_STEPS = 14      # шагов анимации: 14 кадров за 170 мс — глазу достаточно

ROW_GAP = 4          # вертикальный зазор между строками (pady=2 сверху и снизу)
SCREEN_MARGIN = 140  # запас под строку меню, док и заголовок окна


def fit_window_height(window, scrollable):
    """Растягивает окно так, чтобы все отрисованные строки поместились целиком.

    Если экрана не хватает, окно разворачивается на доступную высоту, а остаток
    листается прокруткой — она никуда не девается.

    Ничего не зашито числами: высота строки и обвязки зависит от системного
    шрифта, а он на macOS и Windows разный. Поэтому и шаг строки, и обвязку
    берём замером с уже отрисованного окна.

    Возвращает выставленную высоту либо None, если мерить было ещё нечего.
    """
    window.update_idletasks()

    rows = scrollable.winfo_children()
    if not rows:
        return None

    # Видимая область прокручиваемого блока — это его внутренний холст,
    # он заметно меньше самого блока (рамка плюс место под полосу прокрутки).
    try:
        visible = scrollable._parent_canvas.winfo_height()
    except AttributeError:
        return None
    if visible <= 1:
        return None      # окно ещё не разложено, мерить нечего

    row_height = rows[0].winfo_height()
    if len(rows) > 1:
        step = (rows[-1].winfo_y() - rows[0].winfo_y()) / (len(rows) - 1)
    else:
        step = row_height + ROW_GAP
    if step <= 1:
        return None

    # Обвязка — всё, кроме видимой области таблицы: шапка, кнопки, заголовки
    # колонок, пагинатор, лог, поля окна.
    chrome = window.winfo_height() - visible
    needed = int(step * (len(rows) - 1) + row_height + ROW_GAP * 2)

    max_height = window.winfo_screenheight() - SCREEN_MARGIN
    height = min(chrome + needed, max_height)
    window.geometry("%dx%d" % (window.winfo_width(), height))
    return height


def fade_in(window, duration_ms=FADE_MS, steps=FADE_STEPS):
    """Плавное появление окна вместо резкого «выскакивания».

    Работает через прозрачность окна (-alpha). Если система её не умеет,
    окно просто появится сразу — анимация здесь украшение, а не механика,
    и ломать из-за неё ничего нельзя.

    Анимация идёт через after(), то есть в главном потоке между событиями:
    интерфейс во время неё остаётся отзывчивым.
    """
    try:
        window.wm_attributes("-alpha", 0.0)
    except Exception:
        return

    delay = max(1, duration_ms // steps)

    def step(frame):
        if not window.winfo_exists():
            return
        try:
            window.wm_attributes("-alpha", min(1.0, frame / float(steps)))
        except Exception:
            return
        if frame < steps:
            window.after(delay, lambda: step(frame + 1))

    step(1)


def _to_rgb(color):
    """«#1F6AA5» -> (31, 106, 165)."""
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _blend(from_color, to_color, t):
    """Промежуточный цвет между двумя: t=0 — первый, t=1 — второй."""
    a, b = _to_rgb(from_color), _to_rgb(to_color)
    return "#%02X%02X%02X" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def animate_color(widget, option, from_color, to_color, duration_ms=300, steps=10):
    """Плавно переводит любой цветовой параметр виджета из одного в другой.

    option — имя параметра CustomTkinter: "text_color", "fg_color" и т.п.
    Оба цвета — одиночные hex-строки: пары (светлый, тёмный) сюда передавать
    нельзя, нужный под тему выбирает вызывающая сторона.
    """
    delay = max(1, duration_ms // steps)

    def step(frame):
        if not widget.winfo_exists():
            return
        try:
            widget.configure(**{option: _blend(from_color, to_color, frame / float(steps))})
        except Exception:
            return                      # виджет уничтожен на смене страницы
        if frame < steps:
            widget.after(delay, lambda: step(frame + 1))

    step(0)


def flash_text_color(label, from_color, to_color, duration_ms=420, steps=12):
    """Подсвечивает текст цветом и плавно гасит его до обычного.

    Нужно, чтобы взгляд сам находил строку, в которую только что пришёл
    результат: при сборе 20 аккаунтов они заполняются вразнобой, и без
    подсветки заметить изменение трудно.

    Оба цвета — обычные hex-строки. Пары (светлый, тёмный) сюда передавать
    нельзя: цвет под текущую тему выбирает вызывающая сторона.
    """
    delay = max(1, duration_ms // steps)

    def step(frame):
        if not label.winfo_exists():
            return
        try:
            label.configure(text_color=_blend(from_color, to_color, frame / float(steps)))
        except Exception:
            return                      # виджет уничтожен на смене страницы
        if frame < steps:
            label.after(delay, lambda: step(frame + 1))

    step(0)
