# Frontend (PySide6 UI)

## Window Hierarchy

```
AppWindow (QMainWindow)
  ├── tabbar (QWidget)          4 tab QPushButtons
  ├── QStackedWidget
  │   ├── [0] RealmDataView
  │   ├── [1] AddonVersionsView
  │   ├── [2] BackupsView
  │   └── [3] AccountingExportView
  └── TSMStatusBar (QStatusBar)
       ├── status QLabel
       ├── GitHub HoverIconButton
       └── Settings HoverIconButton → SettingsDialog

LoginView (QDialog)           shown before AppWindow on first run
SettingsDialog (QDialog)      opened from status bar settings button
```

## Views

| View                 | File                                | Key Signals In                                   | Key Signals Out                                                 |
| -------------------- | ----------------------------------- | ------------------------------------------------ | --------------------------------------------------------------- |
| RealmDataView        | views/realm_data.py (284 ln)        | `RealmViewModel.data_updated`, `loading_changed` | `RealmViewModel.refresh_all()`, `add_realm()`, `remove_realm()` |
| AddonVersionsView    | views/addon_versions.py (552 ln)    | `RealmViewModel.addons_updated`                  | download/install/delete via `AsyncBridge`                       |
| BackupsView          | views/backups.py (276 ln)           | `AppViewModel.backup_notification`               | `stats_updated(str)`                                            |
| AccountingExportView | views/accounting_export.py (848 ln) | `RealmViewModel.data_updated`                    | CSV export                                                      |
| LoginView            | views/login.py (114 ln)             | (none)                                           | `login_successful`                                              |
| SettingsDialog       | views/settings.py (357 ln)          | (none)                                           | `SettingsViewModel.saved`                                       |

## ViewModels

### AppViewModel (`viewmodels/app_vm.py`, 54 lines)

```
Signals: status_changed(str), authenticated_changed(bool),
         backup_notification(str), addon_notification(str),
         realm_data_received(AuctionData)
Methods: set_status(msg), on_login_success(session)
```

### RealmViewModel (`viewmodels/realm_vm.py`, 180 lines)

```
Signals: data_updated, loading_changed(bool), error_occurred(str), addons_updated(list)
Methods: load_snapshot(), refresh_all(), add_realm(), remove_realm()
         on_data_received(data)   ← public slot (connected from AppViewModel.realm_data_received)
Properties: summaries, last_sync, had_new_data, apphelper_missing
```

### SettingsViewModel (`viewmodels/settings_vm.py`, 87 lines)

```
Signals: saved
Properties: config (AppConfig)
Methods: load(), save()
```

## Components

```
tsm/ui/components/
  hover_button.py    HoverIconButton(icon_normal, icon_hover)
                     enterEvent/leaveEvent swap icons
  status_bar.py      TSMStatusBar(QStatusBar)
                     set_status(msg) - red text on ⚠ prefix
                     settings_requested signal
  progress.py        ProgressWidget
  wow_tooltip.py     WoWTooltip
```

## UI Utilities (`views/_utils.py`, 77 lines)

```python
set_table_cell(table, row, col, text, color=None)
populate_combo(combo, items)          # blockSignals + clear + addItems
start_rate_limit_countdown(btn, label, get_remaining)
build_realm_tree(data) → dict[gv_label, dict[region, list[realm_dict]]]
```

## Log Viewer (`ui/views/log_viewer.py`)

`LogViewerWindow` (QMainWindow) shows in-session log records in a scrollable table.

- Opened via status bar log button; populated lazily on `showEvent` (not at construction)
- Columns: Timestamp, Level, Logger, Message - word-wrap enabled on Message column
- Row height: `Fixed` mode throughout population, single `resizeRowsToContents()` call after all rows are inserted (O(n) instead of O(n^2) that `ResizeToContents` mode would cause per `setItem()`)
- Level color-coding: DEBUG gray, INFO white, WARNING yellow, ERROR/CRITICAL red
- "Copy to Clipboard" button redacts email addresses before copying

## Thread Safety Pattern

All async work runs via `AsyncBridge`:

```python
bridge = AsyncBridge(self)
bridge.result_ready.connect(self._on_result)  # called on Qt thread via QueuedConnection
bridge.run(some_coroutine())
```

Qt widgets are only touched from the main thread. `AsyncBridge` posts results back via Qt signals.
