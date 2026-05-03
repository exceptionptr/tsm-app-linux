# Changelog

All notable changes to tsm-app-linux are documented here.

---

## [1.1.7] - 2026-05-03

### Fixed

- **Anniversary and Classic Era realm filter restored.**
  The v1.1.6 relaxation ("show all API realms when no active characters found")
  caused the table to flood with all 250+ HC/SoD/Era realms for users who have
  those game versions installed but have not yet logged in. The strict filter is
  back: if no active characters are found in SavedVariables for a game version,
  that version is skipped entirely in the realm list.
- **Debian .deb package now installs app icons to system icon directories.**
  The hicolor icon theme entries (16, 32, 48, 128, 256 px) were missing from
  the `.deb` staging tree; the app icon now appears in desktop launchers and
  task switchers after installing the `.deb`, matching the `.rpm` behavior.

---

## [1.1.6] - 2026-04-22

### Added

- **Anniversary and Classic Era realms now appear in the Add Realm dropdown.**
  The `realms2/list` API only returns Retail and Progression realms. The app
  now also fetches `extraAnniversaryRealms` and `extraClassicRealms` from the
  status endpoint and merges them into the dropdown tree, so Anniversary and
  Classic Era realms can be selected and added.
### Fixed

- **Debian .deb package now targets Ubuntu 26.04+ and installs correctly.**
  Ubuntu 26.04 is the minimum version for the `.deb`: PySide6 is only
  available via apt on 26.04+ (split into individual module packages;
  not present in Ubuntu 24.04 or earlier apt repos at all). Ubuntu 24.04
  users should install via pip - see the README.
  - `python3-pyside6` replaced with the individual module packages
    (`python3-pyside6.qtcore`, `.qtgui`, `.qtnetwork`, `.qtsvg`, `.qtwidgets`).
  - APScheduler 4.x, structlog, and tomli-w are now bundled inside the
    package at `/usr/lib/tsm-app/` (Ubuntu repos only carry APScheduler
    3.x which is incompatible). A shell wrapper sets `PYTHONPATH`
    automatically, matching the approach already used by the RPM package.
  - Entry script now uses `/usr/bin/python3` instead of the pip-generated
    `/usr/bin/python` wrapper (which does not exist on Ubuntu 26.04).
  - Install path is no longer pinned to a specific Python version directory;
    the bundled layout works across all Python 3.x versions.

---

## [1.1.5] - 2026-04-04

### Fixed

- **AppHelper addon folder name corrected for non-retail game versions.**
  The app was looking for `TradeSkillMaster_AppHelper-Progression` (and
  `-Classic`, `-Anniversary`) on disk, but the actual installed folder is
  always named `TradeSkillMaster_AppHelper` regardless of game version -
  confirmed against the Windows reference app. This caused a permanent
  "AppHelper missing" warning for Classic, Classic Era, and Anniversary
  users even when AppHelper was correctly installed.
- **Sync no longer runs for game versions without AppHelper installed.**
  Previously, if a game-version directory existed (e.g. `_classic_/`) but
  AppHelper was not installed there, the app would still download all realm
  data blobs and silently discard them. Now the sync loop skips any game
  version where the AppHelper addon folder is absent, matching Windows app
  behavior.

### Added

- **Addon Versions tab shows WoW installation status per game version.**
  Each group header (Retail, Classic, Progression, Anniversary) now displays
  a grey label indicating whether that game version is installed on disk.

---

## [1.1.4] - 2026-04-01

### Added

- **Update notification in status bar.** At startup the app queries the GitHub
  tags API and shows an amber "New version vX.Y.Z available" label in the status
  bar when a newer release is found. The check runs as a fire-and-forget task and
  does not delay app startup.

### Fixed

- **Log viewer opens instantly** after long sessions. The previous implementation
  used Qt's `ResizeToContents` vertical header mode, which recalculated all row
  heights after every cell insertion (O(n²)). After 8+ hours of running
  (~600-1200 log records) this caused a multi-minute freeze when opening the
  window. Row heights are now calculated once after the table is fully populated.
- **AppHelper detection is now per-game-version and filesystem-based.** The old
  heuristic (empty realm_statuses + non-zero last_sync = AppHelper missing) is
  replaced by a direct check: `write_data()` tests whether the addon folder
  exists for each installed game version and records which are missing. Each
  game version reports its correct addon name in the warning:
  `TradeSkillMaster_AppHelper` for retail, `TradeSkillMaster_AppHelper-Classic`
  for Classic Era, `-Progression` for BCC/Progression, `-Anniversary` for
  Anniversary. False positives at startup are eliminated because the check only
  runs after `write_data()` has had a chance to scan the filesystem.
- **AppHelper warning clears immediately** when the addon is installed via the
  Addon Versions tab. Previously the warning would persist until the next
  5-minute scheduled poll. Installing any addon now triggers an immediate
  `refresh_all_realms()` call that re-evaluates AppHelper presence.
- **Classic Era and Anniversary realm list** now only shows realms the user has
  active characters on, matching Windows app behavior. Previously all
  Classic/Anniversary realms from the user's TSM account were displayed even
  when the user had no characters on those servers. The app reads
  `TradeSkillMaster.lua` and `TradeSkillMaster_AppHelper.lua` SavedVariables to
  determine active faction-realms, hiding game versions with no local characters
  entirely. Retail and Progression realms are unaffected.

---

## [1.1.3] - 2026-03-29

### Changed

- **WoW path storage unified to base directory.** The app now stores and operates
  on the WoW root folder (e.g. `/home/user/Games/world-of-warcraft`) everywhere
  instead of individual game-version subdirectories. Game-version paths
  (`_retail_`, `_classic_`, etc.) are derived on demand. This is a single source
  of truth and eliminates path inconsistencies across services.
- Existing configs that stored game-version paths (e.g. `_retail_`) are
  automatically migrated to the base path on first load. No manual action required.
- Settings dialog now correctly saves a WoW path typed or pasted into the directory
  field when clicking Done. Previously only the Browse button updated the config.
- Settings Browse dialog now saves a single base path instead of multiple
  game-version entries.
- `AddonWriterService` now writes `AppData.lua` to all installed game versions
  under a WoW base directory rather than a single hard-coded version.
- All path utility functions consolidated in `tsm/wow/utils.py`:
  `normalize_wow_base`, `addon_dir`, `apphelper_dir`, `appdata_lua_path`,
  `wtf_accounts_dir`, `installed_versions`.

### Fixed

- Status bar no longer persistently shows "AppHelper not found" on startup for
  users whose WoW install is in config but `WoW.exe` is absent from `_retail_/`
  (or otherwise not found by the auto-scanner). A race condition at startup caused
  `WoWDetectorService.scan()` to overwrite the config-loaded install list with an
  empty result after `_resolve_wow_installs()` had already populated it.
  `scan()` now leaves the install list unchanged when `set_installs()` has already
  been called. Closes #3.

### UI

- Settings: WoW Directory field now shows a hint label explaining that the base
  folder (containing `_retail_`, `_classic_`, etc.) must be selected, with a
  path example.
- Settings: Browse dialog now opens at the currently entered directory instead of
  the home folder.
- Login: removed redundant subtitle label; dialog tightened to 480x240.
- Login: username placeholder changed from "Username or Email" to "Email".
- Login: HTTP error responses are now mapped to concise user-facing messages
  (e.g. 401 → "Invalid email or password.") instead of exposing the raw
  exception string with URL and status details.
- Login: error label always reserves fixed space in the layout so the dialog
  does not shift when an error appears or is cleared.
- **Log viewer** (new): status bar button (between GitHub and Settings) opens a
  session log window. Displays all records from the current run in a styled
  table with columns Time / Level / Logger / Message, alternating row backgrounds,
  and level color-coding (ERROR=red, WARNING=orange). Rows wrap long messages
  and all cells are top-aligned.
- Log viewer: Copy to Clipboard button copies the full session log as plain text
  in the standard log format. Email addresses are automatically redacted before
  copying so logs are safe to paste into GitHub issues.

---

## [1.1.2] - 2026-03-28

### Security

- Zip extraction in `BackupService.restore()` and `UpdateService` now validates
  member paths before extracting, preventing zip-slip path traversal attacks.
- TSM API endpoints probed: only `id.tradeskillmaster.com` (OIDC) has a valid cert.
  All other `*.tradeskillmaster.com` API hosts have a certificate hostname mismatch
  and must use plain HTTP. `scripts/check_ssl.py` added to re-verify this during development.

### Fixed

- Login dialog is now fixed size (480x280 px) and cannot be resized; redundant
  "TradeSkillMaster" title label removed.
- Logging out via Settings now closes the Settings dialog before showing the login
  window instead of leaving it open in the background.
- Status bar no longer shows "⚠ TradeSkillMaster_AppHelper addon not found" on WoW
  installs where `WoW.exe` is absent from the game-version directory (common on some
  Lutris setups). The AppData.lua reader now only requires the game-version directory
  to exist rather than a WoW executable, matching the writer's behavior.
- WoW account directory scan now accepts account names containing hyphens and dots,
  which are valid in some localized WoW installs.
- `ItemCache.get()`, `get_name()`, and `ensure_fetched()` now hold the internal lock
  while reading `_data`, preventing data races with the background fetch thread.
- `cfg.wow_installs = found` in the scheduler replaced with immutable
  `model_copy(update=...)` - Pydantic models must not be mutated in place.
- `subprocess.Popen` in the Settings backup-folder button replaced with
  `subprocess.run(check=False)` with return-code logging.

### Changed

- API client retries on HTTP 429 (rate-limited) responses, honouring the
  `Retry-After` header when present, instead of raising immediately.
- `asyncio.ensure_future()` replaced with `asyncio.create_task()` in the scheduler
  (the former is deprecated in Python 3.10+).

### Chore

- `_GAME_VERSIONS` constant deduplicated: `accounts.py` now imports it from
  `utils.py` instead of redefining it.
- Scheduled job functions are now typed with `ServiceContainer` and the defensive
  `getattr()/callable()` guards are replaced with direct `is not None` checks.
- Hover icon button logic consolidated into `HoverIconButton` in
  `tsm/ui/components/hover_button.py`; four duplicate inner classes removed.
- `populate_combo()` helper added to `tsm/ui/views/_utils.py`; `blockSignals`
  boilerplate replaced across `realm_data.py` and `accounting_export.py`.
- `BackupsView._refresh()` and `RealmViewModel._on_data_received()` renamed to
  public slots; `app_window.py` no longer calls private methods on child objects.
- `backup.py run()` split into `_purge_old_backups()`, `_should_skip_backup()`,
  and `_prune_auto_backups()` helpers; the loop body is now a readable outline.
- Protocol `Any` types replaced with concrete model types (`AuctionData`,
  `RealmStatus`, `AddonVersionInfo`, `WoWInstall`, `AppConfig`, `Path`) in
  `scheduler.py`; `Any` import removed entirely.
- `RealmViewModel.summaries.pop(row)` in `realm_data.py` replaced with a new
  `remove_local(row)` method - views should not mutate ViewModel internals directly.
- Pure CSV/data functions extracted from `accounting_export.py` into
  `tsm/ui/views/_accounting_utils.py` for testability; `_setup_ui()` split into
  `_build_*` helper methods; stray `import contextlib` moved to module top.
- Unit tests added: `test_saved_variables.py`, `test_wow_tooltip.py`,
  `test_item_cache.py` (34 new tests, 70 total).

---

## [1.1.1] - 2026-03-27

### Added

- WoW auto-detection: Faugus Launcher prefixes scanned automatically via
  `~/.config/faugus-launcher/games.json` and `~/Faugus/` subdirectory fallback.
  Closes #1.
- Debug CLI flags: `--skip-detection`, `--skip-auto-sync`, `--skip-auto-backup`
  replace the removed `--debug` flag, allowing targeted bypassing of individual
  startup phases without altering the sync interval.
- `--version` flag: prints the app version and exits without starting the GUI or
  requiring a display.
- RPM package now bundles `apscheduler` (4.x), `structlog`, and `tomli-w` under
  `/usr/lib/tsm-app/vendor/` - these are not packaged in Fedora or openSUSE repos.
  The entry point injects the vendor path automatically; no manual `pip install`
  needed after installing the `.rpm`.
- CI: install-and-run smoke tests for the `.rpm` on Fedora and openSUSE Tumbleweed,
  and for the `.deb` on Ubuntu. Release is blocked until all three pass.

### Fixed

- Status bar warning text (`⚠ ...`) is now shown in red, making misconfiguration
  states easier to spot at a glance.
- Status bar now shows `⚠ TradeSkillMaster_AppHelper addon not found` when a valid
  WoW path is configured but the AppHelper addon is missing, instead of silently
  showing "Up to date as of X".
- Addon Versions, Backups, and Accounting tabs are now disabled (and navigation
  redirected to Realm Data) when no valid WoW directory is configured.
- Auto-detected WoW paths no longer overwrite manually configured paths in config.
  Auto-detection only writes to config when the stored install list is empty.
- WoW game-version directory validation now checks for the WoW executable
  (`Wow.exe` / `WowClassic.exe`, case-insensitive) instead of requiring
  `Interface/AddOns` to exist. Fresh installs without any addons are now detected
  correctly.
- Addon Versions tab is now populated from API data even when AppHelper is not
  installed. Previously `addons_updated` was never emitted when no realm statuses
  were returned, leaving the tab empty.
- WoW path detection: browsing for a custom install in Settings now scans the selected
  folder for version subdirectories (`_retail_`, `_classic_`, etc.) the same way
  auto-detection does. Previously the raw folder path was stored verbatim, causing
  downstream lookups (AppHelper, addon writer, backup) to search the wrong location.
- WoW path detection: selecting a version subdirectory directly (e.g. `_retail_`) now
  resolves one level up so the correct base is scanned. Invalid selections (no version
  dirs found) show a descriptive error message.
- WoW path detection: stale/duplicate config entries are cleared on each browse,
  preventing accumulation of wrong paths (caused the two-entry config in issue #2).
- WoW path detection: saving Settings now immediately pushes valid config paths into
  the WoW detector, so the next poll uses the correct paths without a restart.

### Chore

- `accounting_export.py`: replaced `# type: ignore` pair on `QEvent` cast with a
  proper `isinstance(event, QMouseEvent)` guard; fixes mypy `unused-ignore` error in CI.

---

## [1.1.0] - 2026-03-27

### Added

- Addon Versions tab: collapsible game-version groups (Retail, Classic, Progression,
  Anniversary). Each group header shows an expand/collapse arrow, the group name, and
  an installed summary ("2 installed" / "not installed"). Groups auto-expand on first
  load when any addon is installed; subsequent collapse/expand is manual with a 180 ms
  animation. Groups are top-aligned with a fixed collapsed height.
- Addon Versions tab: per-row action buttons always visible - download icon for
  not-installed addons (installs fresh into the correct game version directory), refresh
  icon for addons with an update available (downloads and replaces), trash icon for
  up-to-date addons (confirms then deletes the addon folder; WTF directory is never
  touched). Icons turn green/orange/red on hover respectively.
- Addon Versions tab: rotating loader-circle spinner replaces the action button while
  a download is in progress. Multiple simultaneous downloads each show their own
  spinner independently.
- Addon Versions tab: Installed Version column and Status column with colored dot
  ("Up to date" green, "Update available" amber, "Not installed" gray).
- Realm Data tab: colored status dot next to AuctionDB text replaces colored text.
  Realms: green under 2 h, yellow 2-6 h, red over 6 h. Regions use wider thresholds
  (green under 26 h, yellow 26-50 h, red over 50 h) matching the ~daily
  AUCTIONDB_REGION_STAT update cadence (MAX_DATA_AGE = 86400 in original app).
  "Updating..." shows yellow; "Outdated" shows red for both.
- Realm Data tab: per-row trash icon delete button (always visible) replaces
  double-click-to-delete. Icon turns red on hover.
- Realm Data tab: inline "Add Realm" panel at the bottom (game version, region,
  and realm dropdowns plus a button). Realm list is pre-fetched on login and
  session restore and pushed to the view via `set_realm_tree()`.
- Realm Data tab: Refresh Now replaced with an icon-only button (refresh-cw.svg).
  Tooltip is dynamic: shows countdown when rate-limited, syncing state during fetch.
- Backups tab: per-row restore button (archive-restore icon, turns green on hover) and
  delete button (trash icon, turns red on hover) with confirmation dialogs.
- Backups tab: Name column showing the optional custom name with automatic ellipsis when
  the column is too narrow. Name input in the bottom panel (matching Realm Data layout)
  validates to alphanumeric, spaces, hyphens, and underscores only; max 40 characters.
  The name is embedded in the filename (`{sys_id}_{account}_{ts}_{name}.zip`).
- Backups tab: Auto/Manual type tag column with uniform fixed-width bordered labels;
  Auto = gray, Manual = orange.
- Backups tab: file size column (KB or MB).
- Status bar shows tab-context text: Backups tab shows "N backups stored - X total";
  all other tabs show the normal "Up to date as of..." message.
- Accounting tab: date range filter row with From/To `QDateEdit` pickers (chevron icon,
  cross-validation blocks from > to) and "Last 7d", "Last 30d", "All time" quick-select
  buttons. Default range is last 30 days.
- Accounting tab: preview table shows all filtered rows sorted by date with pagination
  (50 rows per page). Prev/next chevron buttons are flush left/right; page indicator is
  centered. Row count label shows total matching rows.
- Accounting tab: item names resolved via Wowhead tooltip API with persistent disk cache
  (`~/.local/share/tsm-app/item_cache.json`). Braille spinner shown while loading; falls
  back to `i:ID` on failure. Plain-text entries (e.g. "Repair Bill") shown as-is without
  a fetch attempt.
- Accounting tab: WoW-style item tooltip on row hover (500 ms delay) with quality-colored
  border and full stat block parsed from Wowhead tooltip HTML (money spans, item quality
  colors, sell price).
- Accounting tab: gold column number colored green (income) or red (expense); `g` suffix
  colored gold (#f0c040). Column width sized to the widest entry on the current page.
- Accounting tab: summary bar (dark green-tinted panel) showing total sales, total
  purchases, net gold, and transaction count for the filtered data.
- Accounting tab: Export to CSV applies the date filter and writes per-type CSV files
  with original headers; button label shows the filtered row count.
- Status bar: GitHub icon button (right of settings) opens the project repository;
  Settings icon button (rightmost) opens the Settings dialog. Both icons swap to white
  on hover. Status bar text size raised from 10 px to 12 px.

### Changed

- Settings > General: Realms section removed; realm management now lives in the
  Realm Data tab inline panel.
- Main window minimum width raised from 620 px to 740 px; maximum width constraint
  removed.
- "Accounting Export" tab renamed to "Accounting".

### Fixed

- Status bar "Up to date as of" timestamp now updates on every 5-min poll even when
  no new realm data is available. Previously `_on_data_received` only wrote `_last_sync`
  when `realm_statuses` was non-empty; polls that returned an empty statuses list
  (AppHelper not yet detected, etc.) left the timestamp frozen at the last successful
  refresh.

### Removed

- Addon Versions tab: double-click-to-install replaced by explicit always-visible
  per-row action buttons.
- Addon Versions tab: bottom hint label removed.
- Backups tab: double-click dialog replaced by per-row restore/delete icon buttons.
- Backups tab: System ID column removed (not useful to the user).
- Footer bar (Premium and GitHub buttons) removed; replaced by status bar icon buttons.

### Chore

- Removed dead `AuctionDataService.write_app_info()` method; all call sites were
  removed in 1.0.7 but the method body was not
- README: sync interval corrected from "60 minutes" to "5 minutes (differential)"
- `lua_writer.py` docstring corrected: APP_INFO uses `[[return ...]]` wrapping like
  all other tags; `RAW_TAGS` is an empty reserved set, not used by APP_INFO
- `realm_vm.py`: `_STALE_SECONDS` comment updated to reflect that it is a
  startup-only snapshot staleness threshold, not tied to the poll interval
- Renamed `_fmt_ts` to `fmt_ts` in `realm_data.py`; was being imported as a private
  function from another module

---

## [1.0.7] - 2026-03-22

### Fixed

- `job_auction_refresh` now calls `refresh_all_realms()` on every 5-min poll instead
  of gating on a 60-min local-cache age. TSM publishes new realm data independently of
  our local cache; the old threshold meant updates could be missed for up to 60 minutes.
  `refresh_all_realms()` is already differential (status endpoint + per-tag
  `lastModified` comparison) so only changed blobs are downloaded each poll.
- `apscheduler` dependency specifier changed from `>=4.0.0` to `>=4.0.0a5`: pip
  excludes pre-releases when the lower bound is a stable version, causing CI installs
  to fail since no stable 4.x release exists yet.

### Chore

- `ci.yml` deleted; test matrix (ruff, mypy, pytest on 3.11/3.12/3.13) moved into
  `release.yml` as a gate job that all build jobs depend on
- `aur.yml` now checks the AUR RPC API before publishing and skips if AUR is already
  at the target version, preventing duplicate publishes

---

## [1.0.6] - 2026-03-21

### Fixed

- `AppData.lua` `lastSync` field no longer goes stale between hourly API calls:
  `job_auction_refresh` now calls `AuctionDataService.write_app_info()` on every
  5-min poll when cached data is still fresh, keeping the in-game "data age" indicator
  accurate without hitting the API
- Status bar "last checked" timestamp now updates on every 5-min poll even when no
  API call is made: the fresh path constructs an `AuctionData` from the cached realm
  snapshot with the current time and calls `auction_data_fn` so `RealmViewModel`
  updates `_last_sync`

### Chore

- `AddonWriterService.__init__` and `get_detector()` now carry proper type annotations;
  removes the last `no-untyped-call` mypy error in strict-typed callers

---

## [1.0.5] - 2026-03-20

### Removed

- Dead file `tsm/ui/components/realm_row.py` (`RealmRowWidget` was never used)
- Dead method `WoWDetectorService.add_custom_path()` (never called)
- Unused DB tables `addon_versions` and `sync_history` removed from schema
  and migrations

### Fixed

- `AppData.lua` `lastSync` field no longer goes stale between hourly API calls:
  `job_auction_refresh` now calls `AuctionDataService.write_app_info()` on every
  5-min poll when cached data is still fresh, keeping the in-game "data age" indicator
  accurate without hitting the API
- Status bar "last checked" timestamp now updates on every 5-min poll even when no
  API call is made: the fresh path constructs an `AuctionData` from the cached realm
  snapshot with the current time and calls `auction_data_fn` so `RealmViewModel`
  updates `_last_sync`
- `assert self._db is not None` in `database.py` replaced with a proper
  `RuntimeError` (assert can be silenced with `-O`)
- Silent `except Exception: pass` on backup purge now logs a `WARNING`
- `asyncio.get_event_loop()` replaced with `asyncio.get_running_loop()` in
  `jobs.py`, `wow_detector.py`, and `app_window.py` (deprecated in Python 3.12)
- `auction.py` no longer accesses `addon_writer._detector` directly; uses the
  new public `AddonWriterService.get_detector()` method instead
- All external `getattr(x, "_installs", [])` accesses replaced with the new
  public `WoWDetectorService.installs` property and the delegating
  `AddonWriterService.installs` property
- `SettingsDialog._logout_reset()` no longer pokes `self._vm._config` directly;
  uses the new `SettingsViewModel.reset_to_defaults()` method
- Late imports at the bottom of `scheduler.py` moved to the top (no actual
  circular dependency existed)
- `__main__.py` no longer reaches into `window._app_vm`, `window._settings_vm`,
  and `window._realm_vm` directly; uses the new `AppWindow.on_authenticated()`
  method instead
- `app_window.py` line 111 now connects to public `AccountingExportView.populate`
  instead of the private `_populate`
- Backup delete in `BackupsView` now calls `BackupService.delete()` instead of
  calling `zip_path.unlink()` directly in the view
- README WoW detection frequency corrected: detection runs at startup only, not
  every 5 minutes

### Added

- `WoWDetectorService.installs` - public property returning the cached install list
- `AddonWriterService.get_detector()` and `installs` - public API on the writer
- `SettingsViewModel.reset_to_defaults()` - resets config and persists in one call
- `AppWindow.on_authenticated(session)` - encapsulates post-login window setup
- `AccountingExportView.populate()` - renamed from `_populate` (public slot)
- `BackupService.delete(zip_path)` - file deletion belongs in the service layer
- `tsm/ui/views/_utils.py` with shared helpers:
  - `set_table_cell()` - replaces the duplicated `_set_cell()` methods in
    `realm_data.py` and `backups.py`
  - `start_rate_limit_countdown()` - replaces the duplicated countdown timer
    pattern in `realm_data.py` and `backups.py`
  - `build_realm_tree()` - replaces the duplicated API response parsing in
    `app_window.py` and `settings.py`
- `tsm/wow/utils.py` with `iter_wow_gv_roots()` - replaces the duplicated
  installs x game-version directory loops in `updater.py` and `backup.py`
- `tsm/wow/accounts.py` gains `scan_tsm_accounts()` and `scan_realm_names()`,
  moved from inline functions in `accounting_export.py`
- `packaging/debian/ci-depends` - single source of truth for concrete package
  deps used in CI (no dpkg substitution variables); both the `.deb` control
  file step and the `.rpm` fpm flags now read from this file

### Changed

- `apscheduler` dependency constraint updated from `>=4.0.0a5` to `>=4.0.0,<5`
  (APScheduler 4.0 stable has released)
- `packaging/debian/control` - added missing runtime deps: `python3-pydantic`,
  `python3-aiosqlite`, `python3-apscheduler`, `python3-structlog`,
  `python3-tomli-w`, `python3-yaml`
- `release.yml` `.deb` and `.rpm` steps now derive deps from `ci-depends`
  instead of each maintaining their own hardcoded list
- `tsm/core/scheduler.py`: `ServiceContainer` fields typed with six Protocol
  classes (`AuctionServiceProtocol`, `AuthServiceProtocol`, `UpdateServiceProtocol`,
  `ConfigStoreProtocol`, `WoWDetectorProtocol`, `BackupServiceProtocol`) instead
  of `object`, enabling mypy to validate method calls in `jobs.py` and `scheduler.py`

### Tests

- `tests/integration/test_scheduler.py` rewritten: uses a real `ServiceContainer`
  with mocked services, calls `start()`/`stop()`, and asserts scheduler lifecycle
  and idempotency
- `tests/conftest.py`: removed the redundant `event_loop` fixture (superseded by
  `asyncio_mode = "auto"` in pyproject.toml)
- `tests/unit/test_config_store.py` (new): covers load defaults, TOML parsing,
  corrupt TOML fallback, save round-trip, and parent directory creation
- `tests/unit/test_wow_detector_service.py` (new): covers empty initial state,
  set_installs, get_installs cache hit/miss, and scan() executor call
- `tests/unit/test_backup_service.py` (new): covers delete success/missing,
  restore bad filename, \_list_backups parsing, \_find_sv_files glob, and
  run() with no accounts
- `tests/unit/test_addon_writer.py` (new): covers write_data with no detector,
  missing addon dir, and successful LuaWriter call
- `tests/unit/test_auction_cache.py`: added snapshot save/load round-trip and
  missing snapshot returns empty tests

### CI

- Python 3.13 added to the CI test matrix (`python-version` in `ci.yml`)

### Chore

- Fixed syntax error in `app.py`: `impot` typo corrected to `import`
- `auction.py`: `realm["name"]` changed to `realm.get("name", "")` - `name` is
  optional in `RealmEntry` TypedDict
- Removed unused `_SUFFIX_TO_GV` dict from `updater.py` and `_GAME_VERSIONS`
  tuple from `backup.py`
- Removed unused `Qt` import from `realm_data.py`; `Generator` moved to
  `collections.abc` in `utils.py` (UP035)
- `app_window.py`: captured `backup_service` local before lambda to narrow
  Optional type; renamed `*_args` to `*_` in signal handlers
- `settings.py`: renamed `_index` to `_` in two combo-box signal handlers
- `__main__.py`: `_async_runner` renamed to `_` (conventional discard for
  tuple-unpacking a value kept alive only by the blocking `exec()` call)
- `__init__.py`: added `# type: ignore[import-not-found]` on `_version` import
  (file is generated at build time by hatch-vcs)

---

## [1.0.4] - 2026-03-19

### Fixed

- Last Updated column in the Realm Data tab now correctly shows the primary tag
  timestamp (AUCTIONDB_NON_COMMODITY_DATA for realms, AUCTIONDB_REGION_STAT for
  regions). Previously, when secondary tags were downloaded but the primary tag
  was unchanged, a max() fallback wrote a wrong timestamp into the snapshot;
  this caused the column to show the wrong time until the next manual refresh.
- Tray notification text trimmed to "{n} realm(s)/region(s) updated."

### Added

- Reverse-engineered TSM API reference document (API.md) covering auth flow,
  all endpoints, AppData download flow, tags, and scheduled job intervals.

### CI

- softprops/action-gh-release bumped to v2.3.2 (Node.js 24 compatible)
- AUR publishing extracted from release.yml into a separate aur.yml workflow
  triggered manually via workflow_dispatch

---

## [1.0.3] - 2026-03-18

### Fixed

- Realm list no longer clears when WoW install or AppHelper is not detected
  during a refresh; existing rows are kept with reset status labels
- Closing via tray Quit no longer shows a double confirmation dialog
- Config no longer silently mutated when quitting via tray

### Added

- Timestamps on all log output
- Log file with rotation at ~/.local/share/tsm-app/logs/tsm-app.log,
  retaining the last 5 backups

### Chore

- Removed em-dashes from source comments and strings
- Cleaned up PKGBUILD comments

---

## [1.0.2] - 2026-03-18

### Fixed

- CI workflows now only trigger on the main branch
- Reverted softprops/action-gh-release to v2 to fix GitHub Release upload crash

---

## [1.0.1] - 2026-03-18

### Fixed

- Closing window with confirmation now quits the app instead of hiding to tray
- Prevent multiple simultaneous instances; second launch shows "already running"
  dialog instead of opening a second window
- APScheduler 4.x (AsyncScheduler) bundled correctly for Arch; the system
  package is 3.x which is not compatible
- App icon now installed to the hicolor theme so it appears in desktop launchers

### CI

- GitHub Actions bumped to Node.js 24 runtime

---

## [1.0.0] - 2026-03-17

Initial release.
