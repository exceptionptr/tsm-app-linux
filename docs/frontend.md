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
| RealmDataView        | views/realm_data.py (350 ln)        | `RealmViewModel.data_updated`, `loading_changed` | `RealmViewModel.refresh_all()`, `add_realm()`, `remove_realm()` |
| AddonVersionsView    | views/addon_versions.py (494 ln)    | `RealmViewModel.addons_updated`                  | download/install/delete via `AsyncBridge`                       |
| BackupsView          | views/backups.py (276 ln)           | `AppViewModel.backup_notification`               | `stats_updated(str)`                                            |
| AccountingExportView | views/accounting_export.py (516 ln) | (none, reads SavedVariables directly)            | CSV export                                                      |
| LoginView            | views/login.py                      | (none)                                           | `login_successful`                                              |
| SettingsDialog       | views/settings.py (357 ln)          | (none)                                           | `SettingsViewModel.saved`                                       |

## Realm grouping (`views/realm_grouping.py`, 110 lines)

Qt free so the ordering is unit testable without a `QApplication`.

```python
GV_ORDER      = keys of wow/game_versions.GAME_VERSIONS (retail, bcc, anniversary, classic, forever)
GV_LABELS     = {key: fallback label}
group_summaries(summaries, labels=None) → [(game_version, label, [RealmRow])]
                labels: the game-versions API labels, when loaded
realm_count(rows) → int    # realms only, ignoring region headers
```

`RealmRow(summary, is_region, label, indent)` is one rendered line. Each region
comes first at indent 0 labelled with its raw region string (`BCC-EU`), then its
realms at indent 1 labelled with the bare realm name. A realm whose region is
missing from the catalogue gets a synthesised region header rather than
disappearing.

Both the Add Realm dropdown (fed by `AuctionDataService.realm_tree()`) and the
Realm Data group headers take their order and labels from `GAME_VERSIONS`, so
they cannot drift apart.

## Accounting dashboard

```
views/_accounting_stats.py    Qt free aggregation, unit testable
    parse_gold_log(csv)          -> [GoldPoint]      "minute,copper", minute = unix/60
    merge_gold_logs([[GoldPoint]]) -> [GoldPoint]    forward fill per character, then sum
    collect_gold_logs(db, realm, character_filter)
    characters_for_realm(db, realm)
    build_stats(rows, series, start_ts, end_ts) -> AccountingStats

views/accounting_dashboard.py  rendering only
    AccountingDashboard(item_cache, icon_cache)
        range_changed(days | None)
        set_stats(AccountingStats)
        table                    ITEM_COL carries the item id for the tooltip filter
    money_html(copper, signed, tint)  gold/silver/copper split, each unit coloured

components/gold_chart.py       GoldChart (QPainter area plot, crosshair on hover)
                               RangeSelector (1D .. All)
components/item_icon.py        item_icon_pixmap(path, quality, size)
                               icon_slug_for_non_item(name) in the dashboard maps
                               Repair Bill / Postage / Money Transfer and friends
                               to a stand-in slug, generic for unknown types
core/services/icon_cache.py    IconCache, mirrors ItemCache for wow.zamimg.com icons
```

Each character logs only its own balance, at its own irregular times, so total
gold is not a sum of raw rows: `merge_gold_logs` forward fills each character to
every timestamp any of them logged, and a character contributes nothing before
its first entry. Warbank and guild logs belong to no character, so they count
only when no character filter is active.

Range buttons cut from **now**, not from the newest row: anchoring on the data
would make "1D" mean "the last day that happens to have data", so an account
idle for months would still show a busy day.

## ViewModels

### AppViewModel (`viewmodels/app_vm.py`, 54 lines)

```
Signals: status_changed(str), authenticated_changed(bool),
         backup_notification(str), addon_notification(str),
         realm_data_received(AuctionData), connection_changed(bool),
         session_lost()
Methods: set_status(msg), on_login_success(session)
```

### RealmViewModel (`viewmodels/realm_vm.py`, 180 lines)

```
Signals: data_updated, loading_changed(bool), error_occurred(str), addons_updated(list),
         add_failed(str), realm_tree_ready(dict)
Methods: load_snapshot(), refresh_all(), load_realm_tree(),
         add_realm(realm_id, ah_type), remove_realm(summary)
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
  collapsible_group.py
                     GroupHeader(label)      arrow + name + side label + summary,
                                             clicked signal
                     CollapsibleGroup(label, body)
                                             header over a body that animates
                                             between 0 and its content height.
                                             Used by RealmDataView and
                                             AddonVersionsView, one group per
                                             WoW game version.
```

Both grouped tabs size their nested table with `table_content_height()` and hand
the result to `CollapsibleGroup.set_content_height()`, which expands the group on
its first fill and then leaves the user's expand/collapse choice alone.

## UI Utilities (`views/_utils.py`, 77 lines)

```python
set_table_cell(table, row, col, text, color=None)
populate_combo(combo, items)          # blockSignals + clear + addItems
start_rate_limit_countdown(btn, label, get_remaining)
build_realm_tree(data) → dict[gv_label, dict[region, list[realm_dict]]]
table_content_height(table, row_count) → int   # exact height, no scrollbar
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
