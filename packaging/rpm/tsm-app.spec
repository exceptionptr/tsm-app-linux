Name:           tsm-app
Version:        1.0.5
Release:        1%{?dist}
Summary:        TradeSkillMaster Desktop App for Linux

License:        MIT
URL:            https://github.com/exceptionptr/tsm-app-linux
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz#/tsm-app-linux-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel >= 3.11
BuildRequires:  python3-build
BuildRequires:  python3-installer
BuildRequires:  python3-hatchling
BuildRequires:  python3-hatch-vcs
BuildRequires:  git

Requires:       python3 >= 3.11
Requires:       python3-pyside6
Requires:       python3-aiohttp
Requires:       python3-pydantic
Requires:       python3-aiosqlite
Requires:       python3-keyring
Requires:       python3-structlog
Requires:       python3-tomli-w
Requires:       python3-pyyaml

%description
Downloads auction house data from the TSM API and writes Lua files for
the TradeSkillMaster WoW addon running under Wine, Lutris, or Steam.

%prep
%autosetup -n tsm-app-linux-%{version}

%build
SETUPTOOLS_SCM_PRETEND_VERSION=%{version} python3 -m build --wheel --no-isolation

%install
python3 -m installer --destdir=%{buildroot} dist/*.whl
install -Dm644 packaging/tsm-app.desktop \
    %{buildroot}%{_datadir}/applications/tsm-app.desktop
install -Dm644 tsm/ui/assets/tsm_16.png  %{buildroot}%{_datadir}/icons/hicolor/16x16/apps/tsm-app.png
install -Dm644 tsm/ui/assets/tsm_32.png  %{buildroot}%{_datadir}/icons/hicolor/32x32/apps/tsm-app.png
install -Dm644 tsm/ui/assets/tsm_48.png  %{buildroot}%{_datadir}/icons/hicolor/48x48/apps/tsm-app.png
install -Dm644 tsm/ui/assets/tsm_128.png %{buildroot}%{_datadir}/icons/hicolor/128x128/apps/tsm-app.png
install -Dm644 tsm/ui/assets/tsm_256.png %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/tsm-app.png
install -Dm644 LICENSE \
    %{buildroot}%{_datadir}/licenses/%{name}/LICENSE

%files
%license LICENSE
%{python3_sitelib}/tsm/
%{python3_sitelib}/tsm_app-*.dist-info/
%{_bindir}/tsm-app
%{_datadir}/applications/tsm-app.desktop
%{_datadir}/icons/hicolor/*/apps/tsm-app.png
%{_datadir}/licenses/%{name}/

%changelog
* Fri Mar 20 2026 exceptionptr <https://github.com/exceptionptr> - 1.0.5-1
- Add: Protocol types for ServiceContainer fields in scheduler.py
- Add: unit tests for ConfigStore, WoWDetectorService, BackupService, AddonWriterService, and AuctionCache snapshot round-trip
- CI: Python 3.13 added to the test matrix

* Thu Mar 19 2026 exceptionptr <https://github.com/exceptionptr> - 1.0.4-1
- Fix: Last Updated column now correctly shows the primary tag timestamp
- Fix: tray notification text trimmed to "{n} realm(s)/region(s) updated."
- Add: reverse-engineered TSM API reference document (API.md)
- CI: softprops/action-gh-release bumped to v2.3.2; AUR workflow extracted to separate manual dispatch

* Wed Mar 18 2026 exceptionptr <https://github.com/exceptionptr> - 1.0.3-1
- Fix: realm list no longer clears when WoW install or AppHelper is not detected during refresh
- Fix: closing via tray Quit no longer shows double confirmation dialog
- Fix: config no longer silently mutated when quitting via tray
- Add: timestamps on all log output
- Add: log file with rotation at ~/.local/share/tsm-app/logs/tsm-app.log, keeps last 5 backups
- Chore: clean up PKGBUILD comments

* Wed Mar 18 2026 exceptionptr <https://github.com/exceptionptr> - 1.0.2-1
- Fix: CI workflows now only trigger on main branch
- Fix: revert softprops/action-gh-release to v2 to fix GitHub Release upload crash

* Wed Mar 18 2026 exceptionptr <https://github.com/exceptionptr> - 1.0.1-1
- Fix: closing window with confirmation now quits the app instead of hiding to tray
- Fix: prevent multiple simultaneous instances; second launch shows "already running" dialog
- Fix: app icon now installed to hicolor theme so it appears in desktop launchers
- CI: bump GitHub Actions to Node.js 24 runtime

* Tue Mar 17 2026 exceptionptr <https://github.com/exceptionptr> - 1.0.0-1
- Initial release
