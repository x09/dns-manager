# -*- coding: utf-8 -*-
"""Общие вспомогательные функции, не зависящие ни от tkinter, ни от urwid."""


def open_url(url):
    """
    Открывает URL в браузере по умолчанию через xdg-open (Linux).
    Запускается в фоне, не блокируя интерфейс; ошибки подавляются.
    """
    import subprocess
    try:
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except (OSError, ValueError):
        # Резервный вариант — стандартный модуль webbrowser.
        try:
            import webbrowser
            webbrowser.open(url)
            return True
        except Exception:
            return False
