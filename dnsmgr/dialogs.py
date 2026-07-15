# -*- coding: utf-8 -*-
"""Диалоговые окна: подключение, создание зоны, создание/правка записи."""

import tkinter as tk
from tkinter import ttk

from . import backend

PAD = dict(padx=8, pady=4)


class ModalDialog(tk.Toplevel):
    """Базовый модальный диалог с кнопками ОК/Отмена."""

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
        self.ok_btn = ttk.Button(btns, text="ОК", width=12,
                                 command=self._on_ok, default="active")
        self.ok_btn.grid(row=0, column=0, padx=(0, 6))
        ttk.Button(btns, text="Отмена", width=12,
                   command=self._on_cancel).grid(row=0, column=1)

        self.bind("<Return>", lambda e: self._on_ok())
        self.bind("<Escape>", lambda e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        self.build_body(self.body)

        # Центрирование относительно родителя
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

    # Переопределяются наследниками -----------------------------------
    def build_body(self, master):
        raise NotImplementedError

    def validate(self):
        """Возвращает словарь результата или бросает DnsBackendError."""
        raise NotImplementedError

    def focus_first(self):
        self.body.focus_set()

    # ------------------------------------------------------------------
    def _on_ok(self):
        try:
            self.result = self.validate()
        except backend.DnsBackendError as e:
            from tkinter import messagebox
            messagebox.showwarning("Проверка данных", str(e), parent=self)
            return
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


# ----------------------------------------------------------------------
class ConnectDialog(ModalDialog):
    """Запрос сервера, логина и пароля."""

    def __init__(self, parent, server="", username="", error=None):
        self._init_server = server
        self._init_username = username
        self._error = error
        super().__init__(parent, "Подключение к DNS-серверу")

    def build_body(self, master):
        ttk.Label(master, text="Укажите контроллер домена Samba (DNS-сервер),\n"
                               "имя пользователя и пароль.").grid(
            row=0, column=0, columnspan=2, sticky="w", **PAD)

        ttk.Label(master, text="Сервер (имя или IP):").grid(
            row=1, column=0, sticky="e", **PAD)
        self.server_var = tk.StringVar(value=self._init_server)
        ttk.Entry(master, textvariable=self.server_var, width=32).grid(
            row=1, column=1, sticky="we", **PAD)

        ttk.Label(master, text="Пользователь:").grid(
            row=2, column=0, sticky="e", **PAD)
        self.user_var = tk.StringVar(value=self._init_username)
        ttk.Entry(master, textvariable=self.user_var, width=32).grid(
            row=2, column=1, sticky="we", **PAD)
        ttk.Label(master, text="(формы: user, DOMAIN\\user, user@realm)",
                  foreground="#666").grid(row=3, column=1, sticky="w", padx=8)

        ttk.Label(master, text="Пароль:").grid(
            row=4, column=0, sticky="e", **PAD)
        self.pass_var = tk.StringVar()
        ttk.Entry(master, textvariable=self.pass_var, show="•",
                  width=32).grid(row=4, column=1, sticky="we", **PAD)

        if self._error:
            ttk.Label(master, text=self._error, foreground="#a00000",
                      wraplength=340).grid(row=5, column=0, columnspan=2,
                                           sticky="w", **PAD)

    def focus_first(self):
        entries = [c for c in self.body.winfo_children()
                   if isinstance(c, ttk.Entry)]
        for e in entries:
            if not e.get():
                e.focus_set()
                return
        if entries:
            entries[0].focus_set()

    def validate(self):
        server = self.server_var.get().strip()
        user = self.user_var.get().strip()
        if not server:
            raise backend.DnsBackendError("Укажите имя сервера.")
        if not user:
            raise backend.DnsBackendError("Укажите имя пользователя.")
        return {"server": server, "username": user,
                "password": self.pass_var.get()}


# ----------------------------------------------------------------------
class ZoneDialog(ModalDialog):
    """Создание прямой или обратной зоны."""

    def __init__(self, parent, kind="forward"):
        # kind: 'forward' | 'reverse' — стартовое положение переключателя
        self._kind = kind
        super().__init__(parent, "Создание новой зоны")

    def build_body(self, master):
        self.kind_var = tk.StringVar(value=self._kind)
        ttk.Radiobutton(master, text="Зона прямого просмотра",
                        variable=self.kind_var, value="forward",
                        command=self._update).grid(
            row=0, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Radiobutton(master, text="Зона обратного просмотра (reverse)",
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
            "Зона будет создана как основная (primary), "
            "интегрированная в Active Directory.")).grid(
            row=5, column=0, columnspan=2, sticky="w", **PAD)
        self._update()

    def _update(self):
        if self.kind_var.get() == "forward":
            self.prompt.config(text="Имя зоны (например, corp.example.ru):")
        else:
            self.prompt.config(
                text="ИД сети (например, 192.168.1 или 10.0.0.0/16)\n"
                     "или готовое имя зоны *.in-addr.arpa / *.ip6.arpa:")
        self._preview()
        self.entry.focus_set()

    def _preview(self):
        text = ""
        if self.kind_var.get() == "reverse" and self.value_var.get().strip():
            try:
                text = ("Имя зоны: %s" %
                        backend.reverse_zone_name(self.value_var.get()))
            except backend.DnsBackendError:
                text = ""
        self.preview.config(text=text)

    def focus_first(self):
        self.entry.focus_set()

    def validate(self):
        value = self.value_var.get().strip()
        if not value:
            raise backend.DnsBackendError("Заполните поле имени зоны.")
        if self.kind_var.get() == "reverse":
            zone = backend.reverse_zone_name(value)
        else:
            zone = value.rstrip(".").lower()
            if backend.is_reverse_zone(zone):
                raise backend.DnsBackendError(
                    "Для обратной зоны выберите переключатель "
                    "«Зона обратного просмотра».")
        return {"zone": zone}


# ----------------------------------------------------------------------
# Описание полей для каждого типа записи (по ТЗ)
RECORD_TYPE_INFO = {
    "A":     "Сопоставляет имя хоста с IPv4-адресом",
    "AAAA":  "Сопоставляет имя хоста с IPv6-адресом",
    "CNAME": "Псевдоним (алиас) для другого имени хоста",
    "MX":    "Почтовый сервер домена",
    "PTR":   "Обратное сопоставление: IP-адрес → имя хоста",
    "SRV":   "Местоположение службы (хост и порт)",
    "TXT":   "Произвольная текстовая информация (SPF и т.п.)",
}


class RecordDialog(ModalDialog):
    """Создание или изменение DNS-записи."""

    def __init__(self, parent, zone, is_reverse, record=None):
        """
        zone       — имя зоны;
        is_reverse — зона обратного просмотра;
        record     — существующая запись (dict из backend.get_records)
                     для режима редактирования, None — создание.
        """
        self.zone = zone
        self.is_reverse = is_reverse
        self.record = record
        self._field_vars = {}
        self._field_widgets = []
        title = ("Изменение записи — %s" % zone if record
                 else "Новая запись — %s" % zone)
        super().__init__(parent, title)

    # ------------------------------------------------------------------
    def build_body(self, master):
        master.columnconfigure(1, weight=1)

        ttk.Label(master, text="Тип записи:").grid(
            row=0, column=0, sticky="e", **PAD)
        types = list(backend.EDITABLE_TYPES)
        default_type = "PTR" if self.is_reverse else "A"
        if self.record:
            default_type = self.record["type_name"]
        self.type_var = tk.StringVar(value=default_type)
        self.type_combo = ttk.Combobox(
            master, textvariable=self.type_var, values=types,
            state="disabled" if self.record else "readonly", width=10)
        self.type_combo.grid(row=0, column=1, sticky="w", **PAD)
        self.type_combo.bind("<<ComboboxSelected>>",
                             lambda e: self._rebuild_fields())

        self.type_hint = ttk.Label(master, text="", foreground="#666",
                                   wraplength=380)
        self.type_hint.grid(row=1, column=0, columnspan=2, sticky="w",
                            padx=8)

        # Контейнер для полей конкретного типа
        self.fields_frame = ttk.Frame(master)
        self.fields_frame.grid(row=2, column=0, columnspan=2, sticky="we")
        self.fields_frame.columnconfigure(1, weight=1)

        ttk.Separator(master).grid(row=3, column=0, columnspan=2,
                                   sticky="we", padx=8, pady=6)
        ttk.Label(master, text="TTL (секунды):").grid(
            row=4, column=0, sticky="e", **PAD)
        self.ttl_var = tk.StringVar(
            value=str(self.record["ttl"]) if self.record else "900")
        ttk.Spinbox(master, textvariable=self.ttl_var, from_=0,
                    to=2 ** 31 - 1, increment=60, width=12).grid(
            row=4, column=1, sticky="w", **PAD)

        self._rebuild_fields()

    # ------------------------------------------------------------------
    def _add_field(self, row, label, key, value="", width=34,
                   spin=False, spin_to=65535, combo=None, disabled=False):
        ttk.Label(self.fields_frame, text=label).grid(
            row=row, column=0, sticky="e", **PAD)
        var = tk.StringVar(value=str(value))
        if spin:
            w = ttk.Spinbox(self.fields_frame, textvariable=var, from_=0,
                            to=spin_to, width=10)
        elif combo:
            w = ttk.Combobox(self.fields_frame, textvariable=var,
                             values=combo, width=10,
                             state="disabled" if disabled else "normal")
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
        self._field_vars = {}
        self._field_widgets = []
        rtype = self.type_var.get()
        self.type_hint.config(text=RECORD_TYPE_INFO.get(rtype, ""))
        rec = self.record
        f = rec["fields"] if rec else {}
        name = rec["name"] if rec else ""
        name_disabled = rec is not None
        r = 0

        if rtype in ("A", "AAAA"):
            self._add_field(r, "Имя (пусто или @ — сама зона):", "name",
                            name, disabled=name_disabled); r += 1
            self._add_field(
                r, "IPv4-адрес:" if rtype == "A" else "IPv6-адрес:",
                "ip", f.get("ip", "")); r += 1
            if rtype == "A" and not rec and not self.is_reverse:
                self.ptr_var = tk.BooleanVar(value=False)
                ttk.Checkbutton(
                    self.fields_frame,
                    text="Создать связанную PTR-запись (если есть зона)",
                    variable=self.ptr_var).grid(
                    row=r, column=0, columnspan=2, sticky="w", **PAD)
        elif rtype == "CNAME":
            self._add_field(r, "Псевдоним (имя относительно зоны):", "name",
                            name, disabled=name_disabled); r += 1
            self._add_field(r, "FQDN целевого узла:", "target",
                            f.get("target", ""))
        elif rtype == "MX":
            self._add_field(r, "Имя (обычно @ — сама зона):", "name",
                            name or "@", disabled=name_disabled); r += 1
            self._add_field(r, "FQDN почтового сервера:", "exchange",
                            f.get("exchange", "")); r += 1
            self._add_field(r, "Приоритет (Preference):", "preference",
                            f.get("preference", 10), spin=True)
        elif rtype == "PTR":
            label = ("IP-адрес (или последние октеты):" if self.is_reverse
                     else "Имя записи:")
            self._add_field(r, label, "name", name,
                            disabled=name_disabled); r += 1
            self._add_field(r, "Имя узла (FQDN):", "host", f.get("host", ""))
        elif rtype == "SRV":
            if rec:
                self._add_field(r, "Служба и протокол:", "name", name,
                                disabled=True); r += 1
            else:
                self._add_field(r, "Служба (например _ldap):",
                                "service", "_"); r += 1
                self._add_field(r, "Протокол:", "protocol", "_tcp",
                                combo=("_tcp", "_udp", "_tls", "_msdcs")); r += 1
            self._add_field(r, "Приоритет:", "priority",
                            f.get("priority", 0), spin=True); r += 1
            self._add_field(r, "Вес:", "weight",
                            f.get("weight", 100), spin=True); r += 1
            self._add_field(r, "Порт:", "port",
                            f.get("port", ""), spin=True); r += 1
            self._add_field(r, "Узел, предоставляющий службу (FQDN):",
                            "target", f.get("target", ""))
        elif rtype == "TXT":
            self._add_field(r, "Имя записи (пусто или @ — сама зона):",
                            "name", name, disabled=name_disabled); r += 1
            self._add_field(r, "Текст:", "text", f.get("text", ""), width=44)

        # Фокус на первое редактируемое поле
        for w in self._field_widgets:
            if str(w.cget("state")) != "disabled":
                w.focus_set()
                break

    def focus_first(self):
        pass  # выставляется в _rebuild_fields

    # ------------------------------------------------------------------
    def validate(self):
        rtype = self.type_var.get()
        vals = {k: v.get().strip() for k, v in self._field_vars.items()}

        if rtype == "SRV" and not self.record:
            service = vals.pop("service", "")
            protocol = vals.pop("protocol", "")
            if not service or service == "_":
                raise backend.DnsBackendError("Укажите имя службы.")
            if not service.startswith("_"):
                service = "_" + service
            if not protocol.startswith("_"):
                protocol = "_" + protocol
            name = "%s.%s" % (service, protocol)
        else:
            name = vals.pop("name", "") or "@"

        if rtype == "PTR" and self.is_reverse and not self.record:
            # Пользователь мог ввести полный IP — преобразуем
            name = backend.ptr_relative_name(name, self.zone)

        name = backend.validate_name(name)
        rec_obj = backend.build_record(rtype, vals, self.ttl_var.get())
        return {
            "rtype": rtype,
            "name": name,
            "ttl": self.ttl_var.get(),
            "fields": vals,
            "record": rec_obj,
            "make_ptr": bool(getattr(self, "ptr_var", None)
                             and self.ptr_var.get()
                             and rtype == "A" and not self.record),
        }
