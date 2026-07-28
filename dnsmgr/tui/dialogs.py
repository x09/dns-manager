# -*- coding: utf-8 -*-
"""
Диалоги TUI (urwid): оверлейные окна в MC-стиле.

Все диалоги строятся на общем каркасе Dialog: рамка LineBox поверх
затемнённого фона, кнопки ОК/Отмена, Esc — отмена, Enter в поле — ОК.
Результат передаётся через callback (модальность обеспечивает App,
подменяя верхний виджет и возвращая его после закрытия).
"""

import urwid

from .. import backend, config, kerberos

# Атрибуты палитры (определяется в app.py)
A_DLG = "dialog"
A_FIELD = "field"
A_BTN = "button"
A_BTNF = "button_focus"
A_ERR = "error"
A_HINT = "hint"


class Dialog(urwid.WidgetWrap):
    """
    Каркас модального диалога.

    body_rows — список flow-виджетов содержимого;
    buttons   — [(метка, значение), ...]; значение передаётся в on_close;
    on_close  — callback(value) — вызывается при закрытии (None — отмена).
    """

    def __init__(self, app, title, body_rows, buttons=None, on_close=None,
                 width=60):
        self.app = app
        self.on_close = on_close or (lambda v: None)
        if buttons is None:
            buttons = [(_("btn.ok"), True), (_("btn.cancel"), None)]
        btn_row = []
        for label, value in buttons:
            b = urwid.Button(label, on_press=self._pressed, user_data=value)
            btn_row.append(urwid.AttrMap(b, A_BTN, A_BTNF))
        rows = list(body_rows)
        rows.append(urwid.Divider())
        rows.append(urwid.Columns(
            [("weight", 1, urwid.Text(""))] +
            [("pack", w) for w in btn_row], dividechars=2))
        self.listbox = urwid.ListBox(urwid.SimpleFocusListWalker(rows))
        frame = urwid.LineBox(
            urwid.Padding(self.listbox, left=1, right=1), title=title)
        super().__init__(urwid.AttrMap(frame, A_DLG))
        self.width = width
        self.height = min(len(rows) + 4, 30)

    def _pressed(self, _btn, value):
        self.close(value)

    def close(self, value):
        self.app.close_dialog(self)
        self.on_close(value)

    def keypress(self, size, key):
        if key == "esc":
            self.close(None)
            return None
        return super().keypress(size, key)


def _edit(caption, text="", mask=None):
    e = urwid.Edit(("hint", caption), text or "", mask=mask)
    return urwid.AttrMap(e, A_FIELD), e


class MessageDialog(Dialog):
    """Информационное сообщение / ошибка (одна кнопка ОК)."""

    def __init__(self, app, title, text, on_close=None):
        rows = [urwid.Text(text)]
        super().__init__(app, title, rows,
                         buttons=[(_("btn.ok"), True)],
                         on_close=on_close, width=64)


class ConfirmDialog(Dialog):
    """Вопрос да/нет."""

    def __init__(self, app, title, text, on_close):
        rows = [urwid.Text(text)]
        super().__init__(app, title, rows,
                         buttons=[(_("btn.ok"), True),
                                  (_("btn.cancel"), None)],
                         on_close=on_close, width=64)


# ──────────────────────────────────────────────────────────────────────────
class ConnectDialog(Dialog):
    """
    Подключение к серверу: список сохранённых, поля сервер/логин/пароль,
    флажок Kerberos. Результат: dict как в GUI-версии или None.
    """

    def __init__(self, app, on_close):
        self._saved = config.load_servers()
        self._krb_ticket = kerberos.has_ticket()
        self._krb_principal = (kerberos.get_principal()
                               if self._krb_ticket else None)

        rows = []
        if self._saved:
            rows.append(urwid.Text(("hint", _("dlg.server.saved"))))
            self._radio_group = []
            for i, s in enumerate(self._saved):
                krb = " [Kerberos]" if s.get("kerberos") else ""
                label = "%s  %s%s" % (s["server"], s.get("username", ""), krb)
                rb = urwid.RadioButton(self._radio_group, label,
                                       state=(i == 0),
                                       on_state_change=self._pick_saved,
                                       user_data=i)
                rows.append(rb)
            rows.append(urwid.Divider())
        else:
            self._radio_group = []

        if self._krb_ticket:
            rows.append(urwid.Text(
                _("dlg.server.ticket_ok") %
                (self._krb_principal or _("dlg.server.ticket_obtained"))))
        else:
            rows.append(urwid.Text(("hint", _("dlg.server.ticket_none"))))
        rows.append(urwid.Divider())

        w, self.ed_server = _edit(_("dlg.server.host") + " ")
        rows.append(w)
        w, self.ed_user = _edit(_("dlg.server.user") + " ")
        rows.append(w)
        rows.append(urwid.Text(("hint", _("dlg.server.user_hint"))))
        w, self.ed_pass = _edit(_("dlg.server.password") + " ", mask="•")
        rows.append(w)
        self.cb_krb = urwid.CheckBox(_("dlg.server.use_kerberos"),
                                     state=False)
        if self._krb_ticket:
            rows.append(self.cb_krb)

        super().__init__(app, _("dlg.server.title"), rows,
                         on_close=lambda v: on_close(self._result(v)),
                         width=64)
        if self._saved:
            self._apply_saved(0)

    def _pick_saved(self, _rb, state, idx):
        if state:
            self._apply_saved(idx)

    def _apply_saved(self, idx):
        s = self._saved[idx]
        self.ed_server.set_edit_text(s["server"])
        self.ed_user.set_edit_text(s.get("username", ""))
        self.cb_krb.set_state(bool(s.get("kerberos")) and self._krb_ticket,
                              do_callback=False)

    def _result(self, ok):
        if not ok:
            return None
        server = self.ed_server.edit_text.strip()
        user = self.ed_user.edit_text.strip()
        use_krb = self.cb_krb.get_state() and self._krb_ticket
        if not server:
            return {"error": _("err.no_server_name")}
        if not use_krb and not user:
            return {"error": _("err.no_username")}
        return {"server": server, "username": user,
                "password": self.ed_pass.edit_text, "kerberos": use_krb}


# ──────────────────────────────────────────────────────────────────────────
class ZoneDialog(Dialog):
    """Создание зоны (прямой/обратной). Результат: {'zone': имя} или None."""

    def __init__(self, app, kind, on_close):
        self._group = []
        rb_fwd = urwid.RadioButton(self._group, _("dlg.zone.forward"),
                                   state=(kind != "reverse"))
        rb_rev = urwid.RadioButton(self._group, _("dlg.zone.reverse"),
                                   state=(kind == "reverse"))
        self._rb_rev = rb_rev
        w, self.ed_value = _edit("")
        rows = [rb_fwd, rb_rev, urwid.Divider(),
                urwid.Text(("hint", _("dlg.zone.prompt_forward"))),
                urwid.Text(("hint", _("dlg.zone.prompt_reverse"))),
                w, urwid.Divider(),
                urwid.Text(("hint", _("dlg.zone.note")))]
        super().__init__(app, _("dlg.zone.title"), rows,
                         on_close=lambda v: on_close(self._result(v)),
                         width=64)

    def _result(self, ok):
        if not ok:
            return None
        value = self.ed_value.edit_text.strip()
        if not value:
            return {"error": _("err.zone_empty")}
        try:
            if self._rb_rev.get_state():
                zone = backend.reverse_zone_name(value)
            else:
                zone = value.rstrip(".").lower()
                if backend.is_reverse_zone(zone):
                    return {"error": _("err.zone_reverse_radio")}
        except backend.DnsBackendError as e:
            return {"error": str(e)}
        return {"zone": zone}


# ──────────────────────────────────────────────────────────────────────────
# Поля по типам записей: (ключ, метка, значение по умолчанию)
def _record_fields_spec(rtype, here):
    if rtype in ("A", "AAAA"):
        return [("name", _("dlg.record.name_a") % here, ""),
                ("ip", _("dlg.record.ipv4") if rtype == "A"
                 else _("dlg.record.ipv6"), "")]
    if rtype == "CNAME":
        return [("name", _("dlg.record.alias"), ""),
                ("target", _("dlg.record.cname_target"), "")]
    if rtype == "MX":
        return [("name", _("dlg.record.name_at") % here, "@"),
                ("exchange", _("dlg.record.mx_exchange"), ""),
                ("preference", _("dlg.record.priority"), "10")]
    if rtype == "PTR":
        return [("name", _("dlg.record.ptr_ip"), ""),
                ("host", _("dlg.record.ptr_host"), "")]
    if rtype == "SRV":
        return [("service", _("dlg.record.srv_service"), "_"),
                ("protocol", _("dlg.record.srv_protocol"), "_tcp"),
                ("priority", _("dlg.record.priority"), "0"),
                ("weight", _("dlg.record.weight"), "100"),
                ("port", _("dlg.record.port"), ""),
                ("target", _("dlg.record.srv_target"), "")]
    if rtype == "TXT":
        return [("name", _("dlg.record.name_at") % here, ""),
                ("text", _("dlg.record.txt_text"), "")]
    return []


class RecordTypeDialog(Dialog):
    """Шаг 1 создания записи: выбор типа. Результат: 'A'/'MX'/... или None."""

    def __init__(self, app, is_reverse, on_close):
        self._group = []
        default = "PTR" if is_reverse else "A"
        rows = [urwid.Text(("hint", _("dlg.record.type")))]
        for t in backend.EDITABLE_TYPES:
            rows.append(urwid.RadioButton(self._group, t,
                                          state=(t == default)))
        super().__init__(app, _("title.new_record"), rows,
                         on_close=lambda v: on_close(self._result(v)),
                         width=40)

    def _result(self, ok):
        if not ok:
            return None
        for rb in self._group:
            if rb.get_state():
                return rb.label
        return None


class RecordEditDialog(Dialog):
    """
    Шаг 2: поля записи (создание или правка).

    rtype    — тип записи;
    record   — существующая запись (dict) при правке, иначе None;
    Результат: {'rtype','name','ttl','fields', 'make_ptr'} или None
    (валидацию build_record выполняет вызывающая сторона).
    """

    def __init__(self, app, rtype, zone, is_reverse, folder="",
                 record=None, on_close=None):
        self.rtype = rtype
        self.record = record
        here = _("dlg.record.here_folder") if folder \
            else _("dlg.record.here_zone")
        title = (_("dlg.record.title_edit") if record
                 else _("dlg.record.title_new")) % (
            "%s/%s" % (zone, folder) if folder else zone)

        rows = [urwid.Text(("hint", "%s %s" % (_("dlg.record.type"), rtype)))]
        self._edits = {}
        spec = _record_fields_spec(rtype, here)
        f = record["fields"] if record else {}
        for key, label, default in spec:
            if record and key == "name":
                # Имя существующей записи не меняется — показываем текстом.
                rows.append(urwid.Text(
                    ("hint", "%s %s" % (label, record["name"] or "@"))))
                continue
            elif record and key in ("service", "protocol"):
                continue  # у существующей SRV имя не меняется
            else:
                value = str(f.get(key, default)) if record else default
            w, e = _edit(label + " ", value)
            self._edits[key] = e
            rows.append(w)
        if record and rtype == "SRV":
            rows.insert(1, urwid.Text(
                ("hint", "%s %s" % (_("dlg.record.srv_name"),
                                    record["name"]))))
        w, self.ed_ttl = _edit(_("dlg.record.ttl") + " ",
                               str(record["ttl"]) if record else "900")
        rows.append(w)
        self.cb_ptr = None
        if rtype == "A" and not record and not is_reverse:
            self.cb_ptr = urwid.CheckBox(_("dlg.record.make_ptr"))
            rows.append(self.cb_ptr)

        super().__init__(app, title, rows,
                         on_close=lambda v: on_close(self._result(v)),
                         width=64)

    def _result(self, ok):
        if not ok:
            return None
        vals = {k: e.edit_text.strip() for k, e in self._edits.items()}
        if self.record:
            name = self.record["name"]
            vals.pop("name", None)
        elif self.rtype == "SRV":
            service = vals.pop("service", "")
            protocol = vals.pop("protocol", "")
            if not service or service == "_":
                return {"error": _("err.srv_no_service")}
            service = service if service.startswith("_") else "_" + service
            protocol = (protocol if protocol.startswith("_")
                        else "_" + protocol)
            name = "%s.%s" % (service, protocol)
        else:
            name = vals.pop("name", "") or "@"
        return {"rtype": self.rtype, "name": name,
                "ttl": self.ed_ttl.edit_text.strip(), "fields": vals,
                "make_ptr": bool(self.cb_ptr and self.cb_ptr.get_state())}


# ──────────────────────────────────────────────────────────────────────────
class DeleteConfirmDialog(Dialog):
    """Подтверждение удаления записей: прокручиваемый список."""

    def __init__(self, app, records, skipped, on_close):
        rows = [urwid.Text(_("dlg.delete.header") % len(records))]
        for r in records[:200]:
            rows.append(urwid.Text(
                "  %-24s %-6s %s" % (r["name"][:24], r["type_name"],
                                     r["data"])))
        if len(records) > 200:
            rows.append(urwid.Text("  ..."))
        if skipped:
            rows.append(urwid.Text(("error",
                                    _("dlg.delete.skipped") % skipped)))
        rows.append(urwid.Text(("hint", _("dlg.delete.irreversible"))))
        super().__init__(app, _("title.delete_record"), rows,
                         on_close=on_close, width=76)


class ExportDialog(Dialog):
    """Экспорт в CSV: поле пути файла. Результат: путь или None."""

    def __init__(self, app, default_path, on_close):
        w, self.ed_path = _edit(_("tui.export.path") + " ", default_path)
        rows = [w, urwid.Text(("hint", _("dlg.export.csv")))]
        super().__init__(app, _("dlg.export.title"), rows,
                         on_close=lambda v: on_close(
                             self.ed_path.edit_text.strip() if v else None),
                         width=70)


class AboutDialog(Dialog):
    """О программе + ссылка (открытие xdg-open по кнопке)."""

    def __init__(self, app, version, url):
        from ..util import open_url
        rows = [urwid.Text(_("msg.about") % version),
                urwid.Divider(),
                urwid.Text("%s %s" % (_("about.site"), url))]
        super().__init__(
            app, _("menu.about"), rows,
            buttons=[(_("tui.about.open_site"), "open"),
                     (_("btn.ok"), True)],
            on_close=lambda v: open_url(url) if v == "open" else None,
            width=64)


class LanguageDialog(Dialog):
    """Выбор языка интерфейса. Результат: 'ru'/'en' или None."""

    def __init__(self, app, current, on_close):
        from .. import i18n
        self._group = []
        rows = []
        for code, name in i18n.available_languages():
            rows.append(urwid.RadioButton(self._group, name,
                                          state=(code == current),
                                          user_data=code))
        self._codes = [c for c, _n in i18n.available_languages()]
        super().__init__(app, _("menu.language"), rows,
                         on_close=lambda v: on_close(self._result(v)),
                         width=40)

    def _result(self, ok):
        if not ok:
            return None
        for rb, code in zip(self._group, self._codes):
            if rb.get_state():
                return code
        return None
