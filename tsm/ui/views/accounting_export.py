"""Accounting tab: gold history, headline figures and per-item totals.

Reads the TSM addon's SavedVariables directly. Aggregation lives in
_accounting_stats and the rendering in accounting_dashboard; this module wires
the two together, owns the account / realm / character selectors and exports the
current selection to CSV.
"""

from __future__ import annotations

import csv
import logging
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from tsm.core.services.icon_cache import IconCache
from tsm.core.services.item_cache import ItemCache
from tsm.storage.config_store import CONFIG_DIR
from tsm.ui.components.wow_tooltip import WowItemTooltip
from tsm.ui.views._accounting_selection import (
    load_selection,
    pick_index,
    save_selection,
)
from tsm.ui.views._accounting_stats import (
    ALL_CHARACTERS,
    GoldPoint,
    build_stats,
    characters_for_realm,
    collect_gold_logs,
    merge_gold_logs,
)
from tsm.ui.views._accounting_utils import (
    _TIME_COLS,
    _find_col,
    _is_fetchable,
    _parse_tsm_csv,
    _to_unified_rows,
)
from tsm.ui.views._utils import populate_combo
from tsm.ui.views.accounting_dashboard import ITEM_COL as _ITEM_COL
from tsm.ui.views.accounting_dashboard import AccountingDashboard
from tsm.wow.accounts import scan_tsm_accounts
from tsm.wow.game_versions import SUFFIX_BY_FOLDER

logger = logging.getLogger(__name__)

_DB_KEYS = {
    "Sales": "csvSales",
    "Purchases": "csvBuys",
    "Income": "csvIncome",
    "Expenses": "csvExpense",
    "Expired Auctions": "csvExpired",
    "Canceled Auctions": "csvCancelled",
}

# Types that move gold. Expired and cancelled auctions are recorded by the addon
# but net to nothing, so they are excluded from the money figures.
_FINANCIAL_KEYS = ("Sales", "Purchases", "Income", "Expenses")

_SUFFIXES = SUFFIX_BY_FOLDER

_LAST_DIR_FILE = CONFIG_DIR / "last_export_dir"
_SELECTION_FILE = CONFIG_DIR / "accounting_selection.json"
_TOOLTIP_DELAY_MS = 500


class _ItemHoverFilter(QObject):
    """Event filter that pops a WoW-style tooltip over the item column."""

    def __init__(
        self,
        table: QTableWidget,
        tooltip: WowItemTooltip,
        cache: ItemCache,
        parent: QObject | None = None,
        item_col: int = _ITEM_COL,
    ) -> None:
        super().__init__(parent)
        self._table = table
        self._tooltip = tooltip
        self._cache = cache
        self._item_col = item_col
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_TOOLTIP_DELAY_MS)
        self._pending: tuple[str, int, int] | None = None  # (item_id, gx, gy)
        self._timer.timeout.connect(self._show)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseMove:
            me = event if isinstance(event, QMouseEvent) else None
            if me is None:
                return False
            pos = me.position().toPoint()
            col = self._table.columnAt(pos.x())
            row = self._table.rowAt(pos.y())
            if col == self._item_col and row >= 0:
                cell = self._table.item(row, self._item_col)
                if cell:
                    item_id = cell.data(Qt.ItemDataRole.UserRole)
                    if item_id and _is_fetchable(str(item_id)):
                        vp = self._table.viewport()
                        gp = vp.mapToGlobal(pos)
                        self._pending = (str(item_id), gp.x(), gp.y())
                        self._timer.start()
                        return False
            self._tooltip.hide()
            self._timer.stop()
        elif event.type() in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress):
            self._tooltip.hide()
            self._timer.stop()
        return False

    def _show(self) -> None:
        if not self._pending:
            return
        item_id, gx, gy = self._pending
        data = self._cache.get(item_id)
        if data and data.get("tooltip"):
            tooltip_html = str(data["tooltip"])
            raw_q = data.get("quality")
            quality = int(raw_q) if isinstance(raw_q, (int, float)) else 1
            self._tooltip.show_for(tooltip_html, quality, gx, gy)


class AccountingExportView(QWidget):
    # Emitted from a background thread when a Wowhead or icon fetch completes
    _items_fetched: Signal = Signal(object)
    _icons_fetched: Signal = Signal(object)

    def __init__(self, wow_detector=None, parent=None):
        super().__init__(parent)
        self._detector = wow_detector
        self._last_export_dir = self._load_last_dir()
        self._sv_cache: dict[str, str] = {}
        self._sv_cache_key: str = ""
        self._sv_db: dict = {}
        self._parsed: dict[str, tuple[list[str], list[list[str]]]] = {}
        self._rows: list[dict] = []  # everything in range, after the character filter
        self._accounts: dict[str, list[str]] = {}
        self._range_days: int | None = None  # chart range, None means all
        self._last_stats = None
        # What the user last picked. Only user changes update it, so a refill that
        # has to fall back (account not found yet) does not overwrite the choice.
        self._wanted = load_selection(_SELECTION_FILE)

        self._item_cache = ItemCache()
        self._icon_cache = IconCache()
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._refresh)
        self._items_fetched.connect(self._on_items_fetched)
        self._icons_fetched.connect(self._on_icons_fetched)

        self._setup_ui()
        self.populate()

    # ── Persistence ──────────────────────────────────────────────────

    def _load_last_dir(self) -> Path:
        try:
            if _LAST_DIR_FILE.exists():
                p = Path(_LAST_DIR_FILE.read_text().strip())
                if p.is_dir():
                    return p
        except Exception:
            pass
        return Path.home() / "Desktop"

    def _save_last_dir(self, path: Path) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            _LAST_DIR_FILE.write_text(str(path))
        except Exception:
            pass

    # ── UI setup ─────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        # No outer scroll area: the item table scrolls on its own, and nesting
        # one scroll inside another makes the wheel ambiguous.
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(8)
        vbox.addLayout(self._build_selector_row())

        self._dashboard = AccountingDashboard(self._item_cache, self._icon_cache)
        self._dashboard.range_changed.connect(self._on_range_changed)
        vbox.addWidget(self._dashboard, 1)

        self._setup_tooltip()

        self._export_btn = QPushButton("Export to CSV")
        self._export_btn.setFixedHeight(32)
        self._export_btn.clicked.connect(self._export)
        vbox.addWidget(self._export_btn)

    def _build_selector_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Account:"))
        self._account_combo = QComboBox()
        self._account_combo.setMinimumWidth(160)
        self._account_combo.currentTextChanged.connect(self._on_account_changed)
        row.addWidget(self._account_combo)
        row.addStretch()

        row.addWidget(QLabel("Realm:"))
        self._realm_combo = QComboBox()
        self._realm_combo.setMinimumWidth(160)
        self._realm_combo.currentTextChanged.connect(self._on_realm_changed)
        row.addWidget(self._realm_combo)
        row.addStretch()

        row.addWidget(QLabel("Character:"))
        self._character_combo = QComboBox()
        self._character_combo.setMinimumWidth(150)
        self._character_combo.addItem(ALL_CHARACTERS)
        self._character_combo.currentTextChanged.connect(self._on_character_changed)
        row.addWidget(self._character_combo)
        return row

    def _setup_tooltip(self) -> None:
        self._wow_tooltip = WowItemTooltip()
        table = self._dashboard.table
        self._hover_filter = _ItemHoverFilter(
            table, self._wow_tooltip, self._item_cache, self
        )
        table.viewport().setMouseTracking(True)
        table.viewport().installEventFilter(self._hover_filter)

    # ── Public API ───────────────────────────────────────────────────

    def set_detector(self, detector) -> None:
        self._detector = detector
        self.populate()

    def populate(self) -> None:
        """Rescan the accounts and refill the selectors, keeping the user's pick.

        Runs after every realm data update, so it must not reset the selection
        to the first account (issue #25).
        """
        self._accounts = scan_tsm_accounts(self._detector)
        accounts = sorted(self._accounts)
        populate_combo(self._account_combo, accounts)
        _select(self._account_combo, pick_index(accounts, self._wanted.account))
        self._fill_realms()

    # ── Slots ────────────────────────────────────────────────────────

    def _on_account_changed(self, account: str) -> None:
        self._remember(account=account)
        self._fill_realms()

    def _on_realm_changed(self, realm: str) -> None:
        self._remember(realm=realm)
        self._on_filter_changed()

    def _on_character_changed(self, character: str) -> None:
        self._remember(character=character)
        self._on_filter_changed()

    def _remember(self, **changes: str) -> None:
        self._wanted = replace(self._wanted, **changes)
        save_selection(_SELECTION_FILE, self._wanted)

    def _fill_realms(self) -> None:
        realms = self._accounts.get(self._account_combo.currentText(), [])
        populate_combo(self._realm_combo, realms)
        _select(self._realm_combo, pick_index(realms, self._wanted.realm))
        self._sv_cache = {}
        self._sv_cache_key = ""
        self._parsed = {}
        self._on_filter_changed()

    def _on_filter_changed(self, *_: object) -> None:
        self._debounce.start()

    def _on_range_changed(self, days: object) -> None:
        self._range_days = days if isinstance(days, int) else None
        self._refresh()

    # ── Data loading ─────────────────────────────────────────────────

    def _load_sv(self) -> None:
        account = self._account_combo.currentText()
        realm = self._realm_combo.currentText()
        cache_key = f"{account}|{realm}"
        if cache_key == self._sv_cache_key:
            return

        self._sv_cache = {}
        self._parsed = {}
        self._sv_db = {}
        self._sv_cache_key = cache_key

        if not account or not realm:
            return

        wow_root = _get_wow_root(self._detector)
        if not wow_root:
            return

        acct_dir_name, gv_dir = _split_account_suffix(account)
        sv_path = (
            wow_root
            / gv_dir
            / "WTF"
            / "Account"
            / acct_dir_name
            / "SavedVariables"
            / "TradeSkillMaster.lua"
        )
        if not sv_path.exists():
            return

        from tsm.wow.saved_variables import read_saved_variables

        db = read_saved_variables(sv_path)
        for label, db_key_suffix in _DB_KEYS.items():
            full_key = f"r@{realm}@internalData@{db_key_suffix}"
            val = db.get(full_key, "")
            if val:
                self._sv_cache[label] = val
        self._sv_db = db
        self._populate_characters(db, realm)
        logger.debug("Loaded SV for %s / %s (%d keys)", account, realm, len(self._sv_cache))

    def _populate_characters(self, db: dict, realm: str) -> None:
        """Refill the character combo, keeping the user's pick when it still exists."""
        names = [ALL_CHARACTERS, *characters_for_realm(db, realm)]
        populate_combo(self._character_combo, names)
        _select(self._character_combo, pick_index(names, self._wanted.character))

    def _get_parsed(self, label: str) -> tuple[list[str], list[list[str]]]:
        if label in self._parsed:
            return self._parsed[label]
        csv_str = self._sv_cache.get(label, "")
        if not csv_str:
            self._parsed[label] = ([], [])
            return [], []
        headers, rows = _parse_tsm_csv(csv_str)
        self._parsed[label] = (headers, rows)
        return headers, rows

    def _cutoff(self) -> int:
        """Oldest timestamp the current range admits, measured from now.

        Anchoring on the newest row instead would make "1D" mean "the last day
        that happens to have data", so an account idle for months would still
        show a busy day.
        """
        if self._range_days is None:
            return 0
        return int(time.time()) - self._range_days * 86400

    # ── Refresh ──────────────────────────────────────────────────────

    def _refresh(self) -> None:
        self._load_sv()

        character = self._character_combo.currentText() or ALL_CHARACTERS
        cutoff = self._cutoff()

        rows: list[dict] = []
        for label in _FINANCIAL_KEYS:
            headers, raw_rows = self._get_parsed(label)
            if not headers:
                continue
            for row in _to_unified_rows(raw_rows, headers, label):
                if row["timestamp"] < cutoff:
                    continue
                if character != ALL_CHARACTERS and row.get("player") != character:
                    continue
                rows.append(row)
        rows.sort(key=lambda r: r["timestamp"], reverse=True)
        self._rows = rows

        series = merge_gold_logs(
            collect_gold_logs(self._sv_db, self._realm_combo.currentText(), character)
        )
        series = [p for p in series if p.timestamp >= cutoff]

        stats = build_stats(rows, series, *self._span(rows, series))
        self._last_stats = stats
        self._dashboard.set_stats(stats)
        self._export_btn.setText(f"Export to CSV ({len(rows):,} rows)")

        self._request_item_data(stats.top_items)

    def _span(self, rows: list[dict], series: list[GoldPoint]) -> tuple[int, int]:
        """Start and end of the data actually shown, for the per-day averages."""
        stamps = [r["timestamp"] for r in rows if r["timestamp"]]
        stamps += [p.timestamp for p in series]
        if not stamps:
            return 0, 0
        return min(stamps), max(stamps)

    def _request_item_data(self, items) -> None:
        """Resolve names first, then icons: a slug only exists once a name does."""
        missing = [
            t.item_id.split(":")[1]
            for t in items
            if t.item_id.startswith("i:") and not self._item_cache.get(t.item_id.split(":")[1])
        ]
        if missing:
            self._item_cache.ensure_fetched(
                missing, lambda fetched, attempted: self._items_fetched.emit(fetched)
            )
        self._dashboard.request_icons(
            list(items), lambda fetched: self._icons_fetched.emit(fetched)
        )

    def _on_items_fetched(self, _fetched: object) -> None:
        """Names arrived on a worker thread; redraw and pull their icons."""
        if self._last_stats is None:
            return
        self._dashboard.set_stats(self._last_stats)
        self._dashboard.request_icons(
            list(self._last_stats.top_items), lambda f: self._icons_fetched.emit(f)
        )

    def _on_icons_fetched(self, _fetched: object) -> None:
        if self._last_stats is not None:
            self._dashboard.set_stats(self._last_stats)

    # ── Export ───────────────────────────────────────────────────────

    def _export(self) -> None:
        realm = self._realm_combo.currentText()
        if not self._account_combo.currentText() or not realm:
            QMessageBox.warning(self, "TSM", "Please select an account and realm.")
            return
        if not self._rows:
            QMessageBox.information(self, "TSM", "Nothing to export for this selection.")
            return

        export_dir = QFileDialog.getExistingDirectory(
            self, "Select Export Directory", str(self._last_export_dir)
        )
        if not export_dir:
            return
        export_path = Path(export_dir)
        self._last_export_dir = export_path
        self._save_last_dir(export_path)

        character = self._character_combo.currentText() or ALL_CHARACTERS
        cutoff = self._cutoff()
        suffix = "all" if self._range_days is None else f"{self._range_days}d"
        if character != ALL_CHARACTERS:
            suffix = f"{character}_{suffix}"

        exported: list[str] = []
        errors: list[str] = []
        for label in _DB_KEYS:
            headers, raw_rows = self._get_parsed(label)
            if not headers or not raw_rows:
                continue

            hl = [h.lower().strip() for h in headers]
            t_idx = _find_col(hl, _TIME_COLS)
            p_idx = _find_col(hl, ["player"])

            filtered = []
            for row in raw_rows:
                try:
                    ts = int(row[t_idx]) if 0 <= t_idx < len(row) else 0
                except (ValueError, IndexError):
                    continue
                if ts < cutoff:
                    continue
                if (
                    character != ALL_CHARACTERS
                    and 0 <= p_idx < len(row)
                    and row[p_idx].strip() != character
                ):
                    continue
                filtered.append(row)

            if not filtered:
                continue

            safe_label = label.replace(" ", "_")
            out_path = export_path / f"Accounting_{realm}_{safe_label}_{suffix}.csv"
            try:
                with open(out_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    writer.writerows(filtered)
                exported.append(str(out_path))
                logger.info("Exported %s (%d rows) -> %s", label, len(filtered), out_path)
            except Exception as e:
                logger.error("Export failed for %s: %s", label, e)
                errors.append(label)

        msg = ""
        if exported:
            msg += f"Exported {len(exported)} file(s) to {export_path}."
        if errors:
            msg += f"\nFailed to write: {', '.join(errors)}"
        QMessageBox.information(self, "TSM", msg or "Nothing to export.")


# ── Module-level helpers ──────────────────────────────────────────────────────


def _select(combo: QComboBox, index: int) -> None:
    """Set the current index without firing the change signals."""
    combo.blockSignals(True)
    combo.setCurrentIndex(index)
    combo.blockSignals(False)


def _get_wow_root(detector) -> Path | None:
    """Return the WoW base directory from the first detected install."""
    if detector is None:
        return None
    installs = getattr(detector, "installs", None)
    if not installs:
        return None
    from tsm.wow.utils import normalize_wow_base

    return normalize_wow_base(Path(installs[0].path))


def _split_account_suffix(account: str) -> tuple[str, str]:
    """Split 'STANIBNET-Classic' into ('STANIBNET', '_classic_era_')."""
    for gv_dir, suffix in _SUFFIXES.items():
        if suffix and account.endswith(suffix):
            return account[: -len(suffix)], gv_dir
    return account, "_retail_"
