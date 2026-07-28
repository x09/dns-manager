# -*- coding: utf-8 -*-
"""
Модель данных TUI-интерфейса: состояние серверов и плоское представление
дерева «серверы → группы зон → зоны → папки».

Модуль намеренно не зависит от urwid — логика тестируется отдельно.
Идентификаторы узлов совпадают по формату с GUI-версией:
    srv|<addr>                — сервер
    fwd|<addr> / rev|<addr>   — группы зон
    zone|<addr>|<zone>        — зона
    node|<addr>|<zone>|<path> — папка внутри зоны
"""


class ServerState:
    """Состояние одного подключённого сервера (аналог GUI-версии)."""

    def __init__(self, backend_obj, username, kerberos):
        self.backend = backend_obj
        self.username = username
        self.kerberos = kerberos
        self.forward = []
        self.reverse = []


def parse_iid(iid):
    """Разбирает идентификатор узла. Возвращает dict или None."""
    if not iid:
        return None
    if iid.startswith("srv|"):
        return {"kind": "server", "server": iid[4:], "zone": None, "path": ""}
    if iid.startswith("fwd|") or iid.startswith("rev|"):
        return {"kind": "group", "server": iid[4:], "zone": None, "path": ""}
    if iid.startswith("zone|"):
        _, addr, zone = iid.split("|", 2)
        return {"kind": "zone", "server": addr, "zone": zone, "path": ""}
    if iid.startswith("node|"):
        _, addr, zone, path = iid.split("|", 3)
        return {"kind": "node", "server": addr, "zone": zone, "path": path}
    return None


def zone_iid(addr, zone, path=""):
    return ("node|%s|%s|%s" % (addr, zone, path) if path
            else "zone|%s|%s" % (addr, zone))


class TreeModel:
    """
    Дерево серверов/зон/папок для левой панели.

    servers        — упорядоченный dict addr -> ServerState;
    expanded       — множество раскрытых идентификаторов;
    folder_cache   — (addr, zone, path) -> list[{'name','path'}] — подпапки,
                     загруженные с сервера (лениво, через backend.get_node).
    """

    def __init__(self):
        self.servers = {}
        self.expanded = set()
        self.folder_cache = {}

    # -- изменение состояния -------------------------------------------
    def add_server(self, addr, state):
        self.servers[addr] = state
        self.expanded.update({"srv|" + addr, "fwd|" + addr, "rev|" + addr})

    def remove_server(self, addr):
        self.servers.pop(addr, None)
        self.expanded = {i for i in self.expanded
                         if parse_iid(i) is None or
                         parse_iid(i)["server"] != addr}
        self.folder_cache = {k: v for k, v in self.folder_cache.items()
                             if k[0] != addr}

    def drop_zone_cache(self, addr, zone=None):
        """Сбрасывает кэш подпапок (зоны или всего сервера)."""
        self.folder_cache = {
            k: v for k, v in self.folder_cache.items()
            if not (k[0] == addr and (zone is None or k[1] == zone))}

    def toggle(self, iid):
        """Переключает раскрытие узла; True, если узел теперь раскрыт."""
        if iid in self.expanded:
            self.expanded.discard(iid)
            return False
        self.expanded.add(iid)
        return True

    def is_expanded(self, iid):
        return iid in self.expanded

    def folders_known(self, addr, zone, path=""):
        return (addr, zone, path) in self.folder_cache

    def set_folders(self, addr, zone, path, folders):
        self.folder_cache[(addr, zone, path)] = list(folders)

    # -- плоский список для отрисовки ----------------------------------
    def flatten(self, group_labels):
        """
        Возвращает список элементов дерева сверху вниз:
            [{'iid','depth','label','kind','expandable','expanded'}, ...]

        group_labels — (метка_прямых, метка_обратных) — локализованные
        подписи групп зон (передаются снаружи, чтобы модель не звала _()).
        """
        fwd_label, rev_label = group_labels
        out = []

        def add(iid, depth, label, kind, expandable):
            out.append({
                "iid": iid, "depth": depth, "label": label, "kind": kind,
                "expandable": expandable,
                "expanded": expandable and iid in self.expanded,
            })

        def walk_folders(addr, zone, path, depth):
            for f in self.folder_cache.get((addr, zone, path), []):
                fiid = zone_iid(addr, zone, f["path"])
                add(fiid, depth, f["name"], "node", True)
                if fiid in self.expanded:
                    walk_folders(addr, zone, f["path"], depth + 1)

        for addr, st in self.servers.items():
            siid = "srv|" + addr
            who = "Kerberos" if st.kerberos else st.username
            add(siid, 0, "%s  (%s)" % (addr, who), "server", True)
            if siid not in self.expanded:
                continue
            for gid, glabel, zones in (("fwd|" + addr, fwd_label, st.forward),
                                       ("rev|" + addr, rev_label, st.reverse)):
                add(gid, 1, glabel, "group", True)
                if gid not in self.expanded:
                    continue
                for z in zones:
                    ziid = zone_iid(addr, z)
                    add(ziid, 2, z, "zone", True)
                    if ziid in self.expanded:
                        walk_folders(addr, z, "", 3)
        return out
