# -*- coding: utf-8 -*-
"""
TUI-приложение DNS Manager (urwid) в стиле Midnight Commander.

Раскладка:
  ┌ левая панель ──────┬ правая панель ──────────────────────┐
  │ серверы/зоны/папки │ записи выбранной зоны/папки         │
  ├────────────────────┴─────────────────────────────────────┤
  │ статусная строка                                         │
  │ F2 Подкл F4 Правка F5 Обнов F6 Эксп F7 Зона+ F8 Удал ... │
  └──────────────────────────────────────────────────────────┘

Клавиши: Tab — между панелями; Enter — раскрыть/выбрать; Ins/Space —
пометить запись; F-клавиши — действия; F9 — меню; F10/Q — выход.

Фоновые RPC-операции выполняются в потоке; результат возвращается в
главный цикл через os.pipe (urwid watch_pipe) — интерфейс не замирает.
"""

import csv
import functools
import os
import threading

import urwid

from .. import backend, config, i18n
from ..backend import DnsBackend, friendly_error
from . import dialogs as dlg
from .model import ServerState, TreeModel, parse_iid, zone_iid


def PARENT_LABEL():
    """«[Совпадает с родительской папкой]» — без импорта mainwindow (tkinter)."""
    return _("common.parent_label")

PALETTE = [
    ("panel",        "light gray", "dark blue"),
    ("panel_title",  "white,bold", "dark blue"),
    ("focus",        "black", "dark cyan"),
    ("marked",       "yellow,bold", "dark blue"),
    ("marked_focus", "yellow,bold", "dark cyan"),
    ("readonly",     "dark gray", "dark blue"),
    ("statusbar",    "black", "light gray"),
    ("fkeys",        "black", "light gray"),
    ("fkey_num",     "white,bold", "black"),
    (dlg.A_DLG,      "black", "light gray"),
    (dlg.A_FIELD,    "white", "dark blue"),
    (dlg.A_BTN,      "black", "light gray"),
    (dlg.A_BTNF,     "white,bold", "dark blue"),
    (dlg.A_ERR,      "light red,bold", "light gray"),
    (dlg.A_HINT,     "dark blue", "light gray"),
    ("error",        "light red,bold", "light gray"),
    ("hint",         "dark blue", "light gray"),
]


class SelectableRow(urwid.WidgetWrap):
    """Строка списка: хранит произвольные данные, подсвечивается фокусом."""

    def __init__(self, text, data, attr="panel", focus_attr="focus"):
        self.data = data
        self.text_widget = urwid.Text(text, wrap="clip")
        super().__init__(urwid.AttrMap(self.text_widget, attr, focus_attr))

    def selectable(self):
        return True

    def keypress(self, _size, key):
        return key

    def set(self, text, attr, focus_attr):
        self.text_widget.set_text(text)
        self._w.set_attr_map({None: attr})
        self._w.set_focus_map({None: focus_attr})


class FKeyBar(urwid.WidgetWrap):
    """
    Строка функциональных клавиш внизу экрана. Отображает пары «клавиша+
    подпись» и реагирует на клик мышью: определяет, по какому пункту попал
    курсор, и вызывает on_click(action_id).

    pairs    — [(отображаемая_клавиша, подпись, action_id), ...];
    on_click — callback(action_id).
    """

    def __init__(self, pairs, on_click):
        self._on_click = on_click
        # Диапазоны колонок каждого пункта: (start, end, action_id).
        self._spans = []
        markup = []
        col = 0
        for key, label, action_id in pairs:
            segment = "%s%s " % (key, label)
            self._spans.append((col, col + len(key) + len(label), action_id))
            col += len(segment)
            markup += [("fkey_num", key), ("fkeys", label + " ")]
        self._text = urwid.Text(markup)
        super().__init__(self._text)

    def selectable(self):
        return True

    def mouse_event(self, _size, event, button, x, _y, _focus):
        if button != 1 or "press" not in event:
            return False
        for start, end, action_id in self._spans:
            if start <= x < end:
                self._on_click(action_id)
                return True
        return False


class App:
    """Главное приложение TUI."""

    def __init__(self):
        self.model = TreeModel()
        self.active = None          # адрес выбранного сервера
        self.cur_zone = None        # выбранная зона
        self.cur_path = ""          # путь папки в зоне
        self.records = []           # записи правой панели
        self.marked = set()         # индексы помеченных записей
        self.busy = False
        self._dialog_stack = []

        # -- левая панель
        self.tree_walker = urwid.SimpleFocusListWalker([])
        self.tree_list = urwid.ListBox(self.tree_walker)
        self.left = urwid.LineBox(self.tree_list,
                                  title=_("tui.panel.servers"))

        # -- правая панель
        self.rec_walker = urwid.SimpleFocusListWalker([])
        self.rec_list = urwid.ListBox(self.rec_walker)
        self.right = urwid.LineBox(self.rec_list, title=_("tui.panel.records"))

        # Ширина левой панели — фиксированная (в колонках), из конфига.
        self.left_width = config.load_tui_left_width()
        self.columns = urwid.Columns(
            [(self.left_width, urwid.AttrMap(self.left, "panel")),
             ("weight", 1, urwid.AttrMap(self.right, "panel"))],
            dividechars=0)

        self.status = urwid.Text(_("status.no_connections"))
        self.fkeys = FKeyBar(self._fkey_pairs(), self._on_fkey_click)
        footer = urwid.Pile([urwid.AttrMap(self.status, "statusbar"),
                             urwid.AttrMap(self.fkeys, "fkeys")])
        self.frame = urwid.Frame(self.columns, footer=footer)
        self.loop = urwid.MainLoop(self.frame, PALETTE,
                                   unhandled_input=self.on_key,
                                   handle_mouse=True)
        # канал поток -> главный цикл
        self._pipe = self.loop.watch_pipe(self._on_worker_done)
        self._worker_result = None

    # ==================================================================
    # Асинхронные операции (поток + pipe)
    # ==================================================================
    def run_async(self, work, on_done, status_text):
        if self.busy:
            return
        self.busy = True
        self.set_status(status_text)

        def worker():
            try:
                result, error = work(), None
            except Exception as e:  # noqa: BLE001
                result, error = None, e
            self._worker_result = (error, result, on_done)
            os.write(self._pipe, b"x")

        threading.Thread(target=worker, daemon=True).start()

    def _on_worker_done(self, _data):
        self.busy = False
        error, result, on_done = self._worker_result
        self._worker_result = None
        if error is not None:
            self.show_error(friendly_error(error))
            self.update_status()
        elif on_done:
            on_done(result)
        return True

    # ==================================================================
    # Диалоги (модальность через Overlay)
    # ==================================================================
    def open_dialog(self, dialog):
        overlay = urwid.Overlay(
            dialog, self.loop.widget,
            align="center", width=dialog.width,
            valign="middle", height=dialog.height)
        self._dialog_stack.append(self.loop.widget)
        self.loop.widget = overlay

    def close_dialog(self, _dialog):
        if self._dialog_stack:
            self.loop.widget = self._dialog_stack.pop()

    def show_error(self, text):
        self.open_dialog(dlg.MessageDialog(self, _("title.error"), text))

    def show_info(self, title, text):
        self.open_dialog(dlg.MessageDialog(self, title, text))

    # ==================================================================
    # Левая панель (дерево)
    # ==================================================================
    def rebuild_tree(self, keep_focus=True):
        focus_iid = None
        if keep_focus and self.tree_walker:
            try:
                focus_iid = self.tree_walker[
                    self.tree_list.focus_position].data["iid"]
            except (IndexError, AttributeError):
                pass
        items = self.model.flatten((_("tree.forward_zones"),
                                    _("tree.reverse_zones")))
        del self.tree_walker[:]
        pos_for_iid = {}
        for it in items:
            mark = ("▾ " if it["expanded"] else "▸ ") \
                if it["expandable"] else "  "
            text = "%s%s%s" % ("  " * it["depth"], mark, it["label"])
            pos_for_iid[it["iid"]] = len(self.tree_walker)
            self.tree_walker.append(SelectableRow(text, it))
        if focus_iid and focus_iid in pos_for_iid:
            self.tree_list.focus_position = pos_for_iid[focus_iid]
        elif self.tree_walker:
            self.tree_list.focus_position = min(
                getattr(self.tree_list, "focus_position", 0) or 0,
                len(self.tree_walker) - 1)

    def _tree_focused(self):
        if not self.tree_walker:
            return None
        try:
            return self.tree_walker[self.tree_list.focus_position].data
        except (IndexError, AttributeError):
            return None

    def on_tree_enter(self):
        it = self._tree_focused()
        if it is None or self.busy:
            return
        info = parse_iid(it["iid"])
        self.active = info["server"] if info["server"] in \
            self.model.servers else self.active
        if info["kind"] in ("server", "group"):
            self.model.toggle(it["iid"])
            self.rebuild_tree()
        elif info["kind"] in ("zone", "node"):
            addr, zone, path = info["server"], info["zone"], info["path"]
            # раскрытие + загрузка записей
            self.model.expanded.add(it["iid"])
            self.load_node(addr, zone, path)

    def load_node(self, addr, zone, path):
        st = self.model.servers.get(addr)
        if st is None:
            return
        be = st.backend

        def work():
            return be.get_node(zone, path)

        def done(node):
            self.cur_zone, self.cur_path = zone, path
            self.active = addr
            self.model.set_folders(addr, zone, path, node["folders"])
            self.records = sorted(
                node["records"],
                key=lambda r: (r["name"] != "@", r["name"].lower(),
                               r["type_name"]))
            self.marked = set()
            self.rebuild_tree()
            self.fill_records()
            self.update_status()

        where = "%s/%s" % (zone, path) if path else zone
        self.run_async(work, done, _("status.loading_where") % where)

    # ==================================================================
    # Правая панель (записи)
    # ==================================================================
    def fill_records(self):
        del self.rec_walker[:]
        header = " %-26s %-6s %-30s %s" % (
            _("col.name"), _("col.type"), _("col.data"), "TTL")
        self.rec_walker.append(
            urwid.AttrMap(urwid.Text(header, wrap="clip"), "panel_title"))
        for idx, r in enumerate(self.records):
            self.rec_walker.append(self._record_row(idx, r))
        title = self.cur_zone or _("tui.panel.records")
        if self.cur_path:
            title += "/" + self.cur_path
        self.right.set_title(title)

    def _record_row(self, idx, r):
        name = PARENT_LABEL() if r["name"] == "@" else r["name"]
        marked = idx in self.marked
        editable = r["type_name"] in backend.EDITABLE_TYPES
        prefix = "*" if marked else " "
        text = "%s%-26s %-6s %-30s %s" % (
            prefix, name[:26], r["type_name"], r["data"][:30], r["ttl"])
        if marked:
            attr, fattr = "marked", "marked_focus"
        elif not editable:
            attr, fattr = "readonly", "focus"
        else:
            attr, fattr = "panel", "focus"
        return SelectableRow(text, {"idx": idx}, attr, fattr)

    def _record_focused(self):
        try:
            row = self.rec_walker[self.rec_list.focus_position]
            if isinstance(row, SelectableRow):
                return row.data["idx"]
        except (IndexError, AttributeError):
            pass
        return None

    def toggle_mark(self):
        idx = self._record_focused()
        if idx is None:
            return
        rec = self.records[idx]
        if rec["type_name"] not in backend.EDITABLE_TYPES:
            return  # NS/SOA не помечаются
        if idx in self.marked:
            self.marked.discard(idx)
        else:
            self.marked.add(idx)
        pos = self.rec_list.focus_position
        self.rec_walker[pos] = self._record_row(idx, rec)
        # сдвинуть фокус вниз, как в MC
        if pos + 1 < len(self.rec_walker):
            self.rec_list.focus_position = pos + 1

    # ==================================================================
    # Действия
    # ==================================================================
    def action_connect(self):
        def done(res):
            if res is None:
                return
            if "error" in res:
                self.show_error(res["error"])
                return
            addr = res["server"]
            if addr in self.model.servers:
                self.show_info(_("title.connection"),
                               _("msg.already_connected") % addr)
                return
            be = DnsBackend()

            def work():
                be.connect(res["server"], res["username"], res["password"],
                           use_kerberos=res["kerberos"])
                return be.list_zones()

            def ok(zones):
                st = ServerState(be, res["username"], res["kerberos"])
                st.forward, st.reverse = zones
                self.model.add_server(addr, st)
                self.active = addr
                config.save_server(addr, res["username"], res["kerberos"])
                self.rebuild_tree()
                self.update_status()

            self.run_async(work, ok, _("status.connecting") % addr)

        self.open_dialog(dlg.ConnectDialog(self, done))

    def action_disconnect(self):
        it = self._tree_focused()
        info = parse_iid(it["iid"]) if it else None
        addr = info["server"] if info else self.active
        if not addr or addr not in self.model.servers:
            self.show_info(_("title.disconnect"),
                           _("msg.select_connected_server"))
            return

        def done(ok):
            if not ok:
                return
            self.model.servers[addr].backend.disconnect()
            self.model.remove_server(addr)
            if self.active == addr:
                self.active = None
                self.cur_zone, self.cur_path = None, ""
                self.records = []
                self.marked = set()
                self.fill_records()
            self.rebuild_tree()
            self.update_status()

        self.open_dialog(dlg.ConfirmDialog(
            self, _("title.disconnect"),
            _("msg.disconnect_confirm") % addr, done))

    def action_refresh(self):
        addr = self.active
        st = self.model.servers.get(addr)
        if st is None or self.busy:
            return
        be = st.backend
        zone, path = self.cur_zone, self.cur_path

        def work():
            zones = be.list_zones()
            node = None
            if zone and zone in zones[0] + zones[1]:
                node = be.get_node(zone, path)
            return zones, node

        def done(result):
            zones, node = result
            if addr not in self.model.servers:
                return
            st.forward, st.reverse = zones
            self.model.drop_zone_cache(addr)
            if node is not None:
                self.model.set_folders(addr, zone, path, node["folders"])
                self.records = sorted(
                    node["records"],
                    key=lambda r: (r["name"] != "@", r["name"].lower(),
                                   r["type_name"]))
                self.marked = set()
                self.fill_records()
            self.rebuild_tree()
            self.update_status()

        self.run_async(work, done, _("status.refreshing"))

    def action_new_zone(self):
        st = self.model.servers.get(self.active)
        if st is None:
            self.show_info(_("title.no_connection"), _("msg.need_server"))
            return
        it = self._tree_focused()
        info = parse_iid(it["iid"]) if it else None
        in_rev = bool(info and (
            (info["kind"] == "group" and it["iid"].startswith("rev|")) or
            (info["zone"] and backend.is_reverse_zone(info["zone"]))))
        addr, be = self.active, st.backend

        def done(res):
            if res is None:
                return
            if "error" in res:
                self.show_error(res["error"])
                return
            zone = res["zone"]

            def work():
                be.create_zone(zone)
                return be.list_zones()

            def ok(zones):
                if addr in self.model.servers:
                    st.forward, st.reverse = zones
                    self.rebuild_tree()
                    self.update_status()

            self.run_async(work, ok, _("status.creating_zone") % zone)

        self.open_dialog(dlg.ZoneDialog(
            self, "reverse" if in_rev else "forward", done))

    def action_delete_zone(self):
        it = self._tree_focused()
        info = parse_iid(it["iid"]) if it else None
        st = self.model.servers.get(info["server"]) if info else None
        if st is None or not info or info["kind"] != "zone":
            self.show_info(_("title.delete_zone"), _("msg.select_zone"))
            return
        addr, zone, be = info["server"], info["zone"], st.backend

        def done(ok):
            if not ok:
                return

            def work():
                be.delete_zone(zone)
                return be.list_zones()

            def fin(zones):
                if addr not in self.model.servers:
                    return
                st.forward, st.reverse = zones
                self.model.drop_zone_cache(addr, zone)
                if self.cur_zone == zone:
                    self.cur_zone, self.cur_path = None, ""
                    self.records = []
                    self.marked = set()
                    self.fill_records()
                self.rebuild_tree()
                self.update_status()

            self.run_async(work, fin, _("status.deleting_zone") % zone)

        self.open_dialog(dlg.ConfirmDialog(
            self, _("title.delete_zone"),
            _("msg.delete_zone_confirm") % (zone, addr), done))

    # -- записи ---------------------------------------------------------
    def action_new_record(self):
        st = self.model.servers.get(self.active)
        if st is None:
            self.show_info(_("title.no_connection"), _("msg.need_server"))
            return
        if not self.cur_zone:
            self.show_info(_("title.new_record"), _("msg.select_zone_first"))
            return
        zone, path = self.cur_zone, self.cur_path
        is_rev = backend.is_reverse_zone(zone)

        def type_chosen(rtype):
            if rtype is None:
                return
            self.open_dialog(dlg.RecordEditDialog(
                self, rtype, zone, is_rev, folder=path,
                on_close=lambda res: self._do_add_record(res, st)))

        self.open_dialog(dlg.RecordTypeDialog(self, is_rev, type_chosen))

    def _do_add_record(self, res, st):
        if res is None:
            return
        if "error" in res:
            self.show_error(res["error"])
            return
        addr, zone, path, be = (self.active, self.cur_zone,
                                self.cur_path, st.backend)
        name = res["name"]
        try:
            if (res["rtype"] == "PTR" and backend.is_reverse_zone(zone)
                    and not path):
                name = backend.ptr_relative_name(name, zone)
            name = backend.validate_name(name)
            rec_obj = backend.build_record(res["rtype"], res["fields"],
                                           res["ttl"])
        except backend.DnsBackendError as e:
            self.show_error(str(e))
            return
        full_name = backend.full_record_name(path, name)

        def work():
            be.add_record(zone, full_name, rec_obj)
            warn = None
            if res["make_ptr"]:
                host_fqdn = zone if full_name == "@" \
                    else "%s.%s" % (full_name, zone)
                try:
                    created = be.add_ptr_for_a(
                        res["fields"]["ip"], host_fqdn, st.reverse,
                        res["ttl"])
                    if created is None:
                        warn = _("msg.ptr_no_zone") % res["fields"]["ip"]
                except Exception as e:  # noqa: BLE001
                    warn = _("msg.ptr_failed") % friendly_error(e)
            return be.get_node(zone, path), warn

        def done(result):
            node, warn = result
            self._apply_node(addr, zone, path, node)
            if warn:
                self.show_info(_("title.ptr"), warn)

        self.run_async(work, done, _("status.creating_record"))

    def action_edit_record(self):
        st = self.model.servers.get(self.active)
        idx = self._record_focused()
        if st is None or idx is None:
            return
        rec = self.records[idx]
        if rec["type_name"] not in backend.EDITABLE_TYPES:
            self.show_info(_("title.edit_record"),
                           _("msg.record_not_editable") % rec["type_name"])
            return
        zone, path = self.cur_zone, self.cur_path

        def done(res):
            if res is None:
                return
            if "error" in res:
                self.show_error(res["error"])
                return
            try:
                new_rec = backend.build_record(res["rtype"], res["fields"],
                                               res["ttl"])
            except backend.DnsBackendError as e:
                self.show_error(str(e))
                return
            addr, be = self.active, st.backend

            def work():
                be.replace_record(zone, rec["full_name"], rec["raw"],
                                  new_rec)
                return be.get_node(zone, path)

            self.run_async(
                work,
                functools.partial(self._apply_node, addr, zone, path),
                _("status.editing_record"))

        self.open_dialog(dlg.RecordEditDialog(
            self, rec["type_name"], zone, backend.is_reverse_zone(zone),
            folder=path, record=rec, on_close=done))

    def action_delete_records(self):
        st = self.model.servers.get(self.active)
        if st is None or not self.records:
            return
        # помеченные, иначе — запись под курсором
        idxs = sorted(self.marked)
        if not idxs:
            idx = self._record_focused()
            if idx is None:
                self.show_info(_("title.records"), _("msg.select_record"))
                return
            idxs = [idx]
        recs, skipped = [], 0
        for i in idxs:
            r = self.records[i]
            if r["type_name"] in backend.EDITABLE_TYPES:
                recs.append(r)
            else:
                skipped += 1
        if not recs:
            self.show_info(_("title.delete_record"),
                           _("msg.nothing_deletable"))
            return
        addr, zone, path, be = (self.active, self.cur_zone,
                                self.cur_path, st.backend)
        shown = [{"name": PARENT_LABEL() if r["name"] == "@" else r["name"],
                  "type_name": r["type_name"], "data": r["data"]}
                 for r in recs]
        targets = [(r["full_name"], r["raw"]) for r in recs]

        def done(ok):
            if not ok:
                return

            def work():
                errors = []
                for full_name, raw in targets:
                    try:
                        be.delete_record(zone, full_name, raw)
                    except Exception as e:  # noqa: BLE001
                        errors.append(friendly_error(e))
                return be.get_node(zone, path), errors

            def fin(result):
                node, errors = result
                self._apply_node(addr, zone, path, node)
                if errors:
                    self.show_error(_("msg.delete_partial") %
                                    (len(errors), "\n".join(errors)))

            self.run_async(work, fin, _("status.deleting_record"))

        self.open_dialog(dlg.DeleteConfirmDialog(self, shown, skipped, done))

    def _apply_node(self, addr, zone, path, node):
        if addr not in self.model.servers:
            return
        if (self.cur_zone, self.cur_path) == (zone, path):
            self.model.set_folders(addr, zone, path, node["folders"])
            self.records = sorted(
                node["records"],
                key=lambda r: (r["name"] != "@", r["name"].lower(),
                               r["type_name"]))
            self.marked = set()
            self.rebuild_tree()
            self.fill_records()
            self.update_status()

    # -- экспорт ---------------------------------------------------------
    def action_export(self):
        st = self.model.servers.get(self.active)
        if st is None:
            self.show_info(_("title.no_connection"), _("msg.need_server"))
            return
        # что экспортируем: помеченные записи или зону целиком
        marked_only = bool(self.marked)
        it = self._tree_focused()
        info = parse_iid(it["iid"]) if it else None
        zone = self.cur_zone or (info["zone"] if info else None)
        if not zone:
            self.show_info(_("title.export"), _("msg.select_zone_first"))
            return
        default = os.path.join(os.path.expanduser("~"), "%s.csv" % zone)
        be = st.backend
        parent_label = PARENT_LABEL()

        def done(path_):
            if not path_:
                return
            if marked_only:
                rows = [backend.export_row(self.records[i], parent_label)
                        for i in sorted(self.marked)]
                try:
                    count = self._write_csv(path_, rows)
                except OSError as e:
                    self.show_error(str(e))
                    return
                self.show_info(_("title.export"),
                               _("msg.export_ok") % (count, path_))
                return

            def work():
                recs = be.iter_zone_records(zone)
                rows = [backend.export_row(r, parent_label) for r in recs]
                return self._write_csv(path_, rows)

            self.run_async(
                work,
                lambda count: self.show_info(
                    _("title.export"), _("msg.export_ok") % (count, path_)),
                _("status.exporting"))

        self.open_dialog(dlg.ExportDialog(self, default, done))

    @staticmethod
    def _write_csv(path, rows):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow([_("col.name"), _("col.type"), _("col.data")])
            for row in rows:
                w.writerow(row)
        return len(rows)

    # -- меню (F9) --------------------------------------------------------
    def action_menu(self):
        items = [
            (_("menu.connect"), self.action_connect),
            (_("menu.disconnect"), self.action_disconnect),
            (_("menu.language"), self.action_language),
            (_("menu.about"), self.action_about),
            (_("menu.exit"), self.quit),
        ]

        def done(value):
            if value is not None and callable(value):
                value()

        rows_btns = [(label, cb) for label, cb in items]
        d = dlg.Dialog(self, _("menu.help"),
                       [urwid.Text("")],
                       buttons=rows_btns + [(_("btn.cancel"), None)],
                       on_close=done, width=44)
        self.open_dialog(d)

    def action_language(self):
        def done(code):
            if code is None or code == i18n.current_language():
                return
            config.save_language(code)
            i18n.set_language(code)
            self.show_info(_("menu.language"), _("msg.language_changed"))

        self.open_dialog(dlg.LanguageDialog(
            self, i18n.current_language(), done))

    def action_about(self):
        from .. import __version__, PROJECT_URL
        self.open_dialog(dlg.AboutDialog(self, __version__, PROJECT_URL))

    # ==================================================================
    # Статус и клавиши
    # ==================================================================
    def set_status(self, text):
        self.status.set_text(" " + text)
        # обновить экран из фонового статуса
        if self.loop.screen.started:
            self.loop.draw_screen()

    def update_status(self):
        n = len(self.model.servers)
        if n == 0:
            self.set_status(_("status.no_connections"))
            return
        st = self.model.servers.get(self.active)
        if st and self.cur_zone:
            where = _("status.zone") % self.cur_zone
            if self.cur_path:
                where += "  |  " + _("label.folder_path") % self.cur_path
            self.set_status(
                _("status.full") % (n, self.active, where,
                                    len(self.records),
                                    len(self.model.folder_cache.get(
                                        (self.active, self.cur_zone,
                                         self.cur_path), []))))
        elif st:
            self.set_status(
                _("status.zones") % (n, self.active,
                                     len(st.forward), len(st.reverse)))
        else:
            self.set_status(_("status.servers_count") % n)

    def _fkey_pairs(self):
        """Список (клавиша, подпись, действие-id) для строки F-клавиш."""
        return [
            ("F2", _("tui.fk.connect"), "f2"),
            ("F4", _("tui.fk.edit"), "f4"),
            ("F5", _("tui.fk.refresh"), "f5"),
            ("F6", _("tui.fk.export"), "f6"),
            ("F7", _("tui.fk.newzone"), "f7"),
            ("F8", _("tui.fk.delete"), "f8"),
            ("Ins", _("tui.fk.mark"), "ins"),
            ("F9", _("tui.fk.menu"), "f9"),
            ("F10", _("tui.fk.quit"), "f10"),
        ]

    def _on_fkey_click(self, action_id):
        """Клик мышью по метке F-клавиши — то же действие, что и клавиша."""
        if self._dialog_stack:
            return
        self._dispatch(action_id)

    def _dispatch(self, action_id):
        """Единая точка действий F-клавиш (общая для клавиатуры и мыши)."""
        in_left = self.columns.focus_position == 0
        if action_id == "f2":
            self.action_connect()
        elif action_id == "f4":
            if not in_left:
                self.action_edit_record()
        elif action_id == "f5":
            self.action_refresh()
        elif action_id == "f6":
            self.action_export()
        elif action_id == "f7":
            self.action_new_zone() if in_left else self.action_new_record()
        elif action_id == "f8":
            self.action_delete_zone() if in_left \
                else self.action_delete_records()
        elif action_id == "ins":
            if not in_left:
                self.toggle_mark()
        elif action_id == "f9":
            self.action_menu()
        elif action_id == "f10":
            self.quit()

    def quit(self):
        raise urwid.ExitMainLoop()

    # ==================================================================
    def on_key(self, key):
        if not isinstance(key, str):
            return
        # диалог открыт — не обрабатываем глобальные клавиши
        if self._dialog_stack:
            return
        k = key.lower()
        in_left = self.columns.focus_position == 0
        if key == "tab":
            self.columns.focus_position = 1 if in_left else 0
        elif key == "enter":
            self.on_tree_enter() if in_left else self.action_edit_record()
        elif key in ("insert", " "):
            self._dispatch("ins")
        elif key in ("f2", "f4", "f5", "f6", "f7", "f8", "f9", "f10"):
            self._dispatch(key)
        elif key == "delete":
            self._dispatch("f8")
        elif k == "q":
            self.quit()
        elif k == "n" and not in_left:
            self.action_new_record()

    def run(self):
        self.rebuild_tree()
        self.fill_records()
        self.update_status()
        # предложить подключение при старте (как GUI)
        self.loop.set_alarm_in(0.1, lambda *_a: self.action_connect())
        self.loop.run()


def main():
    App().run()
