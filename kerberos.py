# -*- coding: utf-8 -*-
"""Определение наличия действующего билета Kerberos (klist)."""

import os
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


def get_realm():
    """
    Возвращает realm (в верхнем регистре) из principal действующего билета,
    например 'TEST.ALT', или None.

    Нужно потому, что Samba (в отличие от MIT-утилит вроде ldapsearch) не
    берёт realm из /etc/krb5.conf для GSSAPI-бинда. Без явно заданного realm
    на машине вне домена (без smb.conf) gensec возвращает
    NT_STATUS_INVALID_PARAMETER.
    """
    principal = get_principal()
    if principal and "@" in principal:
        realm = principal.split("@", 1)[1].strip()
        if realm:
            return realm.upper()
    return None


def get_ccache_name():
    """
    Возвращает имя (тип) используемого кэша билетов, например
    'KEYRING:persistent:500:500' или 'FILE:/tmp/krb5cc_500', или None.

    Сначала берётся переменная окружения KRB5CCNAME, затем строка
    'Ticket cache:' из вывода klist.
    """
    name = os.environ.get("KRB5CCNAME")
    if name:
        return name.strip()
    try:
        r = subprocess.run(
            ["klist"], timeout=4,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return None
        for line in r.stdout.splitlines():
            if line.lower().strip().startswith("ticket cache:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        return None
    return None


def ccache_is_keyring(name=None):
    """
    True, если кэш билетов имеет тип KEYRING или KCM — с ними клиентские
    библиотеки Samba (gensec) не могут прочитать принципала и вход по
    Kerberos падает с NT_STATUS_INVALID_PARAMETER. MIT-утилиты
    (kinit/ldapsearch) с такими кэшами работают, поэтому проблема неочевидна.
    """
    if name is None:
        name = get_ccache_name()
    n = (name or "").upper()
    return n.startswith("KEYRING:") or n.startswith("KCM:")
