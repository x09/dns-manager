# -*- coding: utf-8 -*-
"""Сохранение параметров подключения (сервер и логин, без пароля)."""

import json
import os

_CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "samba-dns-manager")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")


def load():
    """Возвращает словарь настроек: {'server': ..., 'username': ...}."""
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {
                "server": str(data.get("server", "")),
                "username": str(data.get("username", "")),
            }
    except (OSError, ValueError):
        pass
    return {"server": "", "username": ""}


def save(server, username):
    """Сохраняет сервер и логин. Пароль намеренно не сохраняется."""
    try:
        os.makedirs(_CONFIG_DIR, mode=0o700, exist_ok=True)
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"server": server, "username": username},
                      f, ensure_ascii=False, indent=2)
        os.chmod(_CONFIG_FILE, 0o600)
    except OSError:
        # Невозможность сохранить настройки не должна мешать работе
        pass
