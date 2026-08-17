# -*- coding: utf-8 -*-
"""Маленькая всплывающая подсказка при наведении — для значков ⓘ."""
import tkinter as tk

from fonts import ui_font


class ToolTip:
    def __init__(self, widget, text, wraplength=260):
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.tip = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry("+%d+%d" % (x, y))
        label = tk.Label(
            self.tip, text=self.text, justify="left", wraplength=self.wraplength,
            background="#2c2c2a", foreground="#ffffff", padx=8, pady=6,
            font=ui_font(9),
        )
        label.pack()

    def _hide(self, _event=None):
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None
