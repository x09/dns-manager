# -*- coding: utf-8 -*-
"""
Взаимодействие с DNS-сервером Samba DC по протоколу MS-DNSP (DCERPC).

Используются python-биндинги Samba (пакет python3-module-samba в ОС Альт).
Логика вызовов повторяет реализацию `samba-tool dns` (samba/netcmd/dns.py).

Версия 2.0: поддержка вложенных узлов зоны (папок) — служебные разделы
_sites, _tcp, _udp, DomainDnsZones, ForestDnsZones и т.д. раскрываются
и опрашиваются отдельно, как в Microsoft DNS Manager.
"""

import ipaddress
import os
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

# Понятные сообщения для кодов ошибок Win32/WERROR.
# Функция (а не словарь-константа), чтобы перевод брался в момент вызова
# после инициализации локали.
def _werror_message(code):
    return {
        5: _("err.access_denied"),
        1326: _("err.bad_credentials"),
        1722: _("err.rpc_unavailable"),
        9601: _("err.zone_absent"),
        9609: _("err.zone_exists"),
        9611: _("err.zone_bad_type"),
        9711: _("err.record_exists"),
        9714: _("err.name_absent"),
        9715: _("err.record_absent"),
    }.get(code)


class DnsBackendError(Exception):
    """Ошибка при работе с DNS-сервером (с понятным описанием)."""


def _looks_like_ip(value):
    """True, если строка — это IPv4/IPv6-адрес, а не имя хоста."""
    try:
        ipaddress.ip_address((value or "").strip())
        return True
    except ValueError:
        return False


def friendly_error(exc):
    """Преобразует исключение samba/RPC в понятное сообщение."""
    if isinstance(exc, DnsBackendError):
        return str(exc)
    text = None
    if isinstance(exc, RuntimeError) and exc.args:
        code = exc.args[0]
        if isinstance(code, int):
            # Werror может быть с установленным старшим битом (HRESULT)
            text = _werror_message(code & 0xFFFF)
        if text is None and len(exc.args) > 1:
            raw = str(exc.args[1])
            if "NT_STATUS_LOGON_FAILURE" in raw:
                text = _("err.bad_credentials")
            elif "NT_STATUS_IO_TIMEOUT" in raw or "NT_STATUS_CONNECTION" in raw:
                text = _("err.connect_timeout")
            elif "NT_STATUS_OBJECT_NAME_NOT_FOUND" in raw or "NT_STATUS_HOST_UNREACHABLE" in raw:
                text = _("err.server_unreachable")
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
                _("err.bad_netid") % network)
        if net.version == 4:
            if net.prefixlen % 8 != 0 or net.prefixlen == 0:
                raise DnsBackendError(
                    _("err.rev_ipv4_mask"))
            octets = str(net.network_address).split(".")[: net.prefixlen // 8]
            return ".".join(reversed(octets)) + ".in-addr.arpa"
        # IPv6
        if net.prefixlen % 4 != 0 or net.prefixlen == 0:
            raise DnsBackendError(
                _("err.rev_ipv6_prefix"))
        nibbles = net.network_address.exploded.replace(":", "")
        count = net.prefixlen // 4
        return ".".join(reversed(nibbles[:count])) + ".ip6.arpa"

    # Форма '192.168.1' — первые октеты сети IPv4
    parts = network.split(".")
    if not 1 <= len(parts) <= 3 or not all(
            p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        raise DnsBackendError(
            _("err.netid_form"))
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
        _("err.ip_not_in_zone") % (ip_text, zone_name))


def validate_name(name):
    """Проверка относительного имени записи ('@' допускается)."""
    if name in ("@", ""):
        return "@"
    if not re.fullmatch(r"[A-Za-z0-9а-яА-ЯёЁ_\-.]{1,255}", name):
        raise DnsBackendError(_("err.bad_record_name") % name)
    return name


def node_names(node_path, raw_name):
    """
    Нормализует имя узла из ответа сервера.

    node_path — путь опрошенного узла относительно зоны ('' — корень зоны);
    raw_name  — имя, вернувшееся в DNS_RPC_RECORDS.dnsNodeName.

    Возвращает (display, full):
      display — имя для показа, относительно опрошенного узла ('@' — сам узел);
      full    — полный путь узла относительно зоны (для RPC-операций).
    """
    name = (raw_name or "").rstrip(".")
    path = (node_path or "").rstrip(".")
    if name in ("", "@"):
        return "@", (path or "@")
    if path:
        if name.lower().endswith("." + path.lower()):
            return name[: -(len(path) + 1)], name
        return name, "%s.%s" % (name, path)
    return name, name


def full_record_name(node_path, name):
    """Полное имя записи относительно зоны по имени в текущей папке."""
    path = (node_path or "").rstrip(".")
    name = (name or "@").strip()
    if name == "@":
        return path or "@"
    return "%s.%s" % (name, path) if path else name


def _validate_fqdn(value, what):
    value = value.strip().rstrip(".")
    if not value or not re.fullmatch(r"[A-Za-z0-9а-яА-ЯёЁ_\-.]{1,255}", value):
        raise DnsBackendError(_("err.bad_fqdn") % what)
    return value


def _validate_int(value, what, lo=0, hi=65535):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise DnsBackendError(_("err.field_not_number") % what)
    if not lo <= n <= hi:
        raise DnsBackendError(_("err.field_range") % (what, lo, hi))
    return n


def build_record(rtype, fields, ttl):
    """
    Создаёт объект DNS_RPC_RECORD по типу и полям из диалога.

    fields — словарь, состав зависит от типа (см. dialogs.py).
    """
    ttl = _validate_int(ttl, _("common.ttl"), 0, 2 ** 31 - 1)
    if rtype == "A":
        try:
            ip = str(ipaddress.IPv4Address(fields["ip"].strip()))
        except ValueError:
            raise DnsBackendError(_("err.bad_ipv4"))
        return ARecord(ip, ttl=ttl)
    if rtype == "AAAA":
        try:
            ip = str(ipaddress.IPv6Address(fields["ip"].strip()))
        except ValueError:
            raise DnsBackendError(_("err.bad_ipv6"))
        return AAAARecord(ip, ttl=ttl)
    if rtype == "CNAME":
        return CNAMERecord(
            _validate_fqdn(fields["target"], _("field.target_host")), ttl=ttl)
    if rtype == "MX":
        return MXRecord(
            _validate_fqdn(fields["exchange"], _("field.mail_server")),
            _validate_int(fields["preference"], _("field.priority")), ttl=ttl)
    if rtype == "PTR":
        return PTRRecord(_validate_fqdn(fields["host"], _("field.host_name")), ttl=ttl)
    if rtype == "NS":
        return NSRecord(_validate_fqdn(fields["host"], _("field.name_server")), ttl=ttl)
    if rtype == "SRV":
        return SRVRecord(
            _validate_fqdn(fields["target"], _("field.service_host")),
            _validate_int(fields["port"], _("field.port"), 1, 65535),
            priority=_validate_int(fields["priority"], _("field.priority")),
            weight=_validate_int(fields["weight"], _("field.weight")),
            ttl=ttl)
    if rtype == "TXT":
        text = fields["text"]
        if '"' in text:
            parts = re.findall(r'"([^"]*)"', text) or [text]
        else:
            parts = [text]
        if not any(parts):
            raise DnsBackendError(_("err.txt_empty"))
        return TXTRecord(parts, ttl=ttl)
    raise DnsBackendError(_("err.rtype_unsupported") % rtype)


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
        return (_("data.soa") %
                (d.dwSerialNo, d.NamePrimaryServer.str,
                 d.ZoneAdministratorEmail.str))
    return _("data.unknown_type") % t


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
    def connect(self, server, username, password, use_kerberos=False,
                realm=""):
        """
        Подключается к DNS-серверу.

        use_kerberos=True — вход по действующему билету Kerberos (GSSAPI),
        пароль не используется; иначе — обычная проверка логина/пароля (NTLM).

        realm — Kerberos-realm (например 'TEST.ALT'). Обязателен при
        use_kerberos на машине вне домена (без настроенного smb.conf):
        Samba не берёт realm из /etc/krb5.conf для GSSAPI-бинда, и без него
        gensec отдаёт NT_STATUS_INVALID_PARAMETER. Если realm не передан,
        он определяется автоматически (из имени пользователя user@REALM или
        из FQDN сервера).
        """
        server = server.strip()
        if not server:
            raise DnsBackendError(_("err.server_name_missing"))
        lp = param.LoadParm()
        try:
            lp.load_default()
        except Exception:
            # smb.conf может отсутствовать на клиентской машине — не критично
            pass
        # Отладка: DNSMGR_DEBUG=<уровень> поднимает логирование Samba, чтобы
        # в консоль попала настоящая ошибка gensec/krb5 из-под INVALID_PARAMETER
        # (аналог `samba-tool ... -d10`).
        _debug = os.environ.get("DNSMGR_DEBUG", "").strip()
        if _debug:
            try:
                lp.set("log level", _debug if _debug.isdigit() else "10")
            except Exception:
                pass
        creds = credentials.Credentials()
        creds.guess(lp)

        target_hostname = ""
        if use_kerberos:
            # ВАЖНО: при входе по билету НЕ вызываем creds.parse_string(user)
            # и НЕ задаём пароль. Иначе Samba считает, что имя задано явно,
            # заводит пустой кэш MEMORY: и пытается сделать kinit заново
            # («No password available for kinit») вместо использования
            # готового билета. Рабочий `samba-tool dns ... --use-kerberos=
            # required` вызывается без -U именно поэтому.

            # 1) Realm — из билета/имени (creds.guess без smb.conf даёт
            #    WORKGROUP, из-за чего контекст к host/<server> не строится).
            realm = (realm or "").strip() or self._guess_realm(username, server)
            if realm:
                creds.set_realm(realm.upper())

            # 2) Имя хоста для SPN host/<FQDN>. При подключении по IP в
            #    биндинге нет target_hostname и имя из IP не вывести →
            #    NT_STATUS_INVALID_PARAMETER. Определяем FQDN контроллера.
            target_hostname = self._target_hostname(server, realm)
            if not target_hostname:
                raise DnsBackendError(
                    _("err.krb_no_fqdn") %
                    server)

            # 3) Явно привязываем существующий кэш билетов, чтобы принципал
            #    брался из самого билета, а не запрашивался заново. Имя кэша —
            #    из KRB5CCNAME или из klist (get_ccache_name), т.к. переменная
            #    окружения может быть не задана при дефолте из krb5.conf.
            try:
                from . import kerberos
                ccache = kerberos.get_ccache_name()
                if ccache:
                    creds.set_named_ccache(ccache)
            except Exception:
                # Не критично: Samba возьмёт кэш по умолчанию.
                pass

            # Использовать имеющийся билет из кэша (ncacn через GSSAPI)
            creds.set_kerberos_state(credentials.MUST_USE_KERBEROS)
        else:
            if username.strip():
                # Поддерживает формы: user, DOMAIN\user, user@realm
                creds.parse_string(username.strip())
            creds.set_kerberos_state(credentials.DONT_USE_KERBEROS)
            creds.set_password(password)

        # Уровень защиты RPC-канала:
        #   sign — только подпись (целостность),
        #   seal — подпись + шифрование (конфиденциальность).
        # Для Kerberos используем sign, как это делает штатный `samba-tool
        # dns` (netcmd/dns.py: binding "ncacn_ip_tcp:%s[sign]"). Канал seal
        # с GSSAPI на pipe dnsserver не согласуется и отдаёт
        # NT_STATUS_INVALID_PARAMETER. Для входа по паролю (NTLM) оставляем
        # seal — это привычное рабочее поведение прежних версий.
        if use_kerberos:
            opts = "sign"
            if target_hostname:
                opts += ",target_hostname=%s" % target_hostname
        else:
            opts = "seal"
        binding = "ncacn_ip_tcp:%s[%s]" % (server, opts)
        try:
            self.dns_conn = dnsserver.dnsserver(binding, lp, creds)
        except RuntimeError as e:
            self.dns_conn = None
            raise DnsBackendError(self._kerberos_error(e, use_kerberos))
        self.server = server
        # Проверочный запрос — сразу убеждаемся, что доступ есть
        try:
            self.list_zones()
        except RuntimeError as e:
            self.dns_conn = None
            raise DnsBackendError(self._kerberos_error(e, use_kerberos))
        return True

    @staticmethod
    def _kerberos_error(exc, use_kerberos):
        """
        Понятное сообщение об ошибке подключения. Отдельно распознаёт частый
        случай Kerberos + кэш KEYRING/KCM: клиентские библиотеки Samba не
        читают из них принципала, вход падает с NT_STATUS_INVALID_PARAMETER
        (хотя kinit/ldapsearch с тем же билетом работают).
        """
        msg = friendly_error(exc)
        if not use_kerberos:
            return msg
        raw = "%s %s" % (getattr(exc, "args", ""), msg)
        if "INVALID_PARAMETER" in raw.upper():
            try:
                from . import kerberos
                if kerberos.ccache_is_keyring():
                    cc = kerberos.get_ccache_name() or "KEYRING"
                    return (
                        _("err.krb_keyring") %
                        (cc, _("common.user_placeholder")))
            except Exception:
                pass
        return msg

    @staticmethod
    def _guess_realm(username, server):
        """
        Пытается определить Kerberos-realm без настроенного smb.conf.

        Порядок: имя пользователя user@REALM → realm действующего билета
        (klist) → доменная часть FQDN сервера (dc.test.alt → TEST.ALT).
        IP-адрес как источник realm не годится, поэтому пропускается.
        """
        username = (username or "").strip()
        if "@" in username:
            realm = username.split("@", 1)[1].strip()
            if realm:
                return realm.upper()
        # realm из билета в кэше
        try:
            from . import kerberos
            realm = kerberos.get_realm()
            if realm:
                return realm
        except Exception:
            pass
        # доменная часть FQDN сервера (только если это не IP)
        server = (server or "").strip().rstrip(".")
        try:
            ipaddress.ip_address(server)
            is_ip = True
        except ValueError:
            is_ip = False
        if not is_ip and "." in server:
            return server.split(".", 1)[1].upper()
        return ""

    @staticmethod
    def _target_hostname(server, realm=""):
        """
        Возвращает FQDN контроллера домена для построения SPN host/<FQDN>
        при Kerberos-подключении.

        - если server уже задан именем (не IP) — возвращается как есть
          (при наличии realm короткое имя дополняется до FQDN);
        - если server — IP-адрес, выполняется обратный DNS-поиск
          (socket.gethostbyaddr). DNS-сервер обычно и есть сам контроллер,
          поэтому PTR для него, как правило, существует.

        Пустая строка — определить FQDN не удалось.
        """
        import socket

        server = (server or "").strip().rstrip(".")
        realm = (realm or "").strip().rstrip(".").lower()
        try:
            ipaddress.ip_address(server)
            is_ip = True
        except ValueError:
            is_ip = False

        if not is_ip:
            # Уже имя. Если оно короткое, а realm известен — дополним до FQDN.
            if "." not in server and realm:
                return "%s.%s" % (server, realm)
            return server

        # server — IP-адрес: обратный DNS
        try:
            name = socket.gethostbyaddr(server)[0].rstrip(".")
        except (OSError, socket.error):
            name = ""
        if name and not _looks_like_ip(name):
            if "." not in name and realm:
                return "%s.%s" % (name, realm)
            return name
        return ""

    def disconnect(self):
        self.dns_conn = None
        self.server = None

    @property
    def connected(self):
        return self.dns_conn is not None

    def _check(self):
        if not self.connected:
            raise DnsBackendError(_("err.not_connected"))

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
            raise DnsBackendError(_("err.bad_zone_name") % zone_name)
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
    # Узлы и записи
    # ------------------------------------------------------------------
    def get_node(self, zone_name, node_path=""):
        """
        Записи и дочерние папки узла зоны.

        node_path — путь узла относительно зоны ('' — корень зоны),
        например 'site1._sites.DomainDnsZones'.

        Возвращает словарь:
          {'records': [...], 'folders': [{'name': ..., 'path': ...}, ...]}

        records — записи самого узла и его непосредственных потомков;
        folders — потомки, у которых есть собственные дочерние узлы
                  (служебные разделы _sites, _tcp и т.п.).
        """
        self._check()
        query_name = node_path or "@"
        try:
            _buflen, res = self.dns_conn.DnssrvEnumRecords2(
                CLIENT_VERSION, 0, self.server, zone_name, query_name, None,
                dnsp.DNS_TYPE_ALL, dnsserver.DNS_RPC_VIEW_AUTHORITY_DATA,
                None, None)
        except RuntimeError as e:
            code = e.args[0] if e.args and isinstance(e.args[0], int) else 0
            if (code & 0xFFFF) in (9714, 9715):  # нет записей
                return {"records": [], "folders": []}
            raise
        records, folders = [], []
        if res is None:
            return {"records": records, "folders": folders}
        for node in res.rec:
            display, full = node_names(node_path, node.dnsNodeName.str)
            child_count = getattr(node, "dwChildCount", 0)
            if child_count and display != "@":
                folders.append({"name": display, "path": full})
            for j in range(node.wRecordCount):
                rec = node.records[j]
                type_name = TYPE_NAMES.get(rec.wType, "TYPE%d" % rec.wType)
                records.append({
                    "name": display,        # имя в текущей папке ('@' — узел)
                    "full_name": full,      # полный путь относительно зоны
                    "type": rec.wType,
                    "type_name": type_name,
                    "data": record_display_data(rec),
                    "ttl": rec.dwTtlSeconds,
                    "fields": record_fields(rec),
                    "raw": rec,
                })
        folders.sort(key=lambda f: f["name"].lower())
        return {"records": records, "folders": folders}

    def add_record(self, zone_name, name, rec):
        """name — полное имя относительно зоны (или '@')."""
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
