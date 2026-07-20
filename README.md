# Диспетчер DNS для Samba DC

Графическая утилита для Linux — аналог **Microsoft DNS Manager**.
Подключается к DNS-серверу, встроенному в контроллер домена **Samba DC**,
по протоколу MS-DNSP (DCERPC).

<img width="1234" height="747" alt="изображение" src="https://github.com/user-attachments/assets/1a05ed9d-3db9-4b43-89ea-30d8b809ca75" />


## Новое в версии 3.2

- **Пиктограммы записей в правой панели.** Три вида: обычная запись
  (A, AAAA, CNAME, MX, PTR, SRV, TXT) — документ с текстом; папка
  (вложенный раздел зоны) — жёлтая папка; запись «только чтение»
  (NS, SOA — управляются сервером) — серый документ с замком.
- **Имя сервера в дереве выделено жирным шрифтом.**

## Новое в версии 3.0

- **Kerberos / GSSAPI.** При наличии действующего TGT (билета Kerberos)
  в диалоге подключения появляется флажок «Использовать данные Kerberos
  для входа». При включении пароль не запрашивается — подключение
  выполняется через GSSAPI с имеющимся билетом. Билет определяется
  командой `klist`; поддерживаются MIT krb5 и Heimdal.
  Если билета нет — флажок неактивен, используется обычный вход.

- **Несколько серверов одновременно.** Подключённые серверы отображаются
  в дереве слева как отдельные корневые узлы (как в MS DNS Manager).
  Кликом на другом сервере переключается активный; можно держать несколько
  серверов подключёнными параллельно.

- **Список серверов в конфиге.** После успешного подключения сервер
  сохраняется в `~/.config/dns-manager/dns-manager.ini`. При запуске
  сохранённые серверы показываются в диалоге выбора. Пароль по-прежнему
  не сохраняется.

  Формат файла:
  ```ini
  [192.168.1.10]
  user = Administrator
  kerberos = false

  [dc.corp.local]
  user = admin@CORP.LOCAL
  kerberos = true
  ```

- **Пиктограммы на панели инструментов.** Все кнопки (Подключиться,
  Обновить, Создать/Удалить зону, Создать/Изменить/Удалить запись)
  получили иконки 20×20 пикселей. Сгенерированы программно, без внешних
  зависимостей — лишних файлов не требуется.

## Возможности (из предыдущих версий)

- Просмотр, создание и удаление прямых и обратных зон (интегрированных в AD).
- Создание, изменение и удаление записей: **A, AAAA, CNAME, MX, PTR, SRV, TXT**.
- Автоматическое создание PTR-записи при добавлении A-записи.
- Служебные разделы зоны (`_sites`, `_tcp`, `DomainDnsZones`, `_msdcs` и т.д.)
  отображаются в дереве как папки с ленивой подгрузкой; записи доступны
  в любой папке.
- Записи NS и SOA показываются в режиме только чтения.

## Требования (ОС Альт)

```
# apt-get install python3-modules-tkinter python3-module-samba
```

## Запуск

```
chmod +x dns-manager.py   # один раз
./dns-manager.py
```

## Состав файлов

```
dns-manager.py          — исполняемый файл (точка входа)
dns-manager.desktop     — ярлык приложения (шаблон)
icons/
    32x32/dns-manager.png
    64x64/dns-manager.png
    128x128/dns-manager.png
    256x256/dns-manager.png
dnsmgr/
    __init__.py
    backend.py          — RPC-протокол MS-DNSP, GSSAPI/Kerberos
    config.py           — INI-конфиг серверов
    kerberos.py         — определение билета Kerberos (klist)
    icons.py            — пиктограммы кнопок (PNG 20×20 в base64)
    dialogs.py          — диалоги (выбор сервера, зоны, записи)
    mainwindow.py       — главное окно (мультисервер, дерево, записи)
```

## Установка в систему (ярлык и иконки)

Иконки приложения лежат в `icons/<размер>/dns-manager.png` и предназначены
для размещения в стандартной теме hicolor:

```
# for s in 32x32 64x64 128x128 256x256; do
    install -Dm644 icons/$s/dns-manager.png \
        /usr/share/icons/hicolor/$s/apps/dns-manager.png
  done
# install -Dm755 dns-manager.py /usr/share/dns-manager/dns-manager.py
# cp -r dnsmgr /usr/share/dns-manager/
# install -Dm644 dns-manager.desktop /usr/share/applications/dns-manager.desktop
# gtk-update-icon-cache /usr/share/icons/hicolor 2>/dev/null || true
```

В `dns-manager.desktop` указан путь `Exec=/usr/share/dns-manager/dns-manager.py` —
поправьте, если размещаете программу в другом каталоге.
