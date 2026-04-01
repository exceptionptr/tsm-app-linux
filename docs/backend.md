# Backend (Services + Workers)

## Services

### AuthService (`core/services/auth.py`, 110 lines)

- `login(user, pass)` → OIDC token → TSM session → save keyring
- `refresh_token()` → re-auth with stored credentials
- `logout()` → clear keyring, reset session

### AuctionDataService (`core/services/auction.py`)

- `refresh_all_realms()` → `StatusAPI.get()` → diff → download blobs → write Lua → returns `AuctionData`
  - Classic Era / Anniversary realms are filtered to those with active characters (reads
    `TradeSkillMaster.lua` + `TradeSkillMaster_AppHelper.lua` via `get_active_factionrealms()`)
  - Returns `AuctionData(addon_versions=...)` with `last_sync=0` when no WoW dirs found yet
    (prevents false "AppHelper not found" warning during startup detection)
- `get_snapshot()` → `AuctionCache.load_statuses()` → `(list[RealmStatus], int)`
- `add_realm(game_version, realm_id)` → `RealmsAPI.add()`
- `remove_realm(game_version, region, name)` → `RealmsAPI.remove()`
- `_get_existing_app_data_files()` - reads cached `WoWDetectorService.installs` (no scan triggered),
  returns `{gv_dir: [AppDataFile, ...]}` for each game-version directory that exists

### UpdateService (`core/services/updater.py`, 216 lines)

- `check_and_update(addon_versions: list[AddonVersionInfo])` → compares with installed TOC → downloads & installs ZIPs
- `install_or_update_addon(name, version)` → single addon download

### BackupService (`core/services/backup.py`, 287 lines)

- `run(period_minutes, retain_days, extra_installs, keep, name)` → per-account ZIP creation
  - `_purge_old_backups(acct_backups, retain_td)` → returns survivors
  - `_should_skip_backup(keep, acct_backups, modified_times, period_td, account_key)` → bool
  - `_prune_auto_backups(acct_backups)` → keep 9 most recent auto backups
- `restore(backup_path)` → extract ZIP → SavedVariables
- `delete(zip_path)` → unlink

### WoWDetectorService (`core/services/wow_detector.py`, 41 lines)

- `scan()` → `detector.find_wow_installs()` → `list[WoWInstall]`
- `get_installs()` / `set_installs(installs)`

### AddonWriterService (`core/services/addon_writer.py`, 49 lines)

- `write_app_data(data: AuctionData)` → writes AppData.lua per WoW install

## Scheduler (`core/scheduler.py`, ~200 lines)

```
ServiceContainer (dataclass)
  auth: AuthServiceProtocol
  auction: AuctionServiceProtocol
  wow_detector: WoWDetectorProtocol
  updater: UpdateServiceProtocol
  backup: BackupServiceProtocol | None
  config_store: ConfigStoreProtocol | None
  backup_notify_fn: Callable[[str], None] | None
  addon_notify_fn: Callable[[str], None] | None
  auction_data_fn: Callable[[AuctionData], None] | None
  wow_warn_fn: Callable[[str], None] | None

JobScheduler.start() → asyncio.create_task(_scheduler_task())
  Schedules:
    job_auction_refresh  every 5 min  (after 5 min delay)
    job_backup           every N min  (user-configured)
    job_auth_refresh     every 25 min
```

## API Client (`api/client.py`, 326 lines)

```
TSMApiClient
  .auth    AuthAPI    → get_oidc_token(), authenticate(), login()
  .status  StatusAPI  → get(channel, tsm_version) → StatusResponse
  .addon   AddonAPI   → download(name) → bytes
  .realms  RealmsAPI  → list(), add(gv, realm_id), remove(gv, region, realm)

api_request(*parts, data, channel, tsm_version)
  → HMAC token (SHA256 of version:time:SECRET)
  → retry: MAX_RETRIES=3, RETRY_DELAY=2s, exponential
  → 429: respects Retry-After header
  → 4xx (non-429): raise immediately

raw_download(url) → tries HTTPS first, falls back to HTTP
```

## Storage

```
Database (aiosqlite, ~/.local/share/tsm-app/data.db)
  AuctionCache   save_statuses/load_statuses (realm sync state)

ConfigStore     ~/.config/tsm-app/config.toml  (AppConfig, tomli-w)
SecretsStore    keyring service "tsm-app" (username + TSM session token)
```

## Workers

```
AsyncRunner        daemon thread, asyncio event loop, submit(coro) → Future
AsyncBridge        QObject, run(coro) → emits result_ready / error_occurred
jobs.py            job_auction_refresh, job_auth_refresh, job_backup
                   all typed: services: ServiceContainer
```
