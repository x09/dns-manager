#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диспетчер DNS для Samba DC — аналог Microsoft DNS Manager для Linux.

Запуск:  ./dns-manager.py
Зависимости: python3 (3.12), tkinter, python-биндинги Samba
(в ОС Альт — пакет python3-module-samba).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SAMBA_HINT = (
    "Не найдены python-биндинги Samba (модуль samba.dcerpc.dnsserver).\n\n"
    "Установите их. В ОС Альт:\n"
    "    # apt-get update && apt-get install python3-module-samba\n\n"
    "(модуль также входит в состав пакетов samba-dc / samba-client)"
)

TK_HINT = (
    "Не найден модуль tkinter.\n\n"
    "Установите его. В ОС Альт:\n"
    "    # apt-get update && apt-get install python3-modules-tkinter"
)


def fail(message):
    """Выводит ошибку в консоль и, если возможно, в графическое окно."""
    print(message, file=sys.stderr)
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Диспетчер DNS — ошибка запуска", message)
        root.destroy()
    except Exception:
        pass
    sys.exit(1)


def main():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print(TK_HINT, file=sys.stderr)
        sys.exit(1)

    try:
        import samba.dcerpc.dnsserver  # noqa: F401
    except ImportError:
        fail(SAMBA_HINT)

    from dnsmgr.mainwindow import main as run
    run()


if __name__ == "__main__":
    main()
