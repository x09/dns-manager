# -*- coding: utf-8 -*-
"""Пиктограммы кнопок панели инструментов (PNG в base64, 20x20).

Сгенерированы программно, без внешних зависимостей. Загружаются в
tk.PhotoImage после создания корневого окна.
"""

# tkinter imported lazily in get()

_ICON_DATA = {
    "connect": (
        "iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAA1ElEQVR42mNgGAxAaYGNCBBHQbEI"
        "pYb5AvFnIP6vNN/mv2Gq01cbG7cGSlwGN8woyek/0DCwoWS5FOrF/yCsXWcPNgxkKMhwkBxFBirP"
        "hhgKNYw8A+VnVAQpLXCAGYCMP5PsZblpPY5A/FV+Zsl/NENBhvmSZRgQ/wcbCnYpmckG3TAQn+w0"
        "R7FhyDkA5C1KDUPkADB2+A+KAEpc9hkzOQANBbqU/AQ7H5JYQYkWyWAycwBS3gTnAAoNFIGWGsh5"
        "k7wcAAOgIghcasynIAfQtOCkFgAAoUrbmdkSjPMAAAAASUVORK5CYII="
    ),
    "refresh": (
        "iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAAqklEQVR42mNgGAUwoJF3wgOINwPx"
        "fjQMEvMgxSBWIJ4DxP+h+CcQX4Hin0jiIDWsxBgIM+wrEJcAMR+SHB9U7CvMUGK8CTPMEo86SyRD"
        "PfAZuBmqqIQIn+wG4vNALIBP0X5oOPERMKwAavF7QraCDLxChOscgDgBiBuIceEzqGIHaqS9/UjJ"
        "ooAaBsIiZTc1cwfBZEOqoYQStgepBhKT9QyoXTiYjhafcAAAeWzAw9hg7rsAAAAASUVORK5CYII="
    ),
    "newzone": (
        "iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAABJElEQVR42mNgGAWDF0zLExED4iog"
        "bkDCIL4YuQZWAvF/LLiSXAMnL6+V/b+6UZ4kDNTzE6i3DsPANU0KP1/scPhPDgbpxTBw/2Qt4g3Z"
        "6fL/1b5AMA3ig/SSZeCr/UH/Pz3a8v/wo8P/l9/YCKZB/IOzbEg3EGTYvRdn/ntsiPuvtsj+f+6B"
        "OjAN4l++d+z/nz9/JEkyEOQSkGalBTb/fTYlggwA0yA+SPz7rx8LiDcQGFYg74FcBDKk4GAj2EAQ"
        "DeKDxA89PvkVKMZKlIGgCACFGcibIIPQMUgcJA9ki8MN3DtRk7ouXFIlffPBBhvqhSEwtctjyctw"
        "vKrLqeHOuwf3scUySBwjlokBIE0gl4C8BwozEA3ik2UYmsGsoAhACTMoAADvmzO980t/CwAAAABJ"
        "RU5ErkJggg=="
    ),
    "delzone": (
        "iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAABGElEQVR42mNgGAWDF0zLExED4iog"
        "bkDCIL4YuQZWAvF/LLiSXAMnL6+V/b+6UZ4kDNTzE6i3DsPANU0KP1/scPhPDgbpxTBw/2Qt4g3Z"
        "6fL/1b5AMA3ig/SSZeCr/UH/vzzY8v/d4X3/X6xcCaZB/IOzbEg3EGTY5xsn/9/Mzv5/QkMDjkH8"
        "l+eP/P/z548kSQaCXALSDNT4/9GECWDDQDSIDxL//ePHAuINBIYVyHvIhrw/ehTF8HeHD38F8lmJ"
        "MhAcAcAwg3kTZhiIhomB5IFi4nAD907UpK4Ll1RJ33ywwYZ6YQhM7fJY8jIcr+pyavhy9+59bLEM"
        "EseIZWIASBPIJSDvQdLh4a8gPlmGoRnMCooAlDCDAgDbgT3QGJLTnQAAAABJRU5ErkJggg=="
    ),
    "newrec": (
        "iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAABj0lEQVR42tVUv0tCURg1CBya+wea"
        "WspapSUikoagoSHaIlqDpjdFODklLTW0BGGBhEk/VCwrDPodRETyNFQSy7pGFIrenvF1zysh6NHz"
        "tkTC4fCd79zzvvt4fhbLv/spitMmMCEwaQJ4bKaBbvdsjrE8VSqVHwEPvKaBweCWaVgV8JoGhsM7"
        "pGkaqYkUxdSkIdCDB96/CcR1Htgj3d0zQ6AHj9SEh6cXdHB8bgj0pCfknFO5bAz0pCcMb+9TYHPv"
        "GzBhOpOlXIFR+iaD4AEB8wmNUHotketkhlo9PdTi6dYZdYEXl0W/XmrC+HWaxqNOaprvoC7fIHGN"
        "64waughUpN5hLJ/QDwN9q8O6B1zVLpl6K7S6mq/sVddoKDRG2ZccseLHZwNGDR19oTXW/NfbSEbI"
        "7u2nqbM58sRWdA2MGvp6MvImtIaal8NT6ZnaFh2GV4Yupo1KrS+/P+AKpXZ580IntS/1ki8R1Bk1"
        "dPEAu/SuFIccV/l41nk0TaMRhcCoof96AYvDVgQIjHyy9Wv/HbAA7SEivWFKAAAAAElFTkSuQmCC"
    ),
    "delrec": (
        "iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAABgklEQVR42tVUwUoCURQ1CFy07h9c"
        "qQsX0he0cdnSXSu/wFVEC0lEXPYTLlzNgEVhYYmJVCAzZuQ0YTm9TBoTHce4vTOkBA2Nr00kHC73"
        "3PPOnDuDz+f7d79kcifEscWx7QFoQp6Gudxel7Fnmk6nPwIaaD0NZfnA02wGaD0Ni8Ujsm2bmq02"
        "Kc1bV2AGDbR/Y4h1nliPHg3mCsygEUpYqV3RWfXCFZgJJ7Qsi8Zjd2AmnLB4eErS/sk3IKGud2hk"
        "GHSv6TDe4PBO6AZ7NCItk6HzSIQqgYBT0U+GwzyfLwslvL7R6C6bpbdWixrxuGOIih48N0wKvUNT"
        "VakaDNJLuUyTwYC0dNqp6MGbjcYDP7e08MrdfN5JVQ2H6bVedzhU9OAx59zqwn89JsvzNZHMMk2n"
        "ztZnkvTOdSsLXw5Wv0+Xsdh8zVo0Ol8f/JixY6Hrq1CQdnulkoWvOlsTFT14/tA14buSH1ofKEqn"
        "nUqRmkgQKnrwv76A+WE/DDg2P6v/6/wD9sX3O974nKgAAAAASUVORK5CYII="
    ),
    "editrec": (
        "iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAABQElEQVR42mNgGHKgoqJJH4jrgLiB"
        "AAap0SdoYH//9BevX7/5/+fPH7wYpAaklqCB27fvIWgYDIPUEjRw1679/3///v3/5u37/6/fvIcV"
        "g+RAakBqB8ZAkHdevX77//nL11gxSA6kBqR2S56IAVEuPHHm0v/jpy5gxSA5kJqL65r+b80X/Xq+"
        "Sa6GoAt//vz5/8cP7Bgk9+XU1P+vp2n8P1kr/f90vew9gi7cte/Y/227D2PFZ5aWgg2D4WPV0v0E"
        "XYgLw1yGhGuICkNsLry6thrFsIMz0oiPZfQw/HB8EophIJeSlGyQ8fltk/6vKVb5/3wKwjBYsiE5"
        "6x3eOO1/jLvc/yg3ObChMMOIznrIhcPDu9f/x3gogA0DGQpyKcmFA3LxlZ+R3AE07He0u9zf+iSz"
        "GWQVX+gAaKA2CA9YAQ0AMAuAlx3qu+cAAAAASUVORK5CYII="
    ),
}

_cache = {}


def get(name):
    """Возвращает tk.PhotoImage по имени или None (нужен Tk root)."""
    if name in _cache:
        return _cache[name]
    data = _ICON_DATA.get(name)
    if not data:
        return None
    try:
        import tkinter as tk
        img = tk.PhotoImage(data=data)
    except Exception:
        return None
    _cache[name] = img
    return img
