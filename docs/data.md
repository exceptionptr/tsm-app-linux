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
  path: str, version: str  ("_retail_" | "_classic_" | "_classic_era_" | "_anniversary_")

AuctionData (auction.py)
  app_info: AppInfo | None
  entries: dict[tuple[str,str], AppHelperEntry]   keyed (tag, realm_or_region)
  realm_statuses: list[RealmStatus]
  addon_versions: list[AddonVersionInfo]
  last_sync: int  (property, derived from app_info or max entry download_time)

RealmStatus (auction.py)
  display_name, is_region, auctiondb_status, last_updated: int
  game_version, region, name

AppHelperEntry (auction.py)
  tag, realm_or_region, data_blob: str, download_time: int

AppInfo (auction.py)
  version, last_sync, message_id, message_text
```

## SQLite (`~/.local/share/tsm-app/data.db`)

Managed by `storage/database.py` (aiosqlite).

```
AuctionCache (storage/auction_cache.py)
  save_statuses(statuses: list[RealmStatus], saved_at: int)
  load_statuses() → (list[RealmStatus], int)
  Table: realm_statuses (JSON blob per row)
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
  username key: stored username
  session key:  TSM session token
  Managed by SecretsStore (storage/secrets.py)
```

## WoW Filesystem Outputs

```
<wow_root>/<gv>/Interface/AddOns/TSM_AppHelper/AppData.lua
  Format: LoadData("TAG", "Realm", [[return {...}]])
  Written by AddonWriterService via lua_writer.py

<wow_root>/<gv>/WTF/Account/<ACCOUNT>/SavedVariables/TradeSkillMaster*.lua
  Read by BackupService, AccountingExportView
```

## Backup Files

```
~/.local/share/tsm-app/backups/{sys_id}_{account}_{timestamp}.zip         (auto)
~/.local/share/tsm-app/backups/keep/{sys_id}_{account}_{timestamp}_{name}.zip  (manual)
  ZIP_LZMA, contains TradeSkillMaster*.lua files
```
