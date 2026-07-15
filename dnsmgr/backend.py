# -*- coding: utf-8 -*-
"""
Взаимодействие с DNS-сервером Samba DC по протоколу MS-DNSP (DCERPC).

Используются python-биндинги Samba (пакет python3-module-samba в ОС Альт).
Логика вызовов повторяет реализацию `samba-tool dns` (samba/netcmd/dns.py).
"""

import ipaddress
import re

from samba import credentials, param
from samba.dcerpc import dnsp, dnsserver
from samba.dnsserver import (
    AAAARecord,
    ARecord,
    CNAMERecord,
    MXRecord,
    NSRecord,
    PTRRecord,
    SRVRecord,
    TXTRecord,
)

CLIENT_VERSION = dnsserver.DNS_CLIENT_VERSION_LONGHORN

# Отображаемые имена типов записей
TYPE_NAMES = {
    dnsp.DNS_TYPE_A: "A",
    dnsp.DNS_TYPE_AAAA: "AAAA",
    dnsp.DNS_TYPE_CNAME: "CNAME",
    dnsp.DNS_TYPE_MX: "MX",
    dnsp.DNS_TYPE_NS: "NS",
    dnsp.DNS_TYPE_PTR: "PTR",
    dnsp.DNS_TYPE_SOA: "SOA",
    dnsp.DNS_TYPE_SRV: "SRV",
    dnsp.DNS_TYPE_TXT: "TXT",
}

# Типы, которые пользователь может создавать/править (по ТЗ)
EDITABLE_TYPES = ("A", "AAAA", "CNAME", "MX", "PTR", "SRV", "TXT")

# Понятные сообщения для кодов ошибок Win32/WERROR
_WERROR_MESSAGES = {
    5: "Отказано в доступе. Проверьте права учётной записи "
       "(нужно членство в группе Domain Admins или DnsAdmins).",
    1326: "Неверное имя пользователя или пароль.",
    1722: "RPC-сервер недоступен. Проверьте имя сервера и сетевое подключение.",
    9601: "Указанная зона не существует.",
    9609: "Зона с таким именем уже существует.",
    9611: "Недопустимый тип зоны.",
    9711: "Такая DNS-запись уже существует.",
    9714: "Имя не существует в зоне.",
    9715: "DNS-запись не найдена.",
}


class DnsBackendError(Exception):
    """Ошибка при работе с DNS-сервером (с понятным описанием)."""


def friendly_error(exc):
    """Преобразует исключение samba/RPC в понятное сообщение."""
    if isinstance(exc, DnsBackendError):
        return str(exc)
    text = None
    if isinstance(exc, RuntimeError) and exc.args:
        code = exc.args[0]
        if isinstance(code, int):
            # Werror может быть с установленным старшим битом (HRESULT)
            text = _WERROR_MESSAGES.get(code & 0xFFFF)
        if text is None and len(exc.args) > 1:
            raw = str(exc.args[1])
            if "NT_STATUS_LOGON_FAILURE" in raw:
                text = "Неверное имя пользователя или пароль."
            elif "NT_STATUS_IO_TIMEOUT" in raw or "NT_STATUS_CONNECTION" in raw:
                text = "Не удалось подключиться к серверу (таймаут/обрыв соединения)."
            elif "NT_STATUS_OBJECT_NAME_NOT_FOUND" in raw or "NT_STATUS_HOST_UNREACHABLE" in raw:
                text = "Сервер не найден или недоступен."
            else:
                text = raw
    return text or str(exc)


def reverse_zone_name(network):
    """
    Строит имя обратной зоны по ИД сети.

    Примеры:
      '192.168.1'      -> '1.168.192.in-addr.arpa'
      '192.168.1.0/24' -> '1.168.192.in-addr.arpa'
      '10.0.0.0/16'    -> '0.10.in-addr.arpa'
      '2001:db8::/32'  -> '8.b.d.0.1.0.0.2.ip6.arpa'
    Если передано уже готовое имя зоны (*.arpa) — возвращается как есть.
    """
    network = network.strip().rstrip(".")
    if network.lower().endswith(".arpa"):
        return network.lower()

    if "/" in network or ":" in network:
        try:
            net = ipaddress.ip_network(network, strict=False)
        except ValueError:
            raise DnsBackendError(
                "Некорректный ИД сети: %r. Примеры: 192.168.1, "
                "10.0.0.0/16, 2001:db8::/32." % network)
        if net.version == 4:
            if net.prefixlen % 8 != 0 or net.prefixlen == 0:
                raise DnsBackendError(
                    "Для обратной зоны IPv4 маска должна быть /8, /16 или /24.")
            octets = str(net.network_address).split(".")[: net.prefixlen // 8]
            return ".".join(reversed(octets)) + ".in-addr.arpa"
        # IPv6
        if net.prefixlen % 4 != 0 or net.prefixlen == 0:
            raise DnsBackendError(
                "Для обратной зоны IPv6 длина префикса должна быть кратна 4.")
        nibbles = net.network_address.exploded.replace(":", "")
        count = net.prefixlen // 4
        return ".".join(reversed(nibbles[:count])) + ".ip6.arpa"

    # Форма '192.168.1' — первые октеты сети IPv4
    parts = network.split(".")
    if not 1 <= len(parts) <= 3 or not all(
            p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        raise DnsBackendError(
            "Укажите ИД сети в виде «192.168.1», «10.0.0.0/16» или готовое имя "
            "зоны «1.168.192.in-addr.arpa».")
    return ".".join(reversed(parts)) + ".in-addr.arpa"


def is_reverse_zone(zone_name):
    z = zone_name.lower()
    return z.endswith(".in-addr.arpa") or z.endswith(".ip6.arpa")


def ptr_relative_name(ip_text, zone_name):
    """
    По IP-адресу и имени обратной зоны возвращает относительное имя PTR-записи.
    Например: ('192.168.1.10', '1.168.192.in-addr.arpa') -> '10'.
    Если ip_text не является полным IP — возвращается как есть.
    """
    try:
        addr = ipaddress.ip_address(ip_text.strip())
    except ValueError:
        return ip_text.strip()
    rev = addr.reverse_pointer  # например '10.1.168.192.in-addr.arpa'
    suffix = "." + zone_name.lower().rstrip(".")
    if rev.lower().endswith(suffix):
        return rev[: -len(suffix)]
    raise DnsBackendError(
        "IP-адрес %s не принадлежит зоне %s." % (ip_text, zone_name))


def validate_name(name):
    """Проверка относительного имени записи ('@' допускается)."""
    if name in ("@", ""):
        return "@"
    if not re.fullmatch(r"[A-Za-z0-9а-яА-ЯёЁ_\-.]{1,255}", name):
        raise DnsBackendError("Недопустимое имя записи: %r" % name)
    return name


def _validate_fqdn(value, what):
    value = value.strip().rstrip(".")
    if not value or not re.fullmatch(r"[A-Za-z0-9а-яА-ЯёЁ_\-.]{1,255}", value):
        raise DnsBackendError("Укажите корректное FQDN: %s." % what)
    return value


def _validate_int(value, what, lo=0, hi=65535):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise DnsBackendError("Поле «%s» должно быть числом." % what)
    if not lo <= n <= hi:
        raise DnsBackendError("Поле «%s»: значение от %d до %d." % (what, lo, hi))
    return n


def build_record(rtype, fields, ttl):
    """
    Создаёт объект DNS_RPC_RECORD по типу и полям из диалога.

    fields — словарь, состав зависит от типа (см. dialogs.py).
    """
    ttl = _validate_int(ttl, "TTL", 0, 2 ** 31 - 1)
    if rtype == "A":
        try:
            ip = str(ipaddress.IPv4Address(fields["ip"].strip()))
        except ValueError:
            raise DnsBackendError("Некорректный IPv4-адрес.")
        return ARecord(ip, ttl=ttl)
    if rtype == "AAAA":
        try:
            ip = str(ipaddress.IPv6Address(fields["ip"].strip()))
        except ValueError:
            raise DnsBackendError("Некорректный IPv6-адрес.")
        return AAAARecord(ip, ttl=ttl)
    if rtype == "CNAME":
        return CNAMERecord(
            _validate_fqdn(fields["target"], "целевой узел"), ttl=ttl)
    if rtype == "MX":
        return MXRecord(
            _validate_fqdn(fields["exchange"], "почтовый сервер"),
            _validate_int(fields["preference"], "Приоритет"), ttl=ttl)
    if rtype == "PTR":
        return PTRRecord(_validate_fqdn(fields["host"], "имя узла"), ttl=ttl)
    if rtype == "NS":
        return NSRecord(_validate_fqdn(fields["host"], "сервер имён"), ttl=ttl)
    if rtype == "SRV":
        return SRVRecord(
            _validate_fqdn(fields["target"], "узел службы"),
            _validate_int(fields["port"], "Порт", 1, 65535),
            priority=_validate_int(fields["priority"], "Приоритет"),
            weight=_validate_int(fields["weight"], "Вес"),
            ttl=ttl)
    if rtype == "TXT":
        text = fields["text"]
        if '"' in text:
            parts = re.findall(r'"([^"]*)"', text) or [text]
        else:
            parts = [text]
        if not any(parts):
            raise DnsBackendError("Текст TXT-записи не может быть пустым.")
        return TXTRecord(parts, ttl=ttl)
    raise DnsBackendError("Тип записи %s не поддерживается." % rtype)


def record_display_data(rec):
    """Строка с данными записи для колонки «Данные»."""
    t, d = rec.wType, rec.data
    if t in (dnsp.DNS_TYPE_A, dnsp.DNS_TYPE_AAAA):
        return str(d)
    if t in (dnsp.DNS_TYPE_CNAME, dnsp.DNS_TYPE_NS, dnsp.DNS_TYPE_PTR):
        return d.str
    if t == dnsp.DNS_TYPE_MX:
        return "[%d] %s" % (d.wPreference, d.nameExchange.str)
    if t == dnsp.DNS_TYPE_SRV:
        return "[%d][%d][%d] %s" % (
            d.wPriority, d.wWeight, d.wPort, d.nameTarget.str)
    if t == dnsp.DNS_TYPE_TXT:
        return " ".join('"%s"' % s.str for s in d.str)
    if t == dnsp.DNS_TYPE_SOA:
        return ("[%d], основной сервер: %s, ответственный: %s" %
                (d.dwSerialNo, d.NamePrimaryServer.str,
                 d.ZoneAdministratorEmail.str))
    return "<данные типа 0x%x>" % t


def record_fields(rec):
    """Словарь полей записи — для подстановки в диалог редактирования."""
    t, d = rec.wType, rec.data
    if t in (dnsp.DNS_TYPE_A, dnsp.DNS_TYPE_AAAA):
        return {"ip": str(d)}
    if t == dnsp.DNS_TYPE_CNAME:
        return {"target": d.str}
    if t in (dnsp.DNS_TYPE_NS, dnsp.DNS_TYPE_PTR):
        return {"host": d.str}
    if t == dnsp.DNS_TYPE_MX:
        return {"preference": d.wPreference, "exchange": d.nameExchange.str}
    if t == dnsp.DNS_TYPE_SRV:
        return {"priority": d.wPriority, "weight": d.wWeight,
                "port": d.wPort, "target": d.nameTarget.str}
    if t == dnsp.DNS_TYPE_TXT:
        return {"text": " ".join('"%s"' % s.str for s in d.str)}
    return {}


class DnsBackend:
    """Подключение к DNS-серверу Samba DC и операции над зонами/записями."""

    def __init__(self):
        self.dns_conn = None
        self.server = None

    # ------------------------------------------------------------------
    # Подключение
    # ------------------------------------------------------------------
    def connect(self, server, username, password):
        server = server.strip()
        if not server:
            raise DnsBackendError("Не указано имя сервера.")
        lp = param.LoadParm()
        try:
            lp.load_default()
        except Exception:
            # smb.conf может отсутствовать на клиентской машине — не критично
            pass
        creds = credentials.Credentials()
        creds.guess(lp)
        if username.strip():
            # Поддерживает формы: user, DOMAIN\user, user@realm
            creds.parse_string(username.strip())
        creds.set_password(password)

        binding = "ncacn_ip_tcp:%s[sign]" % server
        try:
            self.dns_conn = dnsserver.dnsserver(binding, lp, creds)
        except RuntimeError as e:
            self.dns_conn = None
            raise DnsBackendError(friendly_error(e))
        self.server = server
        # Проверочный запрос — сразу убеждаемся, что доступ есть
        try:
            self.list_zones()
        except RuntimeError as e:
            self.dns_conn = None
            raise DnsBackendError(friendly_error(e))
        return True

    def disconnect(self):
        self.dns_conn = None
        self.server = None

    @property
    def connected(self):
        return self.dns_conn is not None

    def _check(self):
        if not self.connected:
            raise DnsBackendError("Нет подключения к серверу.")

    # ------------------------------------------------------------------
    # Зоны
    # ------------------------------------------------------------------
    def list_zones(self):
        """Возвращает (forward_zones, reverse_zones) — списки имён зон."""
        self._check()
        request_filter = dnsserver.DNS_ZONE_REQUEST_PRIMARY
        _typeid, res = self.dns_conn.DnssrvComplexOperation2(
            CLIENT_VERSION, 0, self.server, None,
            "EnumZones", dnsserver.DNSSRV_TYPEID_DWORD, request_filter)
        forward, reverse = [], []
        if res is not None:
            for i in range(res.dwZoneCount):
                name = res.ZoneArray[i].pszZoneName
                # Служебные псевдозоны не показываем
                if name in ("TrustAnchors", "RootDNSServers", ".."):
                    continue
                (reverse if is_reverse_zone(name) else forward).append(name)
        forward.sort()
        reverse.sort()
        return forward, reverse

    def create_zone(self, zone_name):
        """Создаёт основную зону, интегрированную в AD."""
        self._check()
        zone_name = zone_name.strip().rstrip(".").lower()
        if not zone_name or not re.fullmatch(
                r"[A-Za-z0-9а-яА-ЯёЁ_\-.]{1,255}", zone_name):
            raise DnsBackendError("Недопустимое имя зоны: %r" % zone_name)
        info = dnsserver.DNS_RPC_ZONE_CREATE_INFO_LONGHORN()
        info.pszZoneName = zone_name
        info.dwZoneType = dnsp.DNS_ZONE_TYPE_PRIMARY
        info.fAging = 0
        info.fDsIntegrated = 1
        info.fLoadExisting = 1
        info.dwDpFlags = dnsserver.DNS_DP_DOMAIN_DEFAULT
        self.dns_conn.DnssrvOperation2(
            CLIENT_VERSION, 0, self.server, None, 0,
            "ZoneCreate", dnsserver.DNSSRV_TYPEID_ZONE_CREATE, info)
        return zone_name

    def delete_zone(self, zone_name):
        self._check()
        self.dns_conn.DnssrvOperation2(
            CLIENT_VERSION, 0, self.server, zone_name, 0,
            "DeleteZoneFromDs", dnsserver.DNSSRV_TYPEID_NULL, None)

    # ------------------------------------------------------------------
    # Записи
    # ------------------------------------------------------------------
    def get_records(self, zone_name):
        """
        Все записи зоны. Возвращает список словарей:
        {name, type, type_name, data, ttl, fields, raw}
        """
        self._check()
        try:
            _buflen, res = self.dns_conn.DnssrvEnumRecords2(
                CLIENT_VERSION, 0, self.server, zone_name, "@", None,
                dnsp.DNS_TYPE_ALL, dnsserver.DNS_RPC_VIEW_AUTHORITY_DATA,
                None, None)
        except RuntimeError as e:
            code = e.args[0] if e.args and isinstance(e.args[0], int) else 0
            if (code & 0xFFFF) in (9714, 9715):  # нет записей
                return []
            raise
        result = []
        if res is None:
            return result
        for node in res.rec:
            node_name = node.dnsNodeName.str or "@"
            for j in range(node.wRecordCount):
                rec = node.records[j]
                type_name = TYPE_NAMES.get(rec.wType,
                                           "TYPE%d" % rec.wType)
                result.append({
                    "name": node_name,
                    "type": rec.wType,
                    "type_name": type_name,
                    "data": record_display_data(rec),
                    "ttl": rec.dwTtlSeconds,
                    "fields": record_fields(rec),
                    "raw": rec,
                })
        return result

    def add_record(self, zone_name, name, rec):
        self._check()
        add_buf = dnsserver.DNS_RPC_RECORD_BUF()
        add_buf.rec = rec
        self.dns_conn.DnssrvUpdateRecord2(
            CLIENT_VERSION, 0, self.server, zone_name,
            validate_name(name), add_buf, None)

    def replace_record(self, zone_name, name, old_rec, new_rec):
        """Изменение записи: старая версия удаляется, новая добавляется."""
        self._check()
        add_buf = dnsserver.DNS_RPC_RECORD_BUF()
        add_buf.rec = new_rec
        del_buf = dnsserver.DNS_RPC_RECORD_BUF()
        del_buf.rec = old_rec
        self.dns_conn.DnssrvUpdateRecord2(
            CLIENT_VERSION, 0, self.server, zone_name,
            validate_name(name), add_buf, del_buf)

    def delete_record(self, zone_name, name, rec):
        self._check()
        del_buf = dnsserver.DNS_RPC_RECORD_BUF()
        del_buf.rec = rec
        self.dns_conn.DnssrvUpdateRecord2(
            CLIENT_VERSION, 0, self.server, zone_name,
            validate_name(name), None, del_buf)

    # ------------------------------------------------------------------
    # Вспомогательное: автосоздание PTR для A-записи
    # ------------------------------------------------------------------
    def add_ptr_for_a(self, ip_text, host_fqdn, reverse_zones, ttl):
        """
        Создаёт PTR-запись для IP в подходящей обратной зоне.
        Возвращает имя зоны или None, если подходящей зоны нет.
        """
        addr = ipaddress.ip_address(ip_text)
        rev = addr.reverse_pointer.lower()
        best = None
        for z in reverse_zones:
            zl = z.lower().rstrip(".")
            if rev.endswith("." + zl) and (best is None or len(zl) > len(best)):
                best = zl
        if best is None:
            return None
        rel = rev[: -(len(best) + 1)]
        rec = build_record("PTR", {"host": host_fqdn}, ttl)
        self.add_record(best, rel, rec)
        return best
