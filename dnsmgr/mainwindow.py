# -*- coding: utf-8 -*-
"""Главное окно DNS Manager (в стиле Microsoft DNS Manager)."""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import backend, config
from .backend import DnsBackend, friendly_error
from .dialogs import ConnectDialog, RecordDialog, ZoneDialog

APP_TITLE = "Диспетчер DNS — Samba DC"


class MainWindow:
    def __init__(self, root):
        self.root = root
        self.backend = DnsBackend()
        self.zones_forward = []
        self.zones_reverse = []
        self.current_zone = None
        self.current_records = []
        self._task_queue = queue.Queue()
        self._busy = False

        root.title(APP_TITLE)
        root.geometry("980x620")
        root.minsize(720, 420)

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

        # --- левая часть: дерево зон -----------------------------------
        left = ttk.Frame(panes)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        tree_scroll = ttk.Scrollbar(left, orient="vertical",
                                    command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")
        panes.add(left, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
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
        self.records.column("name", width=220, anchor="w")
        self.records.column("type", width=70, anchor="w", stretch=False)
        self.records.column("data", width=420, anchor="w")
        self.records.column("ttl", width=70, anchor="e", stretch=False)
        rec_scroll = ttk.Scrollbar(right, orient="vertical",
                                   command=self.records.yview)
        self.records.configure(yscrollcommand=rec_scroll.set)
        self.records.pack(side="left", fill="both", expand=True)
        rec_scroll.pack(side="right", fill="y")
        panes.add(right, weight=3)

        self.records.bind("<Double-1>", lambda e: self.action_edit_record())
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
    # Асинхронное выполнение RPC-вызовов (не блокируем интерфейс)
    # ==================================================================
    def run_async(self, work, on_done=None, status="Выполняется..."):
        if self._busy:
            return
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
        self.current_zone, self.current_records = None, []
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
            self.tree.insert("fwd", "end", iid="zone|" + z, text=z)
        for z in self.zones_reverse:
            self.tree.insert("rev", "end", iid="zone|" + z, text=z)
        select_zone = select_zone or self.current_zone
        iid = "zone|" + select_zone if select_zone else None
        if iid and self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)
        else:
            self.current_zone = None
            self.current_records = []
            self.records.delete(*self.records.get_children())
        self._update_status()

    def action_refresh(self):
        if not self.backend.connected or self._busy:
            return
        zone = self.current_zone

        def work():
            zones = self.backend.list_zones()
            recs = self.backend.get_records(zone) if zone else None
            return zones, recs

        def done(result):
            zones, recs = result
            self._apply_zones(zones)
            if recs is not None and self.current_zone == zone:
                self._apply_records(recs)

        self.run_async(work, done, "Обновление...")

    def action_new_zone(self):
        if not self._require_connection():
            return
        kind = "reverse" if self._selected_tree_group() == "rev" else "forward"
        dlg = ZoneDialog(self.root, kind)
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
        zone = self._selected_zone()
        if not zone:
            messagebox.showinfo("Удаление зоны",
                                "Выберите зону в дереве слева.",
                                parent=self.root)
            return
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
    # Записи
    # ==================================================================
    def _load_zone_records(self, zone):
        def work():
            return self.backend.get_records(zone)

        def done(recs):
            if self.current_zone == zone:
                self._apply_records(recs)

        self.run_async(work, done, "Загрузка записей зоны %s..." % zone)

    def _apply_records(self, recs):
        def sort_key(r):
            return (r["name"] != "@", r["name"].lower(), r["type_name"])
        self.current_records = sorted(recs, key=sort_key)
        self.records.delete(*self.records.get_children())
        for idx, r in enumerate(self.current_records):
            name = ("(совпадает с родительской папкой)"
                    if r["name"] == "@" else r["name"])
            self.records.insert("", "end", iid=str(idx), values=(
                name, r["type_name"], r["data"], r["ttl"]))
        self._update_status()

    def _sort_records(self, key):
        if not self.current_records:
            return
        rev = getattr(self, "_sort_reverse", {}).get(key, False)
        self.current_records.sort(
            key=lambda r: (str(r.get(key, "")).lower()
                           if key != "ttl" else r["ttl"]),
            reverse=rev)
        if not hasattr(self, "_sort_reverse"):
            self._sort_reverse = {}
        self._sort_reverse[key] = not rev
        self.records.delete(*self.records.get_children())
        for idx, r in enumerate(self.current_records):
            name = ("(совпадает с родительской папкой)"
                    if r["name"] == "@" else r["name"])
            self.records.insert("", "end", iid=str(idx), values=(
                name, r["type_name"], r["data"], r["ttl"]))

    def action_new_record(self):
        if not self._require_connection():
            return
        zone = self.current_zone
        if not zone:
            messagebox.showinfo("Новая запись",
                                "Сначала выберите зону в дереве слева.",
                                parent=self.root)
            return
        dlg = RecordDialog(self.root, zone, backend.is_reverse_zone(zone))
        if dlg.result is None:
            return
        res = dlg.result

        def work():
            self.backend.add_record(zone, res["name"], res["record"])
            warn = None
            if res["make_ptr"]:
                host_fqdn = (zone if res["name"] == "@"
                             else "%s.%s" % (res["name"], zone))
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
            return self.backend.get_records(zone), warn

        def done(result):
            recs, warn = result
            if self.current_zone == zone:
                self._apply_records(recs)
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
        zone = self.current_zone
        dlg = RecordDialog(self.root, zone, backend.is_reverse_zone(zone),
                           record=rec)
        if dlg.result is None:
            return
        res = dlg.result

        def work():
            self.backend.replace_record(zone, rec["name"],
                                        rec["raw"], res["record"])
            return self.backend.get_records(zone)

        self.run_async(work,
                       lambda recs: (self.current_zone == zone
                                     and self._apply_records(recs)),
                       "Изменение записи...")

    def action_delete_record(self):
        rec = self._selected_record()
        if rec is None:
            return
        zone = self.current_zone
        shown = ("(совпадает с родительской папкой)" if rec["name"] == "@"
                 else rec["name"])
        if not messagebox.askyesno(
                "Удаление записи",
                "Удалить запись?\n\nИмя: %s\nТип: %s\nДанные: %s" %
                (shown, rec["type_name"], rec["data"]),
                icon="warning", parent=self.root):
            return

        def work():
            self.backend.delete_record(zone, rec["name"], rec["raw"])
            return self.backend.get_records(zone)

        self.run_async(work,
                       lambda recs: (self.current_zone == zone
                                     and self._apply_records(recs)),
                       "Удаление записи...")

    # ==================================================================
    # Выбор в дереве / контекстные меню
    # ==================================================================
    def _on_tree_select(self, _event=None):
        zone = self._selected_zone()
        self._update_actions()
        if zone and zone != self.current_zone and not self._busy:
            self.current_zone = zone
            self._load_zone_records(zone)
        elif not zone:
            self.current_zone = None
            self.current_records = []
            self.records.delete(*self.records.get_children())
            self._update_status()

    def _selected_tree_group(self):
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        if iid in ("fwd", "rev"):
            return iid
        if iid.startswith("zone|"):
            parent = self.tree.parent(iid)
            return parent
        return None

    def _selected_zone(self):
        sel = self.tree.selection()
        if sel and sel[0].startswith("zone|"):
            return sel[0].split("|", 1)[1]
        return None

    def _selected_record(self):
        sel = self.records.selection()
        if not sel:
            messagebox.showinfo("Записи", "Выберите запись в списке справа.",
                                parent=self.root)
            return None
        try:
            return self.current_records[int(sel[0])]
        except (ValueError, IndexError):
            return None

    def _on_delete_key(self):
        if self.root.focus_get() == self.records and self.records.selection():
            self.action_delete_record()
        elif self.root.focus_get() == self.tree and self._selected_zone():
            self.action_delete_zone()

    def _tree_context_menu(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.tree.selection_set(iid)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Создать зону...", command=self.action_new_zone)
        if self._selected_zone():
            menu.add_command(label="Удалить зону",
                             command=self.action_delete_zone)
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
        if iid:
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
        zone_selected = connected and self._selected_zone() is not None
        rec_selected = (zone_selected and bool(self.records.selection()))
        state = lambda ok: "normal" if ok else "disabled"  # noqa: E731
        self.btn_connect.config(state=state(not self._busy))
        self.btn_refresh.config(state=state(connected))
        self.btn_new_zone.config(state=state(connected))
        self.btn_del_zone.config(state=state(zone_selected))
        self.btn_new_rec.config(state=state(zone_selected))
        self.btn_edit_rec.config(state=state(rec_selected))
        self.btn_del_rec.config(state=state(rec_selected))

    def _update_status(self):
        if not self.backend.connected:
            self.status_var.set("Нет подключения")
        elif self.current_zone:
            self.status_var.set(
                "Сервер: %s  |  Зона: %s  |  Записей: %d" %
                (self.backend.server, self.current_zone,
                 len(self.current_records)))
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
