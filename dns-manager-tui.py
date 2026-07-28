#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диспетчер DNS для Samba DC — консольная (TUI) версия на urwid.

Запуск:  ./dns-manager-tui.py   (в терминале, в т.ч. по SSH)
Зависимости: python3 (3.12), python3-module-urwid, python3-module-samba.
"""

import os
import sys

# Пакет dnsmgr ищем в нескольких местах (как в GUI-версии).
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
    "Не найдены python-биндинги Samba (модуль samba.dcerpc.dnsserver).\n"
    "Установите их. В ОС Альт:\n"
    "    # apt-get update && apt-get install python3-module-samba"
)

URWID_HINT = (
    "Не найден модуль urwid.\n"
    "Установите его. В ОС Альт:\n"
    "    # apt-get update && apt-get install python3-module-urwid"
)


def main():
    try:
        import urwid  # noqa: F401
    except ImportError:
        print(URWID_HINT, file=sys.stderr)
        sys.exit(1)

    try:
        import samba.dcerpc.dnsserver  # noqa: F401
    except ImportError:
        print(SAMBA_HINT, file=sys.stderr)
        sys.exit(1)

    # Локализация ДО импорта UI-модулей (иначе _() не установлен).
    from dnsmgr import config, i18n
    i18n.setup(config.load_language())

    from dnsmgr.tui.app import main as run
    run()


if __name__ == "__main__":
    main()
