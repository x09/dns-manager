# -*- coding: utf-8 -*-
"""
Список серверов для подключения в ~/.config/dns-manager/dns-manager.ini

Формат (по одной секции на сервер):

    [1.2.3.4]
    user=login
    kerberos=false

Пароль намеренно не сохраняется.
"""

import configparser
import os

_CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "dns-manager")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "dns-manager.ini")


def _as_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on", "да")


def load_servers():
    """
    Возвращает список серверов в порядке из файла:
    [{'server': '1.2.3.4', 'username': 'login', 'kerberos': False}, ...]
    """
    parser = configparser.ConfigParser()
    servers = []
    try:
        # read сохраняет порядок секций
        if parser.read(_CONFIG_FILE, encoding="utf-8"):
            for name in parser.sections():
                sec = parser[name]
                servers.append({
                    "server": name,
                    "username": sec.get("user", ""),
                    "kerberos": _as_bool(sec.get("kerberos", "false")),
                })
    except (OSError, configparser.Error):
        pass
    return servers


def _write(parser):
    try:
        os.makedirs(_CONFIG_DIR, mode=0o700, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            parser.write(f)
        os.chmod(_CONFIG_FILE, 0o600)
    except OSError:
        # Невозможность сохранить настройки не должна мешать работе
        pass


def save_server(server, username, kerberos):
    """Добавляет или обновляет секцию сервера (сохраняется после подключения)."""
    parser = configparser.ConfigParser()
    try:
        parser.read(_CONFIG_FILE, encoding="utf-8")
    except (OSError, configparser.Error):
        pass
    if not parser.has_section(server):
        parser.add_section(server)
    parser[server]["user"] = username or ""
    parser[server]["kerberos"] = "true" if kerberos else "false"
    _write(parser)


def remove_server(server):
    """Удаляет секцию сервера из конфигурации."""
    parser = configparser.ConfigParser()
    try:
        parser.read(_CONFIG_FILE, encoding="utf-8")
    except (OSError, configparser.Error):
        return
    if parser.has_section(server):
        parser.remove_section(server)
        _write(parser)
