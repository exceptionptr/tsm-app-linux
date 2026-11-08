# Backend (Services + Workers)

The protocol itself is described in [api.md](api.md).

## Services

### AuthService (`core/services/auth.py`)

- `login(remember_me, open_url, on_url)` → browser sign-in (`api/oidc.py`, PKCE on
  a localhost port) → stores the offline refresh token in the keyring
- `restore_session()` → refreshes with the stored token on start. Waits through a
  missing network or keyring (`RESTORE_RETRY_DELAYS`, about two minutes); a
  rejected token returns False at once. Sets `migrated_from_password` when only a
  password from the old username/password login is found, so the login view can explain why.
- `access_token()` → the current access token, refreshed first when it expires
  within 90 s. Registered as the API client's token provider.
- `refresh_token(force)`, `seconds_until_refresh()`
- `add_token_listener(fn)` (new token), `add_session_lost_listener(fn)` (refresh
  token rejected: session cleared, credentials deleted)
- `logout()` → forget and revoke

### AuctionDataService (`core/services/auction.py`)

Event driven: the socket pushes data, this service decides what to download and
writes it.

- `load_catalog(refresh)` → realms, regions and game version labels. Served from
  the `api_cache` table first, then the network.
- `start(user_id)` / `stop()`; `start` also runs the 15 minute APP_INFO loop
- `load_user_realms()` → the account's followed realms; prunes AppData entries
  for realms no longer followed
- `add_realm(realm_id, ah_type, limit)` (raises `RealmLimitReached`),
  `remove_realm(user_realm_id)`
- `migrate_local_realms()` → moves realms added locally by the old client
  (SQLite table `user_added_realms`) to the account once
- `handle_event(name, payload)` → for realm and region strings: skip if not
  followed or not newer, download (4 at a time), queue a write. Writes are
  debounced by `WRITE_DEBOUNCE_SECONDS` and applied per file in a thread.
- `write_app_info()`, `flush_all()`
- `snapshot()` → `AuctionData` for the UI, also saved to SQLite;
  `get_snapshot()` loads the saved one at start
- `realm_tree()` → `{label: {region_key: [{realm_id, ah_type, name, game_version}]}}`
  for the Add Realm dropdown
- `add_listener(fn)`, `add_addon_listener(fn)`

AppData.lua is only written for game versions where TradeSkillMaster or the
AppHelper is installed; `AuctionData.apphelper_missing_gv` lists the rest.

### SyncController (`core/services/sync.py`)

Owns the socket and ties the services together for one signed-in session.

- `start()` → starts the token refresh loop, `auction.start()` (which also runs
  the legacy realm migration), opens the `TSMSocket`. The refresh loop (sleeps until `seconds_until_refresh()`, retries
  every 30 s on failure)
- On connect: reloads the followed realms. On a new token while disconnected:
  reconnects at once.
- On `addon` events: `updater.check_and_update(releases)` and a notification
- `stop()`

### UpdateService (`core/services/updater.py`)

- `check_and_update(releases)` → for each release, updates the addon in every
  game version where it is already installed and older. One multi-toc zip covers
  all game versions.
- `install_or_update_addon(name_with_suffix, version)` → manual install from the
  Addon Versions tab
- git checkouts and `@project-version@` tocs are never touched

### BackupService (`core/services/backup.py`)

- `run(period_minutes, retain_days, extra_installs, keep, name)` → per-account ZIP creation
  - `_purge_old_backups(acct_backups, retain_td)` → returns survivors
  - `_should_skip_backup(keep, acct_backups, modified_times, period_td, account_key)` → bool
  - `_prune_auto_backups(acct_backups)` → keep 9 most recent auto backups
- `restore(backup_path)` → extract ZIP → SavedVariables
- `delete(zip_path)` → unlink

### WoWDetectorService (`core/services/wow_detector.py`)

- `scan()` → `detector.find_wow_installs()` → `list[WoWInstall]`
- `get_installs()` / `set_installs(installs)`

## Scheduler (`core/scheduler.py`)

```
ServiceContainer (dataclass)
  auth, auction, wow_detector, updater
  sync: SyncControllerProtocol | None
  backup, config_store
  backup_notify_fn, addon_notify_fn, wow_warn_fn

JobScheduler.start() → asyncio.create_task(_scheduler_task())
  resolves WoW installs, then sync.start() (unless --skip-auto-sync)
  Schedules:
    job_check_update   once at start (GitHub release check)
    job_backup         every N min (user-configured)
JobScheduler.stop() → sync.stop(), scheduler shutdown
```

Auction data and token refresh are no longer polled jobs: data arrives over the
socket and `SyncController` refreshes the token on its own timer.

## API (`api/`)

```
TSMApiClient (client.py)
  request(method, url, params, json_body)   Bearer token, retries 5xx/408/429
  realms(), regions(), game_versions(), release_channel_labels()
  user_realms(user_id), add_user_realm(...), delete_user_realm(id)
  download(url)   presigned, gunzips, None on 404

TSMSocket (socket.py)    minimal Socket.IO v4 client on aiohttp
oidc.py                  browser_login, refresh, revoke, Tokens
```

## Storage

```
Database (aiosqlite, ~/.local/share/tsm-app/data.db, schema 5)
  AuctionCache   realm status snapshot, followed realms, api_cache (JSON)

ConfigStore     ~/.config/tsm-app/config.toml  (AppConfig, tomli-w)
secrets.py      keyring service "tsm-app": username + refresh token
```

## Workers

```
AsyncRunner        daemon thread, asyncio event loop, submit(coro) → Future
AsyncBridge        QObject, run(coro) → emits result_ready / error_occurred, returns the Future
jobs.py            job_check_update, job_backup
```
