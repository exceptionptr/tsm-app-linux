Name:           tsm-app
Version:        1.1.6
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

Requires:       python3
Requires:       python3-pyside6
Requires:       python3-aiohttp
Requires:       python3-pydantic
Requires:       python3-aiosqlite
Requires:       python3-keyring
Requires:       python3-PyYAML
# apscheduler (4.x), structlog, and tomli-w are bundled under
# /usr/lib/tsm-app/vendor/ because they are not packaged in Fedora/openSUSE.

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

# Bundle Python deps not packaged in Fedora/openSUSE repos
pip3 install --target=%{buildroot}/usr/lib/tsm-app/vendor \
    "apscheduler>=4.0.0,<5" structlog tomli-w

# Inject vendor path into the entry point so it takes precedence over any
# system-installed incompatible version (e.g. apscheduler 3.x)
python3 -c "
import pathlib
ep = pathlib.Path('%{buildroot}%{_bindir}/tsm-app')
lines = ep.read_text().splitlines(keepends=True)
lines.insert(1, 'import sys; sys.path.insert(0, \"/usr/lib/tsm-app/vendor\")\n')
ep.write_text(''.join(lines))
"

%files
%license LICENSE
%{python3_sitelib}/tsm/
%{python3_sitelib}/tsm_app-*.dist-info/
%{_bindir}/tsm-app
%{_datadir}/applications/tsm-app.desktop
%{_datadir}/icons/hicolor/*/apps/tsm-app.png
%{_datadir}/licenses/%{name}/
/usr/lib/tsm-app/

%changelog
* Tue Apr 22 2026 exceptionptr <https://github.com/exceptionptr> - 1.1.6-1
- Fix: Debian .deb packaging for Ubuntu 24.04+/26.04: replace python3-pyside6
  with individual Qt module packages, bundle APScheduler 4.x/structlog/tomli-w,
  use python3 shebang and version-agnostic install path

* Fri Apr 04 2026 exceptionptr <https://github.com/exceptionptr> - 1.1.5-1
- Fix: AppHelper folder name corrected for non-retail game versions; always
  TradeSkillMaster_AppHelper regardless of version, confirmed against Windows
  reference; eliminates false "AppHelper missing" for Classic/Era/Anniversary
- Fix: sync skips game versions without AppHelper folder; previously downloaded
  all blobs and discarded them
- Add: Addon Versions tab group headers show WoW installation status per game version

* Wed Apr 01 2026 exceptionptr <https://github.com/exceptionptr> - 1.1.4-1
- Add: update notification - amber status bar label when newer GitHub release
  tag detected at startup; fire-and-forget, does not block startup
- Fix: AppHelper detection now per-game-version and filesystem-based; reports
  correct addon name per version (-Classic, -Progression, -Anniversary);
  eliminates false positives; warning clears immediately after addon install
- Fix: log viewer opens instantly after long sessions (O(n) row height calculation)
- Fix: Classic Era and Anniversary realm list filtered to active-character realms,
  matching Windows app behavior; reads TradeSkillMaster SavedVariables

* Sun Mar 29 2026 exceptionptr <https://github.com/exceptionptr> - 1.1.3-1
- Change: WoW path storage unified to base directory; game-version paths derived
  on demand. Old configs with _retail_ paths migrated automatically.
- Change: Settings now saves manually typed WoW path on Done; Browse saves single
  base path instead of per-version entries.
- Change: AddonWriterService writes AppData.lua to all installed game versions.
- Change: path utilities consolidated in tsm/wow/utils.py.
- Fix: startup race condition where scan() overwrote config-loaded WoW install
  paths with an empty list; caused persistent AppHelper-not-found warning even
  when the install was correctly configured (closes #3)
- UI: Settings WoW Directory field now shows a hint label (base folder containing
  _retail_, _classic_, etc.) with a path example
- UI: Settings Browse dialog now opens at the currently entered directory
- UI: Login dialog tightened (480x240); subtitle label removed; placeholder
  changed to "Email"
- UI: Login HTTP errors mapped to concise messages (401 -> invalid credentials,
  etc.) instead of exposing raw exception text
- Feature: Log viewer window via new status bar button; styled table with level
  color-coding, row wrapping; Copy to Clipboard redacts email addresses

* Sat Mar 28 2026 exceptionptr <https://github.com/exceptionptr> - 1.1.2-1
- Security: zip extraction validates member paths to prevent zip-slip attacks
- Security: TSM API SSL probed; app-server/data subdomains use HTTP (cert mismatch);
  scripts/check_ssl.py added for re-verification during development
- Fix: login dialog fixed at 480x280; redundant title label removed
- Fix: logging out via Settings closes the dialog before showing login
- Fix: status bar no longer shows AppHelper not found on WoW installs where WoW.exe
  is absent from the game-version directory (common on some Lutris setups)
- Fix: WoW account directory scan now accepts account names with hyphens and dots
- Fix: API client retries on HTTP 429 with Retry-After header support
- Fix: ItemCache read methods hold the internal lock (thread-safety fix)
- Fix: Pydantic config model no longer mutated in place in scheduler
- Fix: subprocess.Popen replaced with subprocess.run in Settings backup folder button
- Chore: asyncio.ensure_future replaced with asyncio.create_task (deprecated)
- Chore: _GAME_VERSIONS deduplicated; accounts.py imports from utils.py
- Chore: job functions typed with ServiceContainer; defensive getattr removed
- Chore: HoverIconButton component consolidates four duplicate hover button classes
- Chore: populate_combo helper added; blockSignals boilerplate removed from views
- Chore: BackupsView._refresh and RealmViewModel._on_data_received made public
- Chore: backup.py run() refactored into focused helper methods
- Chore: scheduler.py protocols typed with concrete model types; Any removed
- Chore: pure CSV helpers extracted to _accounting_utils.py; _setup_ui split
- Chore: RealmViewModel.remove_local() added; view no longer mutates VM internals
- Test: 34 new unit tests for saved_variables, wow_tooltip, item_cache (70 total)

* Fri Mar 27 2026 exceptionptr <https://github.com/exceptionptr> - 1.1.1-1
- Add: WoW auto-detection for Faugus Launcher via games.json prefix paths and ~/Faugus/ subdirectory fallback (Closes: #1)
- Add: --skip-detection, --skip-auto-sync, --skip-auto-backup CLI flags replace --debug
- Add: --version flag; prints version and exits without requiring a display
- Add: CI smoke tests install and run the .rpm on Fedora and openSUSE before release
- Fix: bundle apscheduler 4.x, structlog, and tomli-w under /usr/lib/tsm-app/vendor/ - not packaged on Fedora/openSUSE
- Fix: status bar warning text shown in red for ⚠ messages
- Fix: status bar shows ⚠ AppHelper addon not found when WoW path is set but addon is missing
- Fix: Addon Versions, Backups, and Accounting tabs disabled when WoW not configured
- Fix: auto-detected WoW paths no longer overwrite manually configured paths in config
- Fix: WoW version dir check now looks for WoW executable (case-insensitive) instead of Interface/AddOns
- Fix: Addon Versions tab populated from API data even when AppHelper is not installed
- Fix: WoW path browse scans for _retail_/_classic_ subdirs; raw path no longer stored verbatim (Closes: #2)
- Fix: selecting a version subdir resolves one level up before scanning
- Fix: stale config entries cleared on each browse; prevents duplicate path accumulation
- Fix: settings save immediately pushes valid paths to WoW detector without restart
- Chore: accounting_export.py QEvent isinstance guard replaces type: ignore; fixes CI mypy

* Fri Mar 27 2026 exceptionptr <https://github.com/exceptionptr> - 1.1.0-1
- Add: Addon Versions tab collapsible game-version groups with 180 ms animation, top-aligned
- Add: Addon Versions tab always-visible action buttons (download/refresh/trash) with functional install, update, and uninstall (WTF untouched)
- Add: Addon Versions tab per-row spinner during download
- Add: Addon Versions tab Installed Version and Status dot columns
- Add: Realm Data tab colored status dot (realms 2h/6h, regions 26h/50h thresholds)
- Add: per-row trash icon delete button, always visible, turns red on hover
- Add: inline Add Realm panel at bottom of Realm Data tab
- Add: Refresh Now replaced with icon-only button with dynamic tooltip
- Change: Settings Realms section removed, moved to Realm Data tab
- Change: main window min width 740px, max width constraint removed
- Fix: status bar timestamp now updates on every poll when realm_statuses is empty
- Add: Backups tab per-row restore (green hover) and delete (red hover) icon buttons with confirmations
- Add: Backups tab Name column with ellipsis; bottom name input (alphanum/hyphen/space, max 40); Auto=gray/Manual=orange uniform tags
- Add: Backups tab file size column (KB/MB)
- Add: status bar shows tab-context text; Backups tab shows backup count and total size
- Remove: Addon Versions double-click-to-install replaced by explicit action buttons
- Remove: Backups tab double-click dialog and System ID column removed
- Add: Accounting tab date range filter (From/To QDateEdit with cross-validation, Last 7d/30d/All time)
- Add: Accounting tab full pagination (50 rows/page, prev/next chevron buttons flush left/right)
- Add: Accounting tab item names via Wowhead API with disk cache; spinner while loading, i:ID fallback
- Add: Accounting tab WoW-style item tooltip on hover with quality-colored border and stat block
- Add: Accounting tab gold column sign-colored number, gold g suffix, auto-sized to widest entry
- Add: Accounting tab summary bar with total sales, purchases, net gold, transaction count
- Add: Export to CSV applies date filter; button label shows filtered row count
- Change: "Accounting Export" tab renamed to "Accounting"
- Add: status bar GitHub icon (opens repo) and Settings icon (opens dialog), both white on hover
- Change: status bar text size raised from 10px to 12px
- Remove: footer bar (Premium and GitHub buttons) replaced by status bar icon buttons
- Chore: removed dead write_app_info() from AuctionDataService
- Chore: README sync interval corrected; lua_writer.py docstring fixed; fmt_ts renamed

* Sun Mar 22 2026 exceptionptr <https://github.com/exceptionptr> - 1.0.7-1
- Fix: auction poller checks TSM API on every 5-min poll; removed 60-min cache gate
- Fix: apscheduler dependency changed to >=4.0.0a5 so pip resolves 4.x pre-release
- Chore: ci.yml deleted; tests moved into release.yml as a gate job
- Chore: aur.yml version check prevents duplicate AUR publishes

* Sat Mar 21 2026 exceptionptr <https://github.com/exceptionptr> - 1.0.6-1
- Fix: AppData.lua lastSync no longer goes stale between hourly API calls
- Fix: status bar last-checked timestamp now updates on every 5-min poll
- Chore: AddonWriterService.get_detector() now typed

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
