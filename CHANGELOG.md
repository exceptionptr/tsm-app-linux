# Changelog

All notable changes to tsm-app-linux are documented here.

---

## [Unreleased]

### Added

- WoW auto-detection: Faugus Launcher prefixes scanned automatically via
  `~/.config/faugus-launcher/games.json` and `~/Faugus/` subdirectory fallback.
  Closes #1.

### Fixed

- Status bar warning text (`⚠ ...`) is now shown in red, making misconfiguration
  states easier to spot at a glance.
- Status bar now shows `⚠ TradeSkillMaster_AppHelper addon not found` when a valid
  WoW path is configured but the AppHelper addon is missing, instead of silently
  showing "Up to date as of X".

---

## [1.1.1] - 2026-03-27

### Fixed

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
  restore bad filename, _list_backups parsing, _find_sv_files glob, and
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
