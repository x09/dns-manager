# -*- coding: utf-8 -*-
"""Определение наличия действующего билета Kerberos (klist)."""

import subprocess


def has_ticket():
    """True — в ccache есть действующий TGT (klist -s вернул 0)."""
    try:
        r = subprocess.run(
            ["klist", "-s"], timeout=4,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return r.returncode == 0
    except (FileNotFoundError, OSError):
        return False


def get_principal():
    """
    Возвращает строку с именем principal (user@REALM) или None.
    Разбирает вывод `klist` — поддерживает форматы MIT krb5 и Heimdal.
    """
    try:
        r = subprocess.run(
            ["klist"], timeout=4,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return None
        for line in r.stdout.splitlines():
            low = line.lower().strip()
            # MIT: "Default principal: user@REALM"
            if low.startswith("default principal:"):
                return line.split(":", 1)[1].strip()
            # Heimdal / older MIT: "Principal: user@REALM"
            if low.startswith("principal:"):
                return line.split(":", 1)[1].strip()
        return None
    except Exception:
        return None
