# Data Models & Storage

## Pydantic Models (`core/models/`)

```
AppConfig (config.py)
  wow_installs: list[WoWInstall]
  minimize_to_tray, notifications_enabled, notify_realm_data,
  notify_addon_update, notify_backup, start_minimized,
  show_confirmation_on_exit: bool
  backup_period_minutes: int = 60
  backup_retain_days: int = 30

WoWInstall (config.py)
  path: str, version: str  ("_retail_" | "_classic_" | "_classic_era_" | "_anniversary_" | "_forever_")

AuctionData (auction.py)
  app_info: AppInfo | None
  realm_statuses: list[RealmStatus]
  addon_versions: list[AddonVersionInfo]
  written: int                         entries written in the last flush
  apphelper_missing_gv: list[str] | None
  last_sync: int  (property)

RealmStatus (auction.py)
  display_name, is_region, auctiondb_status, last_updated: int
  game_version (GameVersion.key), region (AppData region key), name (AppData realm key)
  user_realm_id, realm_id, auction_house_type ("ALL" | "HORDE" | "ALLIANCE")
  server_last_modified: int

AppInfo (auction.py)
  version, last_sync, message_id, message_text, news

UserSession (auth.py)
  username, user_id (OIDC sub), premium_tier, release_channels, remember_failed
  realm_limit (property): None for platinum, 25 gold, 10 free
```

## SQLite (`~/.local/share/tsm-app/data.db`)

Managed by `storage/database.py` (aiosqlite).

```
AuctionCache (storage/auction_cache.py)
  save_statuses(statuses: list[RealmStatus], saved_at: int)
  load_statuses() → (list[RealmStatus], int)
  put_json(key, value) / get_json(key)    api_cache: catalogue responses
  get_all_user_realms()                   legacy local realms, read once for migration
Schema version 5
```

## Config File

```
~/.config/tsm-app/config.toml   (TOML via tomllib/tomli-w)
  Managed by ConfigStore (storage/config_store.py)
  load() → AppConfig
  save(AppConfig)
```

## Credentials

```
keyring service: "tsm-app"
  username key:          stored username
  refresh:<username>:    OIDC offline refresh token
  A password saved by the old login is deleted on the next sign-in.
  Managed by storage/secrets.py
```

## WoW Filesystem Outputs

```
<wow_root>/<gv>/Interface/AddOns/TradeSkillMaster_AppHelper/AppData.lua
  Format: see api.md (LoadData lines with a meta comment, ipairs for connected realms)
  Written by AuctionDataService via lua_writer.AppDataFile

<wow_root>/<gv>/WTF/Account/<ACCOUNT>/SavedVariables/TradeSkillMaster*.lua
  Read by BackupService, AccountingExportView
```

## Backup Files

```
~/.local/share/tsm-app/backups/{sys_id}_{account}_{timestamp}.zip         (auto)
~/.local/share/tsm-app/backups/keep/{sys_id}_{account}_{timestamp}_{name}.zip  (manual)
  ZIP_LZMA, contains TradeSkillMaster*.lua files
```
