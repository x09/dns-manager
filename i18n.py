# -*- coding: utf-8 -*-
"""
Интернационализация интерфейса (i18n) на базе gettext (key-based модель).

В коде используются нейтральные семантические ключи (например
"menu.create_zone", "dlg.server.title"), а не текст на конкретном языке.
Каждый язык — отдельный каталог переводов:
    locale/ru/LC_MESSAGES/dnsmgr.mo — русский
    locale/en/LC_MESSAGES/dnsmgr.mo — английский
gettext по ключу возвращает строку нужного языка.

Функция перевода публикуется как встроенная `_()`, поэтому доступна во
всех модулях без импорта. Смена языка применяется при перезапуске
приложения (уже открытые окна не перестраиваются).

Каталог переводов ищется в нескольких местах по порядку (см.
`_locale_dirs`): переменная окружения DNSMGR_LOCALEDIR → каталог рядом с
пакетом (dnsmgr/locale, запуск из исходников) → системный
/usr/share/locale (стандарт gettext, установка в дистрибутив). В любом
из них .mo должен называться по имени домена: <lang>/LC_MESSAGES/dnsmgr.mo.

Если каталог выбранного языка не найден нигде, `_()` возвращает сам ключ —
это делает проблему заметной, но интерфейс остаётся работоспособным.
"""

import builtins
import gettext
import locale
import os

DOMAIN = "dnsmgr"

# Поддерживаемые языки: код -> отображаемое имя (на самом языке).
LANGUAGES = (
    ("ru", "Русский"),
    ("en", "English"),
)

# Каталог с переводами рядом с пакетом: dnsmgr/locale/<lang>/LC_MESSAGES/
_PACKAGE_LOCALE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "locale")

# Системный каталог gettext (обычно /usr/share/locale). Берётся из настроек
# gettext, чтобы учитывать нестандартные префиксы установки.
try:
    _SYSTEM_LOCALE_DIR = gettext.bindtextdomain(DOMAIN)
except Exception:
    _SYSTEM_LOCALE_DIR = "/usr/share/locale"


def _locale_dirs():
    """
    Каталоги с переводами в порядке приоритета:
      1) переменная окружения DNSMGR_LOCALEDIR (если задана);
      2) dnsmgr/locale рядом с пакетом (запуск из исходников);
      3) системный /usr/share/locale (установка в дистрибутив).
    """
    dirs = []
    env = os.environ.get("DNSMGR_LOCALEDIR", "").strip()
    if env:
        dirs.append(env)
    dirs.append(_PACKAGE_LOCALE_DIR)
    if _SYSTEM_LOCALE_DIR:
        dirs.append(_SYSTEM_LOCALE_DIR)
    return dirs

_current_lang = "en"

# Заглушка _() на случай, если модули импортируются до вызова setup()
# (например, при запуске в обход dns-manager.py или в тестах): возвращает
# сам ключ.
if "_" not in builtins.__dict__:
    builtins.__dict__["_"] = lambda s: s


def available_languages():
    """Список пар (код, отображаемое имя) поддерживаемых языков."""
    return list(LANGUAGES)


def current_language():
    """Код текущего активного языка ('ru' или 'en')."""
    return _current_lang


def detect_system_language():
    """
    Определяет язык по локали ОС. Возвращает 'ru' или 'en'.
    Если однозначно определить не удалось — 'en' (по требованию ТЗ).
    """
    candidates = []
    # Явные переменные окружения имеют приоритет над settings локали.
    for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        val = os.environ.get(var)
        if val:
            candidates.append(val)
    try:
        loc = locale.getdefaultlocale()[0]
        if loc:
            candidates.append(loc)
    except (ValueError, TypeError):
        pass
    for cand in candidates:
        low = cand.lower()
        if low.startswith("ru"):
            return "ru"
        if low.startswith("en"):
            return "en"
    # Ни русская, ни английская локаль не распознаны — английский.
    return "en"


def _install_translation(lang):
    """
    Устанавливает функцию _() для указанного языка. Каталог перевода ищется
    в местах из _locale_dirs() по порядку; используется первый найденный.
    Если нигде не найден, _() возвращает сам ключ (заметно, но не ломает UI).
    """
    for localedir in _locale_dirs():
        try:
            tr = gettext.translation(
                DOMAIN, localedir=localedir, languages=[lang])
        except (FileNotFoundError, OSError):
            continue
        builtins.__dict__["_"] = tr.gettext
        return True
    builtins.__dict__["_"] = lambda s: s
    return False


def setup(saved_lang=None):
    """
    Инициализирует локализацию при старте приложения.

    saved_lang — язык из конфига (или None при первом запуске).
    Порядок выбора: сохранённый язык → язык локали ОС → английский.
    Возвращает код выбранного языка.
    """
    global _current_lang
    lang = (saved_lang or "").strip().lower()
    if lang not in ("ru", "en"):
        lang = detect_system_language()
    _current_lang = lang
    _install_translation(lang)
    return lang


def set_language(lang):
    """
    Переключает язык (для немедленного эффекта требуется перезапуск).
    Возвращает нормализованный код языка.
    """
    global _current_lang
    lang = (lang or "").strip().lower()
    if lang not in ("ru", "en"):
        lang = "en"
    _current_lang = lang
    _install_translation(lang)
    return lang
