# -*- coding: utf-8 -*-
"""
Главное окно DNS Manager (в стиле Microsoft DNS Manager).

Версия 2.0: зоны раскрываются в дереве на вложенные папки (служебные
разделы _sites, _tcp, _udp, DomainDnsZones и т.д.), записи показываются
для выбранной папки; создание/правка/удаление записей работает в любой
папке зоны.
"""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import backend, config
from .backend import DnsBackend, friendly_error
from .dialogs import ConnectDialog, RecordDialog, ZoneDialog

APP_TITLE = "Диспетчер DNS — Samba DC"
PARENT_LABEL = "(совпадает с родительской папкой)"


class MainWindow:
    def __init__(self, root):
        self.root = root
        self.backend = DnsBackend()
        self.zones_forward = []
        self.zones_reverse = []
        self.current_zone = None        # выбранная зона
        self.current_path = ""          # путь папки внутри зоны ('' — корень)
        self.current_records = []
        self.current_folders = []
        self._task_queue = queue.Queue()
        self._busy = False
        self._sort_state = {}

        root.title(APP_TITLE)
        root.geometry("1020x640")
        root.minsize(760, 440)

        self._build_menu()
        self._build_toolbar()
        self._build_panes()
        self._build_statusbar()
        self._update_actions()

        root.after(200, self._startup_connect)

    # ==================================================================
    # Построение интерфейса
    # ==================================================================
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Подключиться к серверу...",
                           command=self.action_connect)
        m_file.add_command(label="Отключиться", command=self.action_disconnect)
        m_file.add_separator()
        m_file.add_command(label="Выход", command=self.root.destroy)
        menubar.add_cascade(label="Файл", menu=m_file)

        self.m_action = tk.Menu(menubar, tearoff=0)
        self.m_action.add_command(label="Обновить", accelerator="F5",
                                  command=self.action_refresh)
        self.m_action.add_separator()
        self.m_action.add_command(label="Создать зону...",
                                  command=self.action_new_zone)
        self.m_action.add_command(label="Удалить зону",
                                  command=self.action_delete_zone)
        self.m_action.add_separator()
        self.m_action.add_command(label="Создать запись...",
                                  command=self.action_new_record)
        self.m_action.add_command(label="Изменить запись...",
                                  command=self.action_edit_record)
        self.m_action.add_command(label="Удалить запись",
                                  command=self.action_delete_record)
        menubar.add_cascade(label="Действие", menu=self.m_action)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="О программе", command=self._about)
        menubar.add_cascade(label="Справка", menu=m_help)

        self.root.config(menu=menubar)
        self.root.bind("<F5>", lambda e: self.action_refresh())
        self.root.bind("<Delete>", lambda e: self._on_delete_key())

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(6, 4))
        bar.pack(side="top", fill="x")
        self.btn_connect = ttk.Button(bar, text="Подключиться",
                                      command=self.action_connect)
        self.btn_refresh = ttk.Button(bar, text="Обновить (F5)",
                                      command=self.action_refresh)
        self.btn_new_zone = ttk.Button(bar, text="Создать зону",
                                       command=self.action_new_zone)
        self.btn_del_zone = ttk.Button(bar, text="Удалить зону",
                                       command=self.action_delete_zone)
        self.btn_new_rec = ttk.Button(bar, text="Создать запись",
                                      command=self.action_new_record)
        self.btn_edit_rec = ttk.Button(bar, text="Изменить запись",
                                       command=self.action_edit_record)
        self.btn_del_rec = ttk.Button(bar, text="Удалить запись",
                                      command=self.action_delete_record)
        for i, b in enumerate((self.btn_connect, self.btn_refresh,
                               self.btn_new_zone, self.btn_del_zone,
                               self.btn_new_rec, self.btn_edit_rec,
                               self.btn_del_rec)):
            b.grid(row=0, column=i, padx=2)

    def _build_panes(self):
        panes = ttk.PanedWindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        # --- левая часть: дерево зон и папок ----------------------------
        left = ttk.Frame(panes)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        tree_scroll = ttk.Scrollbar(left, orient="vertical",
                                    command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        panes.add(left, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self.tree.bind("<Button-3>", self._tree_context_menu)

        # --- правая часть: записи --------------------------------------
        right = ttk.Frame(panes)
        columns = ("name", "type", "data", "ttl")
        self.records = ttk.Treeview(right, columns=columns, show="headings",
                                    selectmode="browse")
        self.records.heading("name", text="Имя",
                             command=lambda: self._sort_records("name"))
        self.records.heading("type", text="Тип",
                             command=lambda: self._sort_records("type_name"))
        self.records.heading("data", text="Данные",
                             command=lambda: self._sort_records("data"))
        self.records.heading("ttl", text="TTL",
                             command=lambda: self._sort_records("ttl"))
        self.records.column("name", width=240, anchor="w")
        self.records.column("type", width=70, anchor="w", stretch=False)
        self.records.column("data", width=430, anchor="w")
        self.records.column("ttl", width=70, anchor="e", stretch=False)
        rec_scroll = ttk.Scrollbar(right, orient="vertical",
                                   command=self.records.yview)
        self.records.configure(yscrollcommand=rec_scroll.set)
        self.records.pack(side="left", fill="both", expand=True)
        rec_scroll.pack(side="right", fill="y")
        panes.add(right, weight=3)

        self.records.bind("<Double-1>", self._on_records_double_click)
        self.records.bind("<Button-3>", self._records_context_menu)
        self.records.bind("<<TreeviewSelect>>",
                          lambda e: self._update_actions())

        self._rebuild_tree_skeleton()

    def _build_statusbar(self):
        self.status_var = tk.StringVar(value="Нет подключения")
        bar = ttk.Frame(self.root)
        bar.pack(side="bottom", fill="x")
        ttk.Separator(bar).pack(fill="x")
        ttk.Label(bar, textvariable=self.status_var, padding=(8, 3)).pack(
            side="left")

    def _rebuild_tree_skeleton(self):
        self.tree.delete(*self.tree.get_children())
        server = self.backend.server or "(не подключено)"
        self.tree.insert("", "end", iid="server", text=server, open=True)
        self.tree.insert("server", "end", iid="fwd",
                         text="Зоны прямого просмотра", open=True)
        self.tree.insert("server", "end", iid="rev",
                         text="Зоны обратного просмотра", open=True)

    # ==================================================================
    # Идентификаторы элементов дерева
    #   зона:   "zone|<имя зоны>"
    #   папка:  "node|<имя зоны>|<путь внутри зоны>"
    #   заглушка для ленивой загрузки: "<iid родителя>|dummy"
    # ==================================================================
    @staticmethod
    def _tree_iid(zone, path):
        return "zone|" + zone if not path else "node|%s|%s" % (zone, path)

    @staticmethod
    def _node_from_iid(iid):
        """Возвращает (zone, path) для элемента дерева или None."""
        if not iid or iid.endswith("|dummy"):
            return None
        if iid.startswith("zone|"):
            return iid.split("|", 1)[1], ""
        if iid.startswith("node|"):
            _, zone, path = iid.split("|", 2)
            return zone, path
        return None

    def _add_dummy(self, parent_iid):
        self.tree.insert(parent_iid, "end", iid=parent_iid + "|dummy",
                         text="...")

    # ==================================================================
    # Асинхронное выполнение RPC-вызовов (не блокируем интерфейс)
    # ==================================================================
    def run_async(self, work, on_done=None, status="Выполняется..."):
        if self._busy:
            return False
        self._set_busy(True, status)

        def worker():
            try:
                result = work()
                error = None
            except Exception as e:  # noqa: BLE001 — показываем пользователю
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
            messagebox.showerror("Ошибка", friendly_error(error),
                                 parent=self.root)
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
    # Подключение
    # ==================================================================
    def _startup_connect(self):
        cfg = config.load()
        self._connect_dialog(cfg["server"], cfg["username"])

    def action_connect(self):
        cfg = config.load()
        self._connect_dialog(cfg["server"], cfg["username"])

    def _connect_dialog(self, server, username, error=None):
        dlg = ConnectDialog(self.root, server, username, error)
        if dlg.result is None:
            return
        params = dlg.result

        def work():
            self.backend.connect(params["server"], params["username"],
                                 params["password"])
            return self.backend.list_zones()

        def done(zones):
            config.save(params["server"], params["username"])
            self.root.title("%s — %s" % (APP_TITLE, params["server"]))
            self._apply_zones(zones)

        def on_fail(exc):
            # Показать диалог снова с текстом ошибки
            self._connect_dialog(params["server"], params["username"],
                                 friendly_error(exc))

        self._run_connect(work, done, on_fail)

    def _run_connect(self, work, done, on_fail):
        """Как run_async, но при ошибке заново открывает диалог подключения."""
        if self._busy:
            return
        self._set_busy(True, "Подключение к серверу...")

        def worker():
            try:
                result = work()
                error = None
            except Exception as e:  # noqa: BLE001
                result, error = None, e
            self._task_queue.put(
                (None, None,
                 lambda _r, er=error, rs=result: (done(rs) if er is None
                                                  else on_fail(er))))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(50, self._poll_queue)

    def action_disconnect(self):
        self.backend.disconnect()
        self.zones_forward, self.zones_reverse = [], []
        self.current_zone, self.current_path = None, ""
        self.current_records, self.current_folders = [], []
        self.records.delete(*self.records.get_children())
        self._rebuild_tree_skeleton()
        self.root.title(APP_TITLE)
        self._update_status()

    # ==================================================================
    # Зоны
    # ==================================================================
    def _apply_zones(self, zones, select_zone=None):
        self.zones_forward, self.zones_reverse = zones
        self._rebuild_tree_skeleton()
        for z in self.zones_forward:
            iid = self._tree_iid(z, "")
            self.tree.insert("fwd", "end", iid=iid, text=z)
            self._add_dummy(iid)
        for z in self.zones_reverse:
            iid = self._tree_iid(z, "")
            self.tree.insert("rev", "end", iid=iid, text=z)
            self._add_dummy(iid)
        select_zone = select_zone or self.current_zone
        iid = self._tree_iid(select_zone, "") if select_zone else None
        # После перестройки дерева папки пропадают — выбираем корень зоны
        self.current_path = ""
        if iid and self.tree.exists(iid):
            self.current_zone = select_zone
            self.tree.selection_set(iid)
            self.tree.see(iid)
        else:
            self.current_zone = None
            self.current_records, self.current_folders = [], []
            self.records.delete(*self.records.get_children())
        self._update_status()

    def action_refresh(self):
        if not self.backend.connected or self._busy:
            return
        zone = self.current_zone

        def work():
            zones = self.backend.list_zones()
            # После обновления возвращаемся к корню зоны
            node = (self.backend.get_node(zone, "")
                    if zone and zone in zones[0] + zones[1] else None)
            return zones, node

        def done(result):
            zones, node = result
            self._apply_zones(zones)
            if node is not None and self.current_zone == zone:
                self._apply_node(zone, "", node)

        self.run_async(work, done, "Обновление...")

    def action_new_zone(self):
        if not self._require_connection():
            return
        sel = self.tree.selection()
        in_reverse = bool(
            sel and (sel[0] == "rev"
                     or (self._node_from_iid(sel[0])
                         and backend.is_reverse_zone(
                             self._node_from_iid(sel[0])[0]))))
        dlg = ZoneDialog(self.root, "reverse" if in_reverse else "forward")
        if dlg.result is None:
            return
        zone = dlg.result["zone"]

        def work():
            self.backend.create_zone(zone)
            return self.backend.list_zones()

        self.run_async(work,
                       lambda zones: self._apply_zones(zones, select_zone=zone),
                       "Создание зоны %s..." % zone)

    def action_delete_zone(self):
        if not self._require_connection():
            return
        sel = self.tree.selection()
        node = self._node_from_iid(sel[0]) if sel else None
        if not node or node[1]:
            messagebox.showinfo(
                "Удаление зоны",
                "Выберите зону (корневой элемент, не папку) в дереве слева.",
                parent=self.root)
            return
        zone = node[0]
        if not messagebox.askyesno(
                "Удаление зоны",
                "Удалить зону «%s» со всеми записями?\n"
                "Действие необратимо." % zone,
                icon="warning", parent=self.root):
            return

        def work():
            self.backend.delete_zone(zone)
            return self.backend.list_zones()

        def done(zones):
            self.current_zone = None
            self._apply_zones(zones)

        self.run_async(work, done, "Удаление зоны %s..." % zone)

    # ==================================================================
    # Узлы (папки) и записи
    # ==================================================================
    def _load_node(self, zone, path):
        def work():
            return self.backend.get_node(zone, path)

        def done(node):
            if (self.current_zone, self.current_path) == (zone, path):
                self._apply_node(zone, path, node)

        where = "%s/%s" % (zone, path) if path else zone
        self.run_async(work, done, "Загрузка %s..." % where)

    def _apply_node(self, zone, path, node):
        """Заполняет правую панель и дочерние папки в дереве."""
        def sort_key(r):
            return (r["name"] != "@", r["name"].lower(), r["type_name"])
        self.current_records = sorted(node["records"], key=sort_key)
        self.current_folders = node["folders"]
        self._sort_state = {}
        self._fill_records_pane()
        self._update_tree_children(zone, path, node["folders"])
        self._update_status()

    def _fill_records_pane(self):
        self.records.delete(*self.records.get_children())
        for f in self.current_folders:
            self.records.insert("", "end", iid="folder|" + f["path"],
                                values=(f["name"], "", "(папка)", ""))
        for idx, r in enumerate(self.current_records):
            name = PARENT_LABEL if r["name"] == "@" else r["name"]
            self.records.insert("", "end", iid=str(idx), values=(
                name, r["type_name"], r["data"], r["ttl"]))

    def _update_tree_children(self, zone, path, folders):
        parent = self._tree_iid(zone, path)
        if not self.tree.exists(parent):
            return
        wanted = [( "node|%s|%s" % (zone, f["path"]), f["name"])
                  for f in folders]
        wanted_ids = {iid for iid, _n in wanted}
        for child in self.tree.get_children(parent):
            if child not in wanted_ids:
                self.tree.delete(child)   # заглушка и устаревшие папки
        for pos, (iid, name) in enumerate(wanted):
            if self.tree.exists(iid):
                self.tree.move(iid, parent, pos)
            else:
                self.tree.insert(parent, pos, iid=iid, text=name)
                self._add_dummy(iid)

    def _sort_records(self, key):
        if not self.current_records:
            return
        rev = self._sort_state.get(key, False)
        self.current_records.sort(
            key=lambda r: (str(r.get(key, "")).lower()
                           if key != "ttl" else r["ttl"]),
            reverse=rev)
        self._sort_state[key] = not rev
        self._fill_records_pane()

    def action_new_record(self):
        if not self._require_connection():
            return
        zone, path = self.current_zone, self.current_path
        if not zone:
            messagebox.showinfo("Новая запись",
                                "Сначала выберите зону в дереве слева.",
                                parent=self.root)
            return
        dlg = RecordDialog(self.root, zone, backend.is_reverse_zone(zone),
                           folder=path)
        if dlg.result is None:
            return
        res = dlg.result
        full_name = backend.full_record_name(path, res["name"])

        def work():
            self.backend.add_record(zone, full_name, res["record"])
            warn = None
            if res["make_ptr"]:
                host_fqdn = (zone if full_name == "@"
                             else "%s.%s" % (full_name, zone))
                try:
                    created_in = self.backend.add_ptr_for_a(
                        res["fields"]["ip"], host_fqdn,
                        self.zones_reverse, res["ttl"])
                    if created_in is None:
                        warn = ("PTR-запись не создана: не найдена "
                                "подходящая обратная зона для адреса %s."
                                % res["fields"]["ip"])
                except Exception as e:  # noqa: BLE001
                    warn = "PTR-запись не создана: %s" % friendly_error(e)
            return self.backend.get_node(zone, path), warn

        def done(result):
            node, warn = result
            if (self.current_zone, self.current_path) == (zone, path):
                self._apply_node(zone, path, node)
            if warn:
                messagebox.showwarning("PTR-запись", warn, parent=self.root)

        self.run_async(work, done, "Создание записи...")

    def action_edit_record(self):
        rec = self._selected_record()
        if rec is None:
            return
        if rec["type_name"] not in backend.EDITABLE_TYPES:
            messagebox.showinfo(
                "Изменение записи",
                "Записи типа %s изменяются автоматически сервером\n"
                "и не редактируются в этой программе." % rec["type_name"],
                parent=self.root)
            return
        zone, path = self.current_zone, self.current_path
        dlg = RecordDialog(self.root, zone, backend.is_reverse_zone(zone),
                           record=rec, folder=path)
        if dlg.result is None:
            return
        res = dlg.result

        def work():
            self.backend.replace_record(zone, rec["full_name"],
                                        rec["raw"], res["record"])
            return self.backend.get_node(zone, path)

        def done(node):
            if (self.current_zone, self.current_path) == (zone, path):
                self._apply_node(zone, path, node)

        self.run_async(work, done, "Изменение записи...")

    def action_delete_record(self):
        rec = self._selected_record()
        if rec is None:
            return
        zone, path = self.current_zone, self.current_path
        shown = PARENT_LABEL if rec["name"] == "@" else rec["name"]
        if not messagebox.askyesno(
                "Удаление записи",
                "Удалить запись?\n\nИмя: %s\nТип: %s\nДанные: %s" %
                (shown, rec["type_name"], rec["data"]),
                icon="warning", parent=self.root):
            return

        def work():
            self.backend.delete_record(zone, rec["full_name"], rec["raw"])
            return self.backend.get_node(zone, path)

        def done(node):
            if (self.current_zone, self.current_path) == (zone, path):
                self._apply_node(zone, path, node)

        self.run_async(work, done, "Удаление записи...")

    # ==================================================================
    # Выбор в дереве / контекстные меню
    # ==================================================================
    def _on_tree_select(self, _event=None):
        sel = self.tree.selection()
        node = self._node_from_iid(sel[0]) if sel else None
        self._update_actions()
        if node is None:
            if sel and sel[0] in ("server", "fwd", "rev"):
                self.current_zone, self.current_path = None, ""
                self.current_records, self.current_folders = [], []
                self.records.delete(*self.records.get_children())
                self._update_status()
            return
        zone, path = node
        if (zone, path) != (self.current_zone, self.current_path) \
                and not self._busy:
            self.current_zone, self.current_path = zone, path
            self._load_node(zone, path)

    def _on_tree_open(self, _event=None):
        """Ленивая подгрузка дочерних папок при раскрытии элемента."""
        iid = self.tree.focus()
        node = self._node_from_iid(iid)
        if node is None or self._busy:
            return
        children = self.tree.get_children(iid)
        if len(children) == 1 and children[0].endswith("|dummy"):
            zone, path = node

            def work():
                return self.backend.get_node(zone, path)

            def done(data):
                self._update_tree_children(zone, path, data["folders"])

            self.run_async(work, done, "Загрузка...")

    def _selected_record(self):
        sel = self.records.selection()
        if not sel:
            messagebox.showinfo("Записи", "Выберите запись в списке справа.",
                                parent=self.root)
            return None
        iid = sel[0]
        if iid.startswith("folder|"):
            messagebox.showinfo(
                "Записи",
                "Выбрана папка. Откройте её двойным щелчком, затем\n"
                "выберите запись.", parent=self.root)
            return None
        try:
            return self.current_records[int(iid)]
        except (ValueError, IndexError):
            return None

    def _on_records_double_click(self, event):
        iid = self.records.identify_row(event.y)
        if iid.startswith("folder|"):
            self._open_folder(iid.split("|", 1)[1])
        elif iid:
            self.action_edit_record()

    def _open_folder(self, path):
        """Переход в папку (по двойному щелчку в правой панели)."""
        zone = self.current_zone
        if not zone:
            return
        iid = self._tree_iid(zone, path)
        if self.tree.exists(iid):
            parent = self.tree.parent(iid)
            if parent:
                self.tree.item(parent, open=True)
            self.tree.selection_set(iid)
            self.tree.see(iid)
            # выбор в дереве сам инициирует загрузку записей

    def _on_delete_key(self):
        if self.root.focus_get() == self.records and self.records.selection():
            iid = self.records.selection()[0]
            if not iid.startswith("folder|"):
                self.action_delete_record()
        elif self.root.focus_get() == self.tree:
            sel = self.tree.selection()
            node = self._node_from_iid(sel[0]) if sel else None
            if node and not node[1]:
                self.action_delete_zone()

    def _tree_context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
        sel_node = self._node_from_iid(iid) if iid else None
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Создать зону...", command=self.action_new_zone)
        if sel_node and not sel_node[1]:
            menu.add_command(label="Удалить зону",
                             command=self.action_delete_zone)
        if sel_node:
            menu.add_separator()
            menu.add_command(label="Создать запись...",
                             command=self.action_new_record)
        menu.add_separator()
        menu.add_command(label="Обновить", command=self.action_refresh)
        menu.tk_popup(event.x_root, event.y_root)

    def _records_context_menu(self, event):
        iid = self.records.identify_row(event.y)
        if iid:
            self.records.selection_set(iid)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Создать запись...",
                         command=self.action_new_record)
        if iid and iid.startswith("folder|"):
            menu.add_command(
                label="Открыть папку",
                command=lambda p=iid.split("|", 1)[1]: self._open_folder(p))
        elif iid:
            menu.add_command(label="Изменить запись...",
                             command=self.action_edit_record)
            menu.add_command(label="Удалить запись",
                             command=self.action_delete_record)
        menu.add_separator()
        menu.add_command(label="Обновить", command=self.action_refresh)
        menu.tk_popup(event.x_root, event.y_root)

    # ==================================================================
    # Служебное
    # ==================================================================
    def _require_connection(self):
        if self._busy:
            return False
        if not self.backend.connected:
            messagebox.showinfo("Нет подключения",
                                "Сначала подключитесь к серверу "
                                "(Файл → Подключиться к серверу).",
                                parent=self.root)
            return False
        return True

    def _update_actions(self):
        connected = self.backend.connected and not self._busy
        sel = self.tree.selection()
        sel_node = self._node_from_iid(sel[0]) if sel else None
        node_selected = connected and sel_node is not None
        zone_selected = node_selected and not sel_node[1]
        rec_sel = self.records.selection()
        rec_selected = (node_selected and bool(rec_sel)
                        and not rec_sel[0].startswith("folder|"))
        state = lambda ok: "normal" if ok else "disabled"  # noqa: E731
        self.btn_connect.config(state=state(not self._busy))
        self.btn_refresh.config(state=state(connected))
        self.btn_new_zone.config(state=state(connected))
        self.btn_del_zone.config(state=state(zone_selected))
        self.btn_new_rec.config(state=state(node_selected))
        self.btn_edit_rec.config(state=state(rec_selected))
        self.btn_del_rec.config(state=state(rec_selected))

    def _update_status(self):
        if not self.backend.connected:
            self.status_var.set("Нет подключения")
        elif self.current_zone:
            where = "Зона: %s" % self.current_zone
            if self.current_path:
                where += "  |  Папка: %s" % self.current_path
            self.status_var.set(
                "Сервер: %s  |  %s  |  Записей: %d, папок: %d" %
                (self.backend.server, where,
                 len(self.current_records), len(self.current_folders)))
        else:
            self.status_var.set(
                "Сервер: %s  |  Зон: %d прямых, %d обратных" %
                (self.backend.server, len(self.zones_forward),
                 len(self.zones_reverse)))
        self._update_actions()

    def _about(self):
        from . import __version__
        messagebox.showinfo(
            "О программе",
            "Диспетчер DNS для Samba DC, версия %s\n\n"
            "Аналог Microsoft DNS Manager для Linux.\n"
            "Работает по протоколу MS-DNSP (RPC) через\n"
            "python-биндинги Samba.\n\n"
            "Python 3 + Tkinter." % __version__,
            parent=self.root)


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
