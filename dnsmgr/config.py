# -*- coding: utf-8 -*-
"""
Список серверов для подключения в ~/.config/dns-manager/dns-manager.ini

Формат (по одной секции на сервер):

    [1.2.3.4]
    user=login
    kerberos=false
    realm=TEST.ALT

Пароль намеренно не сохраняется.
"""

import configparser
import os

_CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "dns-manager")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "dns-manager.ini")

# Зарезервированная секция общих настроек приложения (не сервер).
_SETTINGS_SECTION = "settings"


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
                if name == _SETTINGS_SECTION:
                    continue  # это общие настройки, а не сервер
                sec = parser[name]
                servers.append({
                    "server": name,
                    "username": sec.get("user", ""),
                    "kerberos": _as_bool(sec.get("kerberos", "false")),
                    "realm": sec.get("realm", ""),
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


def save_server(server, username, kerberos, realm=""):
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
    parser[server]["realm"] = realm or ""
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


def load_language():
    """
    Возвращает сохранённый код языка интерфейса ('ru' или 'en') или None,
    если язык ещё не выбран (первый запуск).
    """
    parser = configparser.ConfigParser()
    try:
        if parser.read(_CONFIG_FILE, encoding="utf-8"):
            if parser.has_section(_SETTINGS_SECTION):
                lang = parser[_SETTINGS_SECTION].get("language", "").strip()
                if lang:
                    return lang.lower()
    except (OSError, configparser.Error):
        pass
    return None


def save_language(lang):
    """Сохраняет выбранный код языка интерфейса ('ru' или 'en')."""
    parser = configparser.ConfigParser()
    try:
        parser.read(_CONFIG_FILE, encoding="utf-8")
    except (OSError, configparser.Error):
        pass
    if not parser.has_section(_SETTINGS_SECTION):
        parser.add_section(_SETTINGS_SECTION)
    parser[_SETTINGS_SECTION]["language"] = (lang or "").lower()
    _write(parser)
