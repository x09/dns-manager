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

# Пакет dnsmgr ищем в нескольких местах:
#   1) рядом с самим скриптом (запуск из папки проекта);
#   2) рядом с целью символической ссылки (если /usr/bin/dns-manager — ссылка);
#   3) в стандартных каталогах установки.
_CANDIDATE_DIRS = [
    os.path.dirname(os.path.abspath(__file__)),
    os.path.dirname(os.path.realpath(__file__)),
    "/usr/share/dns-manager",
    "/usr/local/share/dns-manager",
    os.path.expanduser("~/.local/share/dns-manager"),
]

for _d in _CANDIDATE_DIRS:
    if os.path.isfile(os.path.join(_d, "dnsmgr", "__init__.py")):
        if _d not in sys.path:
            sys.path.insert(0, _d)
        break

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
