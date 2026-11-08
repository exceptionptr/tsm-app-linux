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
│  Services: Auth, Auction, Sync, Backup, Updater     │
│        ↕                                            │
│  TSM REST + socket │ SQLite (aiosqlite) │ Files     │
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
    client.py         TSMApiClient: Bearer REST (realms, regions, user-realms), downloads
    oidc.py           Keycloak browser login (PKCE), refresh, revoke
    socket.py         TSMSocket: minimal Socket.IO v4 push client
    types.py          TypedDicts for REST and socket payloads

  core/
    scheduler.py      JobScheduler (APScheduler 4.x), ServiceContainer, Protocols
    models/           Pydantic models: AuctionData, RealmStatus, AppConfig, WoWInstall
    services/         Domain services (async): Auth, Auction, Sync, Updater, Backup, WoWDetector

  storage/
    database.py       aiosqlite wrapper
    auction_cache.py  RealmStatus persistence (SQLite)
    config_store.py   AppConfig → ~/.config/tsm-app/config.toml
    secrets.py        keyring-backed refresh token store

  workers/
    async_runner.py   Daemon thread running asyncio loop
    bridge.py         AsyncBridge: runs coroutines, emits result_ready/error_occurred signals
    jobs.py           APScheduler job functions (check_update, backup)

  wow/
    game_versions.py  GAME_VERSIONS: the one table of client folders, keys, labels, suffixes
    detector.py       WoW install detection (Wine, Lutris, Steam, Bottles, Faugus, ~/Games)
    accounts.py       WTF account/realm scanning
    lua_writer.py     AppDataFile: AppData.lua parser and atomic writer
    saved_variables.py  SV file reader
    utils.py          is_valid_wow_version_dir, iter_wow_gv_roots

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
JobScheduler start → SyncController.start()
  → AuctionDataService.start(user_id): catalogue, followed realms, migration
  → TSMSocket connects (Authorization: access token)
server pushes realm_auctiondb / realm_shopping / region_auctiondb
  → AuctionDataService.handle_event()
  → followed and newer? → TSMApiClient.download(url)
  → queued, debounced 1.5 s → AppDataFile per game version → AppData.lua
  → snapshot() saved to SQLite → listeners
  → AppViewModel.realm_data_received → RealmViewModel → RealmDataView
server pushes addon → UpdateService.check_and_update()
server pushes app_info → APP_INFO rewritten
```

## Auth Flow

```
LoginView "Sign in with browser" → AuthService.login()
  → oidc.browser_login(): system browser, localhost callback, code + PKCE
  → secrets.store_credentials(username, refresh token) (keyring)
  → AppViewModel.authenticated_changed → JobScheduler.start()
SyncController refresh loop → AuthService.refresh_token() 90 s before expiry
  → token listeners → socket reconnects if it was down
Refresh rejected → session_lost → back to LoginView
```
