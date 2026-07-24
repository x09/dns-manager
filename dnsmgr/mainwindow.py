# -*- coding: utf-8 -*-
"""
Главное окно DNS Manager (в стиле Microsoft DNS Manager).

Версия 3.2:
  * пиктограммы записей в правой панели: обычная запись, папка,
    запись «только чтение» (NS, SOA);
  * имя сервера в дереве выделено жирным шрифтом.

Версия 3.0:
  * несколько серверов одновременно — каждый отдельный узел в дереве;
  * вход по логину/паролю или по билету Kerberos (GSSAPI);
  * список серверов хранится в ~/.config/dns-manager/dns-manager.ini;
  * пиктограммы на кнопках панели инструментов.
"""

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from . import backend, config, i18n, icons
from .backend import DnsBackend, friendly_error
from .dialogs import (
    DeleteConfirmDialog, RecordDialog, ServerChooserDialog, ZoneDialog)

def APP_TITLE():
    return _("app.title")


def PARENT_LABEL():
    return _("common.parent_label")


class ServerState:
    """UI-состояние одного подключённого сервера."""
    def __init__(self, backend_obj, username, kerberos):
        self.backend = backend_obj
        self.username = username
        self.kerberos = kerberos
        self.forward = []
        self.reverse = []
        self.zone = None       # выбранная зона
        self.path = ""         # путь папки внутри зоны
        self.records = []
        self.folders = []


class MainWindow:
    def __init__(self, root):
        self.root = root
        self.servers = {}          # addr -> ServerState
        self.active = None         # адрес активного (выбранного) сервера
        self._task_queue = queue.Queue()
        self._busy = False
        self._sort_state = {}

        root.title(APP_TITLE())
        root.geometry("1040x660")
        root.minsize(780, 460)

        self._load_icons()
        self._build_menu()
        self._build_toolbar()
        self._build_panes()
        self._build_statusbar()
        self._update_actions()

        root.after(200, self._startup)

    # ==================================================================
    def _load_icons(self):
        self.icon = {n: icons.get(n) for n in (
            "connect", "refresh", "newzone", "delzone",
            "newrec", "delrec", "editrec",
            "rec16", "folder16", "lock16")}

    # ==================================================================
    # Интерфейс
    # ==================================================================
    def _build_menu(self):
        menubar = tk.Menu(self.root)
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label=_("menu.connect"),
                           command=self.action_connect)
        m_file.add_command(label=_("menu.disconnect"),
                           command=self.action_disconnect)
        m_file.add_separator()
        m_file.add_command(label=_("menu.exit"), command=self.root.destroy)
        menubar.add_cascade(label=_("menu.file"), menu=m_file)

        m_action = tk.Menu(menubar, tearoff=0)
        m_action.add_command(label=_("menu.refresh"), accelerator="F5",
                             command=self.action_refresh)
        m_action.add_separator()
        m_action.add_command(label=_("menu.new_zone"), command=self.action_new_zone)
        m_action.add_command(label=_("menu.delete_zone"), command=self.action_delete_zone)
        m_action.add_separator()
        m_action.add_command(label=_("menu.new_record"), command=self.action_new_record)
        m_action.add_command(label=_("menu.edit_record"), command=self.action_edit_record)
        m_action.add_command(label=_("menu.delete_record"), command=self.action_delete_record)
        menubar.add_cascade(label=_("menu.action"), menu=m_action)

        m_help = tk.Menu(menubar, tearoff=0)
        # Подменю выбора языка интерфейса
        m_lang = tk.Menu(m_help, tearoff=0)
        self._lang_var = tk.StringVar(value=i18n.current_language())
        for code, name in i18n.available_languages():
            m_lang.add_radiobutton(
                label=name, value=code, variable=self._lang_var,
                command=lambda c=code: self._on_language_selected(c))
        m_help.add_cascade(label=_("menu.language"), menu=m_lang)
        m_help.add_separator()
        m_help.add_command(label=_("menu.about"), command=self._about)
        menubar.add_cascade(label=_("menu.help"), menu=m_help)
        self.root.config(menu=menubar)
        self.root.bind("<F5>", lambda e: self.action_refresh())
        self.root.bind("<Delete>", lambda e: self._on_delete_key())

    def _on_language_selected(self, code):
        """Сохраняет выбранный язык и предлагает перезапуск."""
        if code == i18n.current_language():
            return
        config.save_language(code)
        i18n.set_language(code)
        messagebox.showinfo(
            _("menu.language"),
            _("msg.language_changed"),
            parent=self.root)

    def _tbutton(self, bar, name, text, cmd):
        img = self.icon.get(name)
        kw = dict(text=text, command=cmd)
        if img is not None:
            kw.update(image=img, compound="left")
        b = ttk.Button(bar, **kw)
        return b

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(6, 4))
        bar.pack(side="top", fill="x")
        self.btn_connect = self._tbutton(bar, "connect", " " + _("btn.connect"), self.action_connect)
        self.btn_refresh = self._tbutton(bar, "refresh", " " + _("menu.refresh"), self.action_refresh)
        self.btn_new_zone = self._tbutton(bar, "newzone", " " + _("btn.new_zone"), self.action_new_zone)
        self.btn_del_zone = self._tbutton(bar, "delzone", " " + _("menu.delete_zone"), self.action_delete_zone)
        self.btn_new_rec = self._tbutton(bar, "newrec", " " + _("btn.new_record"), self.action_new_record)
        self.btn_edit_rec = self._tbutton(bar, "editrec", " " + _("btn.edit_record"), self.action_edit_record)
        self.btn_del_rec = self._tbutton(bar, "delrec", " " + _("menu.delete_record"), self.action_delete_record)
        for i, b in enumerate((self.btn_connect, self.btn_refresh, self.btn_new_zone,
                               self.btn_del_zone, self.btn_new_rec,
                               self.btn_edit_rec, self.btn_del_rec)):
            b.grid(row=0, column=i, padx=2)

    def _build_panes(self):
        panes = ttk.PanedWindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        left = ttk.Frame(panes)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        ts = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ts.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ts.pack(side="right", fill="y")
        panes.add(left, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<Button-3>", self._tree_context_menu)

        # Жирный шрифт для имени сервера в дереве
        base_font = tkfont.nametofont("TkDefaultFont")
        self._bold_font = base_font.copy()
        self._bold_font.configure(weight="bold")
        self.tree.tag_configure("server", font=self._bold_font)

        right = ttk.Frame(panes)
        # Колонка #0 («дерево») показывает пиктограмму и имя записи
        cols = ("type", "data", "ttl")
        self.records = ttk.Treeview(right, columns=cols, show="tree headings",
                                    selectmode="extended")
        self.records.heading("#0", text=_("col.name"),
                             command=lambda: self._sort_records("name"))
        self.records.heading("type", text=_("col.type"), command=lambda: self._sort_records("type_name"))
        self.records.heading("data", text=_("col.data"), command=lambda: self._sort_records("data"))
        self.records.heading("ttl", text=_("common.ttl"), command=lambda: self._sort_records("ttl"))
        self.records.column("#0", width=260, anchor="w")
        self.records.column("type", width=70, anchor="w", stretch=False)
        self.records.column("data", width=430, anchor="w")
        self.records.column("ttl", width=70, anchor="e", stretch=False)
        rs = ttk.Scrollbar(right, orient="vertical", command=self.records.yview)
        self.records.configure(yscrollcommand=rs.set)
        self.records.pack(side="left", fill="both", expand=True)
        rs.pack(side="right", fill="y")
        panes.add(right, weight=3)
        self.records.bind("<Double-1>", self._on_records_double_click)
        self.records.bind("<Button-3>", self._records_context_menu)
        self.records.bind("<<TreeviewSelect>>", lambda e: self._update_actions())

    def _build_statusbar(self):
        self.status_var = tk.StringVar(value=_("status.no_connections"))
        bar = ttk.Frame(self.root)
        bar.pack(side="bottom", fill="x")
        ttk.Separator(bar).pack(fill="x")
        ttk.Label(bar, textvariable=self.status_var, padding=(8, 3)).pack(side="left")

    # ==================================================================
    # Идентификаторы дерева
    #   srv|<addr>                          — сервер
    #   fwd|<addr> / rev|<addr>             — группы зон
    #   zone|<addr>|<zone>                  — зона
    #   node|<addr>|<zone>|<path>           — папка внутри зоны
    #   <parent>|dummy                      — заглушка для ленивой загрузки
    # ==================================================================
    @staticmethod
    def _zone_iid(addr, zone, path=""):
        return ("node|%s|%s|%s" % (addr, zone, path) if path
                else "zone|%s|%s" % (addr, zone))

    def _parse_iid(self, iid):
        """Возвращает dict {'kind','server','zone','path'} или None."""
        if not iid or iid.endswith("|dummy"):
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

    def _add_dummy(self, parent_iid):
        self.tree.insert(parent_iid, "end", iid=parent_iid + "|dummy", text="...")

    # ==================================================================
    # Асинхронность
    # ==================================================================
    def run_async(self, work, on_done=None, status=None):
        if status is None:
            status = _("status.working")
        if self._busy:
            return False
        self._set_busy(True, status)

        def worker():
            try:
                result, error = work(), None
            except Exception as e:  # noqa: BLE001
                result, error = None, e
            self._task_queue.put((error, result, on_done))
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(50, self._poll_queue)
        return True

    def _poll_queue(self):
        try:
            error, result, on_done = self._task_queue.get_nowait()
        except queue.Empty:
            self.root.after(50, self._poll_queue)
            return
        self._set_busy(False)
        if error is not None:
            messagebox.showerror(_("title.error"), friendly_error(error), parent=self.root)
            self._update_status()
        elif on_done:
            on_done(result)

    def _set_busy(self, busy, status=None):
        self._busy = busy
        self.root.config(cursor="watch" if busy else "")
        if status:
            self.status_var.set(status)
        self._update_actions()

    # ==================================================================
    # Запуск и подключение
    # ==================================================================
    def _startup(self):
        self.action_connect(startup=True)

    def action_connect(self, startup=False, preselect=None):
        if self._busy:
            return
        saved = config.load_servers()
        dlg = ServerChooserDialog(self.root, saved_servers=saved, preselect=preselect)
        if dlg.result is None:
            return
        self._do_connect(dlg.result)

    def _do_connect(self, spec):
        addr = spec["server"]
        if addr in self.servers:
            messagebox.showinfo(_("title.connection"),
                                _("msg.already_connected") % addr, parent=self.root)
            self._select_server(addr)
            return
        be = DnsBackend()

        def work():
            be.connect(spec["server"], spec["username"],
                       spec["password"], use_kerberos=spec["kerberos"],
                       realm=spec.get("realm", ""))
            return be.list_zones()

        def done(zones):
            st = ServerState(be, spec["username"], spec["kerberos"])
            st.forward, st.reverse = zones
            self.servers[addr] = st
            config.save_server(addr, spec["username"], spec["kerberos"],
                               spec.get("realm", ""))
            self._add_server_node(addr)
            self._select_server(addr)
            self._update_status()

        self.run_async(work, done, _("status.connecting") % addr)

    def _add_server_node(self, addr):
        iid = "srv|" + addr
        st = self.servers[addr]
        label = "%s  (%s)" % (addr, _("common.kerberos") if st.kerberos else st.username)
        if self.tree.exists(iid):
            self.tree.delete(iid)
        self.tree.insert("", "end", iid=iid, text=label, open=True,
                         tags=("server",))
        self.tree.insert(iid, "end", iid="fwd|" + addr,
                         text=_("tree.forward_zones"), open=True)
        self.tree.insert(iid, "end", iid="rev|" + addr,
                         text=_("tree.reverse_zones"), open=True)
        for z in st.forward:
            ziid = self._zone_iid(addr, z)
            self.tree.insert("fwd|" + addr, "end", iid=ziid, text=z)
            self._add_dummy(ziid)
        for z in st.reverse:
            ziid = self._zone_iid(addr, z)
            self.tree.insert("rev|" + addr, "end", iid=ziid, text=z)
            self._add_dummy(ziid)

    def _select_server(self, addr):
        iid = "srv|" + addr
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def action_disconnect(self):
        addr = self.active
        if not addr or addr not in self.servers:
            messagebox.showinfo(_("title.disconnect"),
                                _("msg.select_connected_server"),
                                parent=self.root)
            return
        if not messagebox.askyesno(
                _("title.disconnect"), _("msg.disconnect_confirm") % addr,
                parent=self.root):
            return
        self.servers[addr].backend.disconnect()
        del self.servers[addr]
        if self.tree.exists("srv|" + addr):
            self.tree.delete("srv|" + addr)
        self.active = None
        self.records.delete(*self.records.get_children())
        self._update_status()

    # ==================================================================
    # Зоны
    # ==================================================================
    def _active_state(self):
        return self.servers.get(self.active)

    def action_refresh(self):
        st = self._active_state()
        if st is None or self._busy:
            return
        addr = self.active
        zone = st.zone
        be = st.backend

        def work():
            zones = be.list_zones()
            node = be.get_node(zone, "") if zone and zone in zones[0] + zones[1] else None
            return zones, node

        def done(result):
            zones, node = result
            if addr not in self.servers:
                return
            st.forward, st.reverse = zones
            self._refresh_zone_nodes(addr)
            if node is not None and st.zone == zone:
                st.path = ""
                self._apply_node(addr, zone, "", node)
            self._update_status()

        self.run_async(work, done, _("status.refreshing"))

    def _refresh_zone_nodes(self, addr):
        st = self.servers[addr]
        for group, zones in (("fwd", st.forward), ("rev", st.reverse)):
            gid = group + "|" + addr
            if not self.tree.exists(gid):
                continue
            have = {self.tree.item(c, "text"): c for c in self.tree.get_children(gid)}
            for z in zones:
                if z not in have:
                    ziid = self._zone_iid(addr, z)
                    if not self.tree.exists(ziid):
                        self.tree.insert(gid, "end", iid=ziid, text=z)
                        self._add_dummy(ziid)
            for text, cid in have.items():
                if text not in zones:
                    self.tree.delete(cid)

    def action_new_zone(self):
        st = self._active_state()
        if st is None:
            self._need_server()
            return
        sel = self.tree.selection()
        info = self._parse_iid(sel[0]) if sel else None
        in_rev = bool(info and (
            (info["kind"] == "group" and sel[0].startswith("rev|")) or
            (info["zone"] and backend.is_reverse_zone(info["zone"]))))
        dlg = ZoneDialog(self.root, "reverse" if in_rev else "forward")
        if dlg.result is None:
            return
        zone = dlg.result["zone"]
        addr = self.active
        be = st.backend

        def work():
            be.create_zone(zone)
            return be.list_zones()

        def done(zones):
            if addr not in self.servers:
                return
            st.forward, st.reverse = zones
            self._refresh_zone_nodes(addr)
            ziid = self._zone_iid(addr, zone)
            if self.tree.exists(ziid):
                self.tree.selection_set(ziid)
                self.tree.see(ziid)
            self._update_status()

        self.run_async(work, done, _("status.creating_zone") % zone)

    def action_delete_zone(self):
        st = self._active_state()
        sel = self.tree.selection()
        info = self._parse_iid(sel[0]) if sel else None
        if st is None or not info or info["kind"] != "zone":
            messagebox.showinfo(_("title.delete_zone"),
                                _("msg.select_zone"),
                                parent=self.root)
            return
        zone = info["zone"]; addr = self.active; be = st.backend
        if not messagebox.askyesno(
                _("title.delete_zone"),
                _("msg.delete_zone_confirm") % (zone, addr),
                icon="warning", parent=self.root):
            return

        def work():
            be.delete_zone(zone)
            return be.list_zones()

        def done(zones):
            if addr not in self.servers:
                return
            st.forward, st.reverse = zones
            st.zone, st.path = None, ""
            self._refresh_zone_nodes(addr)
            self.records.delete(*self.records.get_children())
            self._select_server(addr)
            self._update_status()

        self.run_async(work, done, _("status.deleting_zone") % zone)

    # ==================================================================
    # Узлы (папки) и записи
    # ==================================================================
    def _load_node(self, addr, zone, path):
        be = self.servers[addr].backend

        def work():
            return be.get_node(zone, path)

        def done(node):
            st = self.servers.get(addr)
            if st and (st.zone, st.path) == (zone, path):
                self._apply_node(addr, zone, path, node)
        where = "%s/%s" % (zone, path) if path else zone
        self.run_async(work, done, _("status.loading_where") % where)

    def _apply_node(self, addr, zone, path, node):
        st = self.servers.get(addr)
        if st is None:
            return

        def sort_key(r):
            return (r["name"] != "@", r["name"].lower(), r["type_name"])
        st.records = sorted(node["records"], key=sort_key)
        st.folders = node["folders"]
        self._sort_state = {}
        self._fill_records_pane()
        self._update_tree_children(addr, zone, path, node["folders"])
        self._update_status()

    def _fill_records_pane(self):
        st = self._active_state()
        self.records.delete(*self.records.get_children())
        if st is None:
            return
        for f in st.folders:
            self.records.insert("", "end", iid="folder|" + f["path"],
                                text=" " + f["name"],
                                image=self.icon.get("folder16") or "",
                                values=("", _("tree.folder_marker"), ""))
        for idx, r in enumerate(st.records):
            name = PARENT_LABEL() if r["name"] == "@" else r["name"]
            editable = r["type_name"] in backend.EDITABLE_TYPES
            img = self.icon.get("rec16" if editable else "lock16") or ""
            self.records.insert("", "end", iid=str(idx),
                                text=" " + name, image=img,
                                values=(r["type_name"], r["data"], r["ttl"]))

    def _update_tree_children(self, addr, zone, path, folders):
        parent = self._zone_iid(addr, zone, path)
        if not self.tree.exists(parent):
            return
        wanted = [("node|%s|%s|%s" % (addr, zone, f["path"]), f["name"])
                  for f in folders]
        wanted_ids = {iid for iid, _n in wanted}
        for child in self.tree.get_children(parent):
            if child not in wanted_ids:
                self.tree.delete(child)
        for pos, (iid, name) in enumerate(wanted):
            if self.tree.exists(iid):
                self.tree.move(iid, parent, pos)
            else:
                self.tree.insert(parent, pos, iid=iid, text=name)
                self._add_dummy(iid)

    def _sort_records(self, key):
        st = self._active_state()
        if st is None or not st.records:
            return
        rev = self._sort_state.get(key, False)
        st.records.sort(key=lambda r: (str(r.get(key, "")).lower()
                                       if key != "ttl" else r["ttl"]), reverse=rev)
        self._sort_state[key] = not rev
        self._fill_records_pane()

    def action_new_record(self):
        st = self._active_state()
        if st is None:
            self._need_server()
            return
        if not st.zone:
            messagebox.showinfo(_("title.new_record"), _("msg.select_zone_first"),
                                parent=self.root)
            return
        addr, zone, path, be = self.active, st.zone, st.path, st.backend
        dlg = RecordDialog(self.root, zone, backend.is_reverse_zone(zone), folder=path)
        if dlg.result is None:
            return
        res = dlg.result
        full_name = backend.full_record_name(path, res["name"])

        def work():
            be.add_record(zone, full_name, res["record"])
            warn = None
            if res["make_ptr"]:
                host_fqdn = zone if full_name == "@" else "%s.%s" % (full_name, zone)
                try:
                    created = be.add_ptr_for_a(res["fields"]["ip"], host_fqdn,
                                               st.reverse, res["ttl"])
                    if created is None:
                        warn = (_("msg.ptr_no_zone") % res["fields"]["ip"])
                except Exception as e:  # noqa: BLE001
                    warn = _("msg.ptr_failed") % friendly_error(e)
            return be.get_node(zone, path), warn

        def done(result):
            node, warn = result
            cur = self.servers.get(addr)
            if cur and (cur.zone, cur.path) == (zone, path):
                self._apply_node(addr, zone, path, node)
            if warn:
                messagebox.showwarning(_("title.ptr"), warn, parent=self.root)

        self.run_async(work, done, _("status.creating_record"))

    def action_edit_record(self):
        st = self._active_state()
        rec = self._selected_record()
        if st is None or rec is None:
            return
        if rec["type_name"] not in backend.EDITABLE_TYPES:
            messagebox.showinfo(_("title.edit_record"),
                                _("msg.record_not_editable") % rec["type_name"],
                                parent=self.root)
            return
        addr, zone, path, be = self.active, st.zone, st.path, st.backend
        dlg = RecordDialog(self.root, zone, backend.is_reverse_zone(zone),
                           record=rec, folder=path)
        if dlg.result is None:
            return
        res = dlg.result

        def work():
            be.replace_record(zone, rec["full_name"], rec["raw"], res["record"])
            return be.get_node(zone, path)

        def done(node):
            cur = self.servers.get(addr)
            if cur and (cur.zone, cur.path) == (zone, path):
                self._apply_node(addr, zone, path, node)

        self.run_async(work, done, _("status.editing_record"))

    def _selected_records(self):
        """
        Все выбранные в правой панели записи, годные к удалению.

        Возвращает (records, skipped): records — список записей обычных типов
        (папки и нередактируемые NS/SOA отфильтрованы); skipped — сколько
        элементов выбора отброшено.
        """
        st = self._active_state()
        if st is None:
            return [], 0
        records, skipped = [], 0
        for iid in self.records.selection():
            if iid.startswith("folder|"):
                skipped += 1
                continue
            try:
                rec = st.records[int(iid)]
            except (ValueError, IndexError, AttributeError):
                skipped += 1
                continue
            if rec["type_name"] not in backend.EDITABLE_TYPES:
                skipped += 1  # NS/SOA и прочие нередактируемые
                continue
            records.append(rec)
        return records, skipped

    def action_delete_record(self):
        st = self._active_state()
        if st is None:
            return
        recs, skipped = self._selected_records()
        if not recs:
            if skipped:
                messagebox.showinfo(_("title.delete_record"),
                                    _("msg.nothing_deletable"),
                                    parent=self.root)
            else:
                messagebox.showinfo(_("title.records"),
                                    _("msg.select_record"), parent=self.root)
            return
        addr, zone, path, be = self.active, st.zone, st.path, st.backend

        # Список для показа (с подстановкой «родительской папки» вместо '@').
        shown = [{"name": PARENT_LABEL() if r["name"] == "@" else r["name"],
                  "type_name": r["type_name"], "data": r["data"]}
                 for r in recs]
        dlg = DeleteConfirmDialog(self.root, shown, skipped=skipped)
        if not dlg.result:
            return

        targets = [(r["full_name"], r["raw"]) for r in recs]

        def work():
            errors = []
            for full_name, raw in targets:
                try:
                    be.delete_record(zone, full_name, raw)
                except Exception as e:  # noqa: BLE001
                    errors.append(friendly_error(e))
            return be.get_node(zone, path), errors

        def done(result):
            node, errors = result
            cur = self.servers.get(addr)
            if cur and (cur.zone, cur.path) == (zone, path):
                self._apply_node(addr, zone, path, node)
            if errors:
                messagebox.showwarning(
                    _("title.delete_record"),
                    _("msg.delete_partial") % (len(errors), "\n".join(errors)),
                    parent=self.root)

        self.run_async(work, done, _("status.deleting_record"))

    # ==================================================================
    # Выбор в дереве
    # ==================================================================
    def _on_tree_select(self, _event=None):
        sel = self.tree.selection()
        info = self._parse_iid(sel[0]) if sel else None
        if info is None:
            self._update_actions()
            return
        addr = info["server"]
        self.active = addr if addr in self.servers else None
        st = self.servers.get(addr)
        if st is None:
            self._update_actions()
            return
        if info["kind"] in ("server", "group"):
            st.zone, st.path = None, ""
            self.records.delete(*self.records.get_children())
            self._update_status()
        elif info["kind"] in ("zone", "node"):
            zone, path = info["zone"], info["path"]
            if (zone, path) != (st.zone, st.path) and not self._busy:
                st.zone, st.path = zone, path
                self._load_node(addr, zone, path)
        self._update_actions()

    def _on_tree_open(self, _event=None):
        iid = self.tree.focus()
        info = self._parse_iid(iid)
        if info is None or info["kind"] not in ("zone", "node") or self._busy:
            return
        children = self.tree.get_children(iid)
        if len(children) == 1 and children[0].endswith("|dummy"):
            addr, zone, path = info["server"], info["zone"], info["path"]
            be = self.servers[addr].backend

            def work():
                return be.get_node(zone, path)

            def done(data):
                self._update_tree_children(addr, zone, path, data["folders"])
            self.run_async(work, done, _("status.loading"))

    def _selected_record(self):
        st = self._active_state()
        sel = self.records.selection()
        if not sel:
            messagebox.showinfo(_("title.records"), _("msg.select_record"), parent=self.root)
            return None
        iid = sel[0]
        if iid.startswith("folder|"):
            messagebox.showinfo(_("title.records"), _("msg.is_folder"),
                                parent=self.root)
            return None
        try:
            return st.records[int(iid)]
        except (ValueError, IndexError, AttributeError):
            return None

    def _on_records_double_click(self, event):
        iid = self.records.identify_row(event.y)
        if iid.startswith("folder|"):
            self._open_folder(iid.split("|", 1)[1])
        elif iid:
            self.action_edit_record()

    def _open_folder(self, path):
        st = self._active_state()
        if st is None or not st.zone:
            return
        iid = self._zone_iid(self.active, st.zone, path)
        if self.tree.exists(iid):
            parent = self.tree.parent(iid)
            if parent:
                self.tree.item(parent, open=True)
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def _on_delete_key(self):
        foc = self.root.focus_get()
        if foc == self.records and self.records.selection():
            # Удаляем, если в выборе есть хотя бы одна удаляемая запись.
            if any(self._is_deletable_iid(i) for i in self.records.selection()):
                self.action_delete_record()
        elif foc == self.tree:
            sel = self.tree.selection()
            info = self._parse_iid(sel[0]) if sel else None
            if info and info["kind"] == "zone":
                self.action_delete_zone()

    def _tree_context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
        info = self._parse_iid(iid) if iid else None
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=_("menu.connect"), command=self.action_connect)
        if info and info["kind"] == "server":
            menu.add_command(label=_("menu.disconnect"),
                             command=self.action_disconnect)
        if info and info["server"] in self.servers:
            menu.add_separator()
            menu.add_command(label=_("menu.new_zone"), command=self.action_new_zone)
            if info["kind"] == "zone":
                menu.add_command(label=_("menu.delete_zone"), command=self.action_delete_zone)
            if info["kind"] in ("zone", "node"):
                menu.add_command(label=_("menu.new_record"), command=self.action_new_record)
        menu.add_separator()
        menu.add_command(label=_("menu.refresh"), command=self.action_refresh)
        menu.tk_popup(event.x_root, event.y_root)

    def _records_context_menu(self, event):
        iid = self.records.identify_row(event.y)
        # Не сбрасываем множественный выбор: меняем его только если клик был
        # по строке вне текущего выбора.
        if iid and iid not in self.records.selection():
            self.records.selection_set(iid)
        sel = self.records.selection()
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label=_("menu.new_record"), command=self.action_new_record)
        if iid and iid.startswith("folder|") and len(sel) <= 1:
            menu.add_command(label=_("menu.open_folder"),
                             command=lambda p=iid.split("|", 1)[1]: self._open_folder(p))
        else:
            rec_items = [i for i in sel if not i.startswith("folder|")]
            if len(rec_items) == 1 and self._is_deletable_iid(rec_items[0]):
                menu.add_command(label=_("menu.edit_record"),
                                 command=self.action_edit_record)
            if any(self._is_deletable_iid(i) for i in rec_items):
                menu.add_command(label=_("menu.delete_record"),
                                 command=self.action_delete_record)
        menu.add_separator()
        menu.add_command(label=_("menu.refresh"), command=self.action_refresh)
        menu.tk_popup(event.x_root, event.y_root)

    # ==================================================================
    # Служебное
    # ==================================================================
    def _need_server(self):
        messagebox.showinfo(_("title.no_connection"),
                            _("msg.need_server"),
                            parent=self.root)

    def _update_actions(self):
        busy = self._busy
        st = self._active_state()
        sel = self.tree.selection()
        info = self._parse_iid(sel[0]) if sel else None
        has_server = st is not None and not busy
        zone_sel = has_server and info is not None and info["kind"] == "zone"
        node_sel = has_server and info is not None and info["kind"] in ("zone", "node")
        server_sel = has_server and info is not None and info["kind"] == "server"
        rec_sel = self.records.selection()
        # Записи в выборе (без папок).
        rec_items = [i for i in rec_sel if not i.startswith("folder|")]
        # Удаление доступно, если выбрана хотя бы одна удаляемая запись
        # (обычного типа). Правка — только когда выбрана ровно одна.
        deletable = node_sel and any(
            self._is_deletable_iid(i) for i in rec_items)
        edit_ok = node_sel and len(rec_items) == 1 and \
            self._is_deletable_iid(rec_items[0])
        s = lambda ok: "normal" if ok else "disabled"  # noqa: E731
        self.btn_connect.config(state=s(not busy))
        self.btn_refresh.config(state=s(has_server))
        self.btn_new_zone.config(state=s(has_server))
        self.btn_del_zone.config(state=s(zone_sel))
        self.btn_new_rec.config(state=s(node_sel))
        self.btn_edit_rec.config(state=s(edit_ok))
        self.btn_del_rec.config(state=s(deletable))

    def _is_deletable_iid(self, iid):
        """True, если iid соответствует удаляемой записи (не папке, тип EDITABLE)."""
        if not iid or iid.startswith("folder|"):
            return False
        st = self._active_state()
        try:
            rec = st.records[int(iid)]
        except (ValueError, IndexError, AttributeError):
            return False
        return rec["type_name"] in backend.EDITABLE_TYPES

    def _update_status(self):
        n = len(self.servers)
        if n == 0:
            self.status_var.set(_("status.no_connections"))
            self._update_actions()
            return
        st = self._active_state()
        if st and st.zone:
            where = _("status.zone") % st.zone
            if st.path:
                where += "  |  " + _("label.folder_path") % st.path
            self.status_var.set(
                _("status.full") %
                (n, self.active, where, len(st.records), len(st.folders)))
        elif st:
            self.status_var.set(
                _("status.zones") %
                (n, self.active, len(st.forward), len(st.reverse)))
        else:
            self.status_var.set(_("status.servers_count") % n)
        self._update_actions()

    def _about(self):
        from . import __version__
        messagebox.showinfo(
            _("menu.about"),
            _("msg.about") % __version__, parent=self.root)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except tk.TclError:
        pass
    MainWindow(root)
    root.mainloop()
