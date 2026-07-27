# -*- coding: utf-8 -*-
"""Диалоговые окна: выбор/добавление сервера, создание зоны, создание/правка записи."""

import tkinter as tk
from tkinter import ttk

from . import backend, kerberos  # noqa: F401  (kerberos используется ниже)

PAD = dict(padx=8, pady=4)


class ModalDialog(tk.Toplevel):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self.body = ttk.Frame(self, padding=10)
        self.body.grid(row=0, column=0, sticky="nsew")
        btns = ttk.Frame(self, padding=(10, 0, 10, 10))
        btns.grid(row=1, column=0, sticky="e")
        self.ok_btn = ttk.Button(btns, text=_("btn.ok"), width=12,
                                 command=self._on_ok, default="active")
        self.ok_btn.grid(row=0, column=0, padx=(0, 6))
        ttk.Button(btns, text=_("btn.cancel"), width=12,
                   command=self._on_cancel).grid(row=0, column=1)
        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.build_body(self.body)
        self.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        self.geometry("+%d+%d" % (px + max((pw - w) // 2, 0),
                                  py + max((ph - h) // 3, 0)))
        self.deiconify()
        self.grab_set()
        self.focus_first()
        self.wait_window(self)

    def build_body(self, master): raise NotImplementedError
    def validate(self): raise NotImplementedError
    def focus_first(self): self.body.focus_set()

    def _on_ok(self):
        try:
            self.result = self.validate()
        except backend.DnsBackendError as e:
            from tkinter import messagebox
            messagebox.showwarning(_("title.validation"), str(e), parent=self)
            return
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


# ──────────────────────────────────────────────────────────────────────────────
class ServerChooserDialog(ModalDialog):
    """
    Диалог выбора / добавления сервера (показывается при запуске и по кнопке
    «Подключиться»).  Возвращает словарь:
      {'server': ..., 'username': ..., 'password': ..., 'kerberos': bool}
    или None.
    """

    def __init__(self, parent, saved_servers=None, preselect=None):
        self._saved = saved_servers or []
        self._preselect = preselect
        self._krb_ticket = kerberos.has_ticket()
        self._krb_principal = kerberos.get_principal() if self._krb_ticket else None
        super().__init__(parent, _("dlg.server.title"))

    # ---- построение --------------------------------------------------------
    def build_body(self, master):
        master.columnconfigure(1, weight=1)
        # ── saved server list ──
        lf = ttk.LabelFrame(master, text=_("dlg.server.saved"), padding=6)
        lf.grid(row=0, column=0, columnspan=2, sticky="we", **PAD)
        lf.columnconfigure(0, weight=1)
        self.lb = tk.Listbox(lf, height=5, selectmode="single", width=36,
                             exportselection=False)
        self.lb.grid(row=0, column=0, sticky="nswe")
        sb = ttk.Scrollbar(lf, command=self.lb.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.lb.configure(yscrollcommand=sb.set)
        for s in self._saved:
            krb = " [Kerberos]" if s.get("kerberos") else ""
            self.lb.insert("end", "%s  %s%s" % (s["server"], s.get("username", ""), krb))
        self.lb.bind("<<ListboxSelect>>", self._on_lb_select)
        self.lb.bind("<Double-1>", lambda e: self._on_ok())
        btf = ttk.Frame(lf)
        btf.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(btf, text=_("btn.delete"), width=10,
                   command=self._remove_selected).grid(row=0, column=0, padx=(0, 4))

        # ── kerberos info ──
        krb_frame = ttk.Frame(master)
        krb_frame.grid(row=1, column=0, columnspan=2, sticky="we", padx=8, pady=(2, 0))
        if self._krb_ticket:
            ttk.Label(krb_frame,
                      text=_("dlg.server.ticket_ok") % (self._krb_principal or _("dlg.server.ticket_obtained")),
                      foreground="#226622").pack(side="left")
        else:
            ttk.Label(krb_frame, text=_("dlg.server.ticket_none"),
                      foreground="#888").pack(side="left")

        # ── connection form ──
        cf = ttk.LabelFrame(master, text=_("dlg.server.params"), padding=6)
        cf.grid(row=2, column=0, columnspan=2, sticky="we", **PAD)
        cf.columnconfigure(1, weight=1)

        ttk.Label(cf, text=_("dlg.server.host")).grid(
            row=0, column=0, sticky="e", **PAD)
        self.srv_var = tk.StringVar()
        self.srv_entry = ttk.Entry(cf, textvariable=self.srv_var, width=28)
        self.srv_entry.grid(row=0, column=1, sticky="we", **PAD)

        ttk.Label(cf, text=_("dlg.server.user")).grid(row=1, column=0, sticky="e", **PAD)
        self.user_var = tk.StringVar()
        self.user_entry = ttk.Entry(cf, textvariable=self.user_var, width=28)
        self.user_entry.grid(row=1, column=1, sticky="we", **PAD)
        ttk.Label(cf, text=_("dlg.server.user_hint"),
                  foreground="#666").grid(row=2, column=1, sticky="w", padx=8)

        ttk.Label(cf, text=_("dlg.server.password")).grid(row=3, column=0, sticky="e", **PAD)
        self.pass_var = tk.StringVar()
        self.pass_entry = ttk.Entry(cf, textvariable=self.pass_var,
                                    show="•", width=28)
        self.pass_entry.grid(row=3, column=1, sticky="we", **PAD)

        self.krb_var = tk.BooleanVar(value=False)
        self.krb_cb = ttk.Checkbutton(
            cf, text=_("dlg.server.use_kerberos"),
            variable=self.krb_var, command=self._on_krb_toggle,
            state="normal" if self._krb_ticket else "disabled")
        self.krb_cb.grid(row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 2))

        # подставить preselect
        if self._preselect:
            self._fill_form(self._preselect)
        elif self._saved:
            self.lb.selection_set(0)
            self._on_lb_select()
        else:
            self._on_krb_toggle()

    def _fill_form(self, spec):
        self.srv_var.set(spec.get("server", ""))
        self.user_var.set(spec.get("username", ""))
        use_krb = spec.get("kerberos", False) and self._krb_ticket
        self.krb_var.set(use_krb)
        self._on_krb_toggle()

    def _on_lb_select(self, _event=None):
        sel = self.lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._saved):
            self._fill_form(self._saved[idx])

    def _on_krb_toggle(self):
        use_krb = self.krb_var.get()
        if use_krb:
            # Имя пользователя и пароль берутся из билета — поля не нужны.
            self.pass_entry.config(state="disabled")
            self.pass_var.set("")
            self.user_entry.config(state="disabled")
        else:
            self.pass_entry.config(state="normal")
            self.user_entry.config(state="normal")

    def _remove_selected(self):
        from . import config as cfg
        sel = self.lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if 0 <= idx < len(self._saved):
            addr = self._saved[idx]["server"]
            self.lb.delete(idx)
            self._saved.pop(idx)
            cfg.remove_server(addr)

    def focus_first(self):
        self.srv_entry.focus_set()

    def validate(self):
        server = self.srv_var.get().strip()
        user = self.user_var.get().strip()
        if not server:
            raise backend.DnsBackendError(_("err.no_server_name"))
        use_krb = self.krb_var.get() and self._krb_ticket
        if not use_krb and not user:
            raise backend.DnsBackendError(_("err.no_username"))
        return {
            "server": server,
            "username": user,
            "password": self.pass_var.get(),
            "kerberos": use_krb,
        }


# ──────────────────────────────────────────────────────────────────────────────
class ZoneDialog(ModalDialog):
    """Создание прямой или обратной зоны."""

    def __init__(self, parent, kind="forward"):
        self._kind = kind
        super().__init__(parent, _("dlg.zone.title"))

    def build_body(self, master):
        self.kind_var = tk.StringVar(value=self._kind)
        ttk.Radiobutton(master, text=_("dlg.zone.forward"),
                        variable=self.kind_var, value="forward",
                        command=self._update).grid(
            row=0, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Radiobutton(master, text=_("dlg.zone.reverse"),
                        variable=self.kind_var, value="reverse",
                        command=self._update).grid(
            row=1, column=0, columnspan=2, sticky="w", **PAD)
        self.prompt = ttk.Label(master, text="")
        self.prompt.grid(row=2, column=0, columnspan=2, sticky="w", **PAD)
        self.value_var = tk.StringVar()
        self.value_var.trace_add("write", lambda *a: self._preview())
        self.entry = ttk.Entry(master, textvariable=self.value_var, width=42)
        self.entry.grid(row=3, column=0, columnspan=2, sticky="we", **PAD)
        self.preview = ttk.Label(master, text="", foreground="#666")
        self.preview.grid(row=4, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Label(master, foreground="#666", wraplength=380, text=(
            _("dlg.zone.note")
        )).grid(row=5, column=0, columnspan=2, sticky="w", **PAD)
        self._update()

    def _update(self):
        self.prompt.config(
            text=(_("dlg.zone.prompt_forward")
                  if self.kind_var.get() == "forward"
                  else _("dlg.zone.prompt_reverse")))
        self._preview()
        self.entry.focus_set()

    def _preview(self):
        text = ""
        if self.kind_var.get() == "reverse" and self.value_var.get().strip():
            try:
                text = _("dlg.zone.preview") % backend.reverse_zone_name(self.value_var.get())
            except backend.DnsBackendError:
                pass
        self.preview.config(text=text)

    def focus_first(self): self.entry.focus_set()

    def validate(self):
        value = self.value_var.get().strip()
        if not value:
            raise backend.DnsBackendError(_("err.zone_empty"))
        if self.kind_var.get() == "reverse":
            zone = backend.reverse_zone_name(value)
        else:
            zone = value.rstrip(".").lower()
            if backend.is_reverse_zone(zone):
                raise backend.DnsBackendError(
                    _("err.zone_reverse_radio"))
        return {"zone": zone}


# ──────────────────────────────────────────────────────────────────────────────
def record_type_info(rtype):
    """Пояснение к типу записи (переводится в момент вызова)."""
    return {
        "A":     _("rtype.a"),
        "AAAA":  _("rtype.aaaa"),
        "CNAME": _("rtype.cname"),
        "MX":    _("rtype.mx"),
        "PTR":   _("rtype.ptr"),
        "SRV":   _("rtype.srv"),
        "TXT":   _("rtype.txt"),
    }.get(rtype, "")


class RecordDialog(ModalDialog):
    """Создание или изменение DNS-записи."""

    def __init__(self, parent, zone, is_reverse, record=None, folder=""):
        self.zone = zone
        self.is_reverse = is_reverse
        self.record = record
        self.folder = (folder or "").rstrip(".")
        self._field_vars = {}
        self._field_widgets = []
        location = "%s/%s" % (zone, self.folder) if self.folder else zone
        title = (_("dlg.record.title_edit") % location if record
                 else _("dlg.record.title_new") % location)
        super().__init__(parent, title)

    def build_body(self, master):
        master.columnconfigure(1, weight=1)
        if self.folder:
            ttk.Label(master, foreground="#666",
                      text=_("label.folder_path") % self.folder).grid(
                row=0, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Label(master, text=_("dlg.record.type")).grid(row=1, column=0, sticky="e", **PAD)
        types = list(backend.EDITABLE_TYPES)
        default_type = "PTR" if self.is_reverse else "A"
        if self.record:
            default_type = self.record["type_name"]
        self.type_var = tk.StringVar(value=default_type)
        self.type_combo = ttk.Combobox(
            master, textvariable=self.type_var, values=types,
            state="disabled" if self.record else "readonly", width=10)
        self.type_combo.grid(row=1, column=1, sticky="w", **PAD)
        self.type_combo.bind("<<ComboboxSelected>>", lambda e: self._rebuild_fields())
        self.type_hint = ttk.Label(master, text="", foreground="#666", wraplength=380)
        self.type_hint.grid(row=2, column=0, columnspan=2, sticky="w", padx=8)
        self.fields_frame = ttk.Frame(master)
        self.fields_frame.grid(row=3, column=0, columnspan=2, sticky="we")
        self.fields_frame.columnconfigure(1, weight=1)
        ttk.Separator(master).grid(row=4, column=0, columnspan=2,
                                   sticky="we", padx=8, pady=6)
        ttk.Label(master, text=_("dlg.record.ttl")).grid(row=5, column=0, sticky="e", **PAD)
        self.ttl_var = tk.StringVar(
            value=str(self.record["ttl"]) if self.record else "900")
        ttk.Spinbox(master, textvariable=self.ttl_var, from_=0,
                    to=2 ** 31 - 1, increment=60, width=12).grid(
            row=5, column=1, sticky="w", **PAD)
        self._rebuild_fields()

    def _add_field(self, row, label, key, value="", width=34,
                   spin=False, spin_to=65535, combo=None, disabled=False):
        ttk.Label(self.fields_frame, text=label).grid(
            row=row, column=0, sticky="e", **PAD)
        var = tk.StringVar(value=str(value))
        if spin:
            w = ttk.Spinbox(self.fields_frame, textvariable=var,
                            from_=0, to=spin_to, width=10)
        elif combo:
            w = ttk.Combobox(self.fields_frame, textvariable=var, values=combo,
                             width=10, state="disabled" if disabled else "normal")
        else:
            w = ttk.Entry(self.fields_frame, textvariable=var, width=width)
        if disabled and not combo:
            w.config(state="disabled")
        w.grid(row=row, column=1, sticky="we", **PAD)
        self._field_vars[key] = var
        self._field_widgets.append(w)
        return w

    def _rebuild_fields(self):
        for w in self.fields_frame.winfo_children():
            w.destroy()
        self._field_vars = {}; self._field_widgets = []
        rtype = self.type_var.get()
        self.type_hint.config(text=record_type_info(rtype))
        rec = self.record; f = rec["fields"] if rec else {}
        name = rec["name"] if rec else ""; nd = rec is not None
        here = _("dlg.record.here_folder") if self.folder else _("dlg.record.here_zone"); r = 0
        if rtype in ("A", "AAAA"):
            self._add_field(r, _("dlg.record.name_a") % here, "name",
                            name, disabled=nd); r += 1
            self._add_field(r, _("dlg.record.ipv4") if rtype == "A" else _("dlg.record.ipv6"),
                            "ip", f.get("ip", "")); r += 1
            if rtype == "A" and not rec and not self.is_reverse:
                self.ptr_var = tk.BooleanVar(value=False)
                ttk.Checkbutton(self.fields_frame,
                                text=_("dlg.record.make_ptr"),
                                variable=self.ptr_var).grid(
                    row=r, column=0, columnspan=2, sticky="w", **PAD)
        elif rtype == "CNAME":
            self._add_field(r, _("dlg.record.alias"), "name", name, disabled=nd); r += 1
            self._add_field(r, _("dlg.record.cname_target"), "target", f.get("target", ""))
        elif rtype == "MX":
            self._add_field(r, _("dlg.record.name_at") % here, "name",
                            name or "@", disabled=nd); r += 1
            self._add_field(r, _("dlg.record.mx_exchange"), "exchange",
                            f.get("exchange", "")); r += 1
            self._add_field(r, _("dlg.record.priority"), "preference",
                            f.get("preference", 10), spin=True)
        elif rtype == "PTR":
            lbl = (_("dlg.record.ptr_ip")
                   if self.is_reverse and not self.folder else _("dlg.record.ptr_name"))
            self._add_field(r, lbl, "name", name, disabled=nd); r += 1
            self._add_field(r, _("dlg.record.ptr_host"), "host", f.get("host", ""))
        elif rtype == "SRV":
            if rec:
                self._add_field(r, _("dlg.record.srv_name"), "name", name, disabled=True); r += 1
            else:
                self._add_field(r, _("dlg.record.srv_service"), "service", "_"); r += 1
                self._add_field(r, _("dlg.record.srv_protocol"), "protocol", "_tcp",
                                combo=("_tcp", "_udp", "_tls", "_msdcs")); r += 1
            self._add_field(r, _("dlg.record.priority"), "priority",
                            f.get("priority", 0), spin=True); r += 1
            self._add_field(r, _("dlg.record.weight"), "weight",
                            f.get("weight", 100), spin=True); r += 1
            self._add_field(r, _("dlg.record.port"), "port", f.get("port", ""), spin=True); r += 1
            self._add_field(r, _("dlg.record.srv_target"), "target", f.get("target", ""))
        elif rtype == "TXT":
            self._add_field(r, _("dlg.record.name_at") % here, "name",
                            name, disabled=nd); r += 1
            self._add_field(r, _("dlg.record.txt_text"), "text", f.get("text", ""), width=44)
        for w in self._field_widgets:
            if str(w.cget("state")) != "disabled":
                w.focus_set(); break

    def focus_first(self): pass

    def validate(self):
        rtype = self.type_var.get()
        vals = {k: v.get().strip() for k, v in self._field_vars.items()}
        if rtype == "SRV" and not self.record:
            service = vals.pop("service", "")
            protocol = vals.pop("protocol", "")
            if not service or service == "_":
                raise backend.DnsBackendError(_("err.srv_no_service"))
            service = service if service.startswith("_") else "_" + service
            protocol = protocol if protocol.startswith("_") else "_" + protocol
            name = "%s.%s" % (service, protocol)
        else:
            name = vals.pop("name", "") or "@"
        if (rtype == "PTR" and self.is_reverse and not self.record
                and not self.folder):
            name = backend.ptr_relative_name(name, self.zone)
        name = backend.validate_name(name)
        rec_obj = backend.build_record(rtype, vals, self.ttl_var.get())
        return {
            "rtype": rtype, "name": name, "ttl": self.ttl_var.get(),
            "fields": vals, "record": rec_obj,
            "make_ptr": bool(getattr(self, "ptr_var", None)
                             and self.ptr_var.get()
                             and rtype == "A" and not self.record),
        }
