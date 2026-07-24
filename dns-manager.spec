Name:          dns-manager
Version:       3.5
Release:       alt1
License:       %gpl3only
Group:         System/Configuration/Other
Source:        %name-v%version.tgz
BuildArch:     noarch

Summary:       Graphical DNS management utility for Samba AD
Url:           https://github.com/x09/dns-manager

BuildRequires: 	rpm-build-licenses

Requires: 	python3-modules-tkinter
Requires: 	python3-module-samba
Requires: 	python3

%description
A graphical DNS management utility for GNU/Linux, similar to Microsoft DNS Manager,
connecting to the Samba DC's built-in DNS server via MS-DNSP (DCERPC) protocol.

%description -l ru_RU.UTF-8
Графическая утилита для GNU/Linux — аналог Microsoft DNS Manager.
Подключается к DNS-серверу, встроенному в контроллер домена Samba DC,
по протоколу MS-DNSP (DCERPC).

%prep
%setup -n %name-v%version

%install
for language in ru en; do
	mkdir -p %buildroot/%_datadir/locale/$language/LC_MESSAGES/
	install -m644 dnsmgr/locale/ru/LC_MESSAGES/dnsmgr.mo %buildroot/%_datadir/locale/$language/LC_MESSAGES/
done


mkdir -p %buildroot/%_datadir/%name/dnsmgr
cp dnsmgr/*.py %buildroot/%_datadir/%name/dnsmgr/

mkdir -p  %buildroot/%_desktopdir
cp %name.desktop %buildroot/%_desktopdir/%name.desktop

mkdir -p  %buildroot/%_iconsdir
for s in 32x32 64x64 128x128 256x256; do
    mkdir -p %buildroot/%_iconsdir/hicolor/$s/apps/
    cp icons/$s/%name.png %buildroot/%_iconsdir/hicolor/$s/apps/%name.png
done

mkdir -p %buildroot/%_bindir/
cp %name.py %buildroot/%_bindir/dns-manager
chmod 755 %buildroot/%_bindir/dns-manager

%post

%postun

%files
%_bindir/dns-manager
%_iconsdir/hicolor/*
%_desktopdir/%name.desktop
%_datadir/%name/dnsmgr/*
%_datadir/locale/ru/LC_MESSAGES/*
%_datadir/locale/en/LC_MESSAGES/*

%changelog
* Thu Jul 23 2026 Anton Shevtsov <shevtsov.anton@gmail.com> 3.5-alt1
- Batch DNS record deletion with filtering

* Thu Jul 23 2026 Anton Shevtsov <shevtsov.anton@gmail.com> 3.4-alt1
- Add multilingual interface

* Mon Jul 20 2026 Anton Shevtsov <shevtsov.anton@gmail.com> 3.3-alt1
- Kerberos fixes

* Mon Jul 20 2026 Anton Shevtsov <shevtsov.anton@gmail.com> 3.2-alt1
- New version

* Wed Jul 15 2026 Anton Shevtsov <shevtsov.anton@gmail.com> 3.1-alt1
- New version
