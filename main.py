# -*- coding: utf-8 -*-
"""EasyGrab — точка входа. Запуск: python main.py"""
import customtkinter as ctk

import diagnostics
from main_window import MainWindow
from app_state import state

if __name__ == "__main__":
    diagnostics.install_exception_hooks()  # ловим падения — и в главном потоке, и в потоке сбора
    ctk.set_appearance_mode(state.appearance_mode)  # по умолчанию "dark", если не менялось
    ctk.set_default_color_theme("blue")
    app = MainWindow()
    app.mainloop()
