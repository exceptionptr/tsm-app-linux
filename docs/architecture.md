# Architecture

Single-process Linux desktop app (PySide6 GUI + asyncio background loop).

## System Overview

```
┌─────────────────────────────────────────────────────┐
│  Qt Main Thread                                     │
│  AppWindow → views → viewmodels                     │
│        ↕ AsyncBridge (signal/slot bridge)           │
│  AsyncRunner (daemon thread + asyncio event loop)   │
│        ↕                                            │
│  Services: Auth, Auction, Backup, Updater           │
│        ↕                                            │
│  TSM API (HTTP) │ SQLite (aiosqlite) │ Filesystem   │
└─────────────────────────────────────────────────────┘
```

## Entry Points

- `tsm/__main__.py` - CLI: `--version`, `--skip-detection`, `--skip-auto-sync`, `--skip-auto-backup`
- `tsm/app.py:create_app()` - DI root: wires all services, returns `(QApplication, AppWindow, AsyncRunner, AuthService)`

## Layer Map

```
tsm/
  __main__.py         CLI + arg parsing
  app.py              DI wiring (create_app)

  api/
    client.py         TSMApiClient + sub-APIs (Auth, Status, Addon, Realms)
    types.py          TypedDicts: OIDCTokenResponse, StatusResponse, AddonVersionInfo

  core/
    scheduler.py      JobScheduler (APScheduler 4.x), ServiceContainer, Protocols
    models/           Pydantic models: AuctionData, RealmStatus, AppConfig, WoWInstall
    services/         Domain services (async): Auth, Auction, Updater, Backup, WoWDetector, AddonWriter

  storage/
    database.py       aiosqlite wrapper
    auction_cache.py  RealmStatus persistence (SQLite)
    config_store.py   AppConfig → ~/.config/tsm-app/config.toml
    secrets.py        keyring-backed credential store

  workers/
    async_runner.py   Daemon thread running asyncio loop
    bridge.py         AsyncBridge: runs coroutines, emits result_ready/error_occurred signals
    jobs.py           APScheduler job functions (auction_refresh, auth_refresh, backup)

  wow/
    detector.py       WoW install detection (filesystem + Faugus Launcher)
    accounts.py       WTF account/realm scanning
    lua_writer.py     AppData.lua serialiser (LoadData format)
    saved_variables.py  SV file reader
    utils.py          _GAME_VERSIONS, is_valid_wow_version_dir, iter_wow_gv_roots

  ui/
    app_window.py     AppWindow (QMainWindow): tab bar, stack, tray, login flow
    components/       HoverIconButton, TSMStatusBar, ProgressWidget, WoWTooltip
    viewmodels/       AppViewModel, RealmViewModel, SettingsViewModel
    views/            RealmDataView, AddonVersionsView, BackupsView,
                      AccountingExportView, LoginView, SettingsDialog
    styles/           Dark theme QSS loader
```

## Data Flow: Auction Sync

```
JobScheduler (every 5 min)
  → job_auction_refresh(services)
  → AuctionDataService.refresh_all_realms()
  → TSMApiClient.status.get() → diff lastModified per realm
  → TSMApiClient.raw_download(url) for changed blobs
  → AuctionCache.save_statuses() (SQLite)
  → AddonWriterService.write_app_data() → AppData.lua
  → ServiceContainer.auction_data_fn(AuctionData)
  → AppViewModel.realm_data_received signal
  → RealmViewModel.on_data_received() → data_updated signal
  → RealmDataView._refresh()
```

## Auth Flow

```
LoginView → AuthService.login(user, pass)
  → TSMApiClient.auth.get_oidc_token() (Keycloak)
  → TSMApiClient.auth.authenticate(access_token)
  → secrets.save_credentials() (keyring)
  → AppViewModel.authenticated_changed → JobScheduler.start()
```
