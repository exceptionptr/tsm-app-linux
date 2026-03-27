"""Accounting Export tab: reads WoW SavedVariables for accounting data."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QIcon, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from tsm.core.services.item_cache import ItemCache
from tsm.storage.config_store import CONFIG_DIR
from tsm.ui.components.wow_tooltip import WowItemTooltip
from tsm.ui.views._utils import set_table_cell
from tsm.wow.accounts import scan_tsm_accounts

logger = logging.getLogger(__name__)

_DB_KEYS = {
    "Sales": "csvSales",
    "Purchases": "csvBuys",
    "Income": "csvIncome",
    "Expenses": "csvExpense",
    "Expired Auctions": "csvExpired",
    "Canceled Auctions": "csvCancelled",
}

_SUFFIXES = {
    "_retail_": "",
    "_classic_era_": "-Classic",
    "_classic_": "-Progression",
    "_anniversary_": "-Anniversary",
}

_LAST_DIR_FILE = CONFIG_DIR / "last_export_dir"
_PAGE_SIZE = 50
_ALL_TIME_FROM = QDate(2004, 11, 23)  # WoW release date

# Column name candidates (case-insensitive) for each semantic field
_TIME_COLS = ["time", "timestamp", "ts"]
_PRICE_COLS = ["price", "money", "amount"]
_QTY_COLS = ["quantity", "qty", "count"]
_ITEM_COLS = ["itemstring", "item", "itemid"]

# Sign multiplier for copper totals; 0 = excluded from financial summary
_GOLD_SIGN = {
    "Sales": 1,
    "Purchases": -1,
    "Income": 1,
    "Expenses": -1,
    "Expired Auctions": 0,
    "Canceled Auctions": 0,
}

_TYPE_SHORT = {
    "Sales": "Sale",
    "Purchases": "Purchase",
    "Income": "Income",
    "Expenses": "Expense",
    "Expired Auctions": "Expired",
    "Canceled Auctions": "Canceled",
}

_TYPE_COLOR = {
    "Sales": "#4caf50",
    "Purchases": "#f44336",
    "Income": "#4caf50",
    "Expenses": "#f44336",
    "Expired Auctions": "#888888",
    "Canceled Auctions": "#888888",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_col(headers_lower: list[str], candidates: list[str]) -> int:
    for c in candidates:
        try:
            return headers_lower.index(c)
        except ValueError:
            pass
    return -1


def _parse_tsm_csv(csv_string: str) -> tuple[list[str], list[list[str]]]:
    lines = csv_string.replace("\\n", "\n").split("\n")
    all_rows = [r for r in csv.reader([ln for ln in lines if ln.strip()]) if r]
    if not all_rows:
        return [], []
    return all_rows[0], all_rows[1:]


def _to_unified_rows(
    raw_rows: list[list[str]], headers: list[str], label: str
) -> list[dict]:
    """Convert raw CSV rows to unified dicts with label/item/qty/copper/timestamp."""
    hl = [h.lower().strip() for h in headers]
    t_idx = _find_col(hl, _TIME_COLS)
    p_idx = _find_col(hl, _PRICE_COLS)
    q_idx = _find_col(hl, _QTY_COLS)
    i_idx = _find_col(hl, _ITEM_COLS)
    sign = _GOLD_SIGN.get(label, 0)

    result = []
    for row in raw_rows:
        try:
            ts = int(row[t_idx]) if 0 <= t_idx < len(row) else 0
            price = int(row[p_idx]) if 0 <= p_idx < len(row) else 0
            qty = int(row[q_idx]) if 0 <= q_idx < len(row) else 1
            item = row[i_idx] if 0 <= i_idx < len(row) else (row[0] if row else "?")
            item = item.strip().rstrip(":")
            copper = price * qty * sign
        except (ValueError, IndexError):
            continue
        result.append(
            {"label": label, "item": item, "qty": qty, "copper": copper, "timestamp": ts}
        )
    return result


def _base_item_str(item_str: str) -> str:
    """Return the base item string (i:ID) from a full TSM item string.

    For non-item strings like 'Repair Bill' or 'Money Transfer', returns as-is.
    """
    parts = item_str.split(":")
    if len(parts) >= 2 and parts[0] == "i" and parts[1].isdigit():
        return f"i:{parts[1]}"
    return item_str


def _is_fetchable(item_id: str) -> bool:
    """True only for numeric item IDs that Wowhead can resolve."""
    return item_id.isdigit()



def _fmt_gold(copper: int, with_sign: bool = False) -> str:
    gold = copper / 10000
    if with_sign and gold > 0:
        return f"+{gold:,.0f}g"
    return f"{gold:,.0f}g"


def _make_gold_cell(copper: int) -> QLabel:
    """Right-aligned QLabel with the number in sign-color and 'g' in gold color."""
    if copper == 0:
        html = '<span style="color:#888888">0</span><span style="color:#f0c040">g</span>'
    else:
        num_color = "#4caf50" if copper > 0 else "#f44336"
        sign = "+" if copper > 0 else ""
        gold = copper / 10000
        html = (
            f'<span style="color:{num_color}">{sign}{gold:,.0f}</span>'
            f'<span style="color:#f0c040">g</span>'
        )
    lbl = QLabel(html)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    lbl.setStyleSheet("background: transparent; padding-right: 4px;")
    return lbl


def _qdate_to_ts(d: QDate) -> int:
    return int(datetime(d.year(), d.month(), d.day()).timestamp())


# ── Hover event filter ────────────────────────────────────────────────────────

_ITEM_COL = 1  # column index of the "Item" cell in the preview table
_TOOLTIP_DELAY_MS = 500
_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_SPINNER_COLOR = "#666666"


class _ItemHoverFilter(QObject):
    """Event filter installed on the preview table viewport.

    Shows a WoW-style tooltip when the cursor dwells over a cell in the
    Item column that has cached tooltip data.
    """

    def __init__(
        self,
        table: QTableWidget,
        tooltip: WowItemTooltip,
        cache: ItemCache,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._table = table
        self._tooltip = tooltip
        self._cache = cache
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
            if col == _ITEM_COL and row >= 0:
                cell = self._table.item(row, _ITEM_COL)
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


# ── View ──────────────────────────────────────────────────────────────────────

class AccountingExportView(QWidget):
    # Emitted from background thread when Wowhead fetch completes
    _items_fetched: Signal = Signal(object)

    def __init__(self, wow_detector=None, parent=None):
        super().__init__(parent)
        self._detector = wow_detector
        self._last_export_dir = self._load_last_dir()
        self._sv_cache: dict[str, str] = {}
        self._sv_cache_key: str = ""
        self._parsed: dict[str, tuple[list[str], list[list[str]]]] = {}
        self._all_rows: list[dict] = []
        self._current_page: int = 0
        self._accounts: dict[str, list[str]] = {}
        # item_id -> list of row indices currently showing that item
        self._preview_id_rows: dict[str, list[int]] = {}
        # Summary labels - assigned in _build_summary_widget via setattr
        self._lbl_sales: QLabel
        self._lbl_purchases: QLabel
        self._lbl_net: QLabel
        self._lbl_count: QLabel

        self._item_cache = ItemCache()
        self._loading_rows: dict[int, str] = {}  # row -> item_id currently spinning
        self._spinner_frame = 0
        self._spinner_timer = QTimer()
        self._spinner_timer.setInterval(80)
        self._spinner_timer.timeout.connect(self._tick_spinner)
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._refresh_preview)
        self._items_fetched.connect(self._on_items_fetched)

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
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(8)

        # Account + Realm row
        ar_row = QHBoxLayout()
        ar_row.addWidget(QLabel("Account:"))
        self._account_combo = QComboBox()
        self._account_combo.setMinimumWidth(160)
        self._account_combo.currentTextChanged.connect(self._on_account_changed)
        ar_row.addWidget(self._account_combo)
        ar_row.addStretch()
        ar_row.addWidget(QLabel("Realm:"))
        self._realm_combo = QComboBox()
        self._realm_combo.setMinimumWidth(160)
        self._realm_combo.currentTextChanged.connect(self._on_filter_changed)
        ar_row.addWidget(self._realm_combo)
        vbox.addLayout(ar_row)

        # Date range row
        date_row = QHBoxLayout()
        date_row.setSpacing(6)
        date_row.addWidget(QLabel("From:"))
        self._from_date = QDateEdit()
        self._from_date.setCalendarPopup(True)
        self._from_date.setDisplayFormat("dd.MM.yyyy")
        self._from_date.setDate(QDate.currentDate().addDays(-30))
        self._from_date.dateChanged.connect(self._on_from_date_changed)
        date_row.addWidget(self._from_date)
        lbl_to = QLabel("to")
        lbl_to.setObjectName("hint")
        date_row.addWidget(lbl_to)
        self._to_date = QDateEdit()
        self._to_date.setCalendarPopup(True)
        self._to_date.setDisplayFormat("dd.MM.yyyy")
        self._to_date.setDate(QDate.currentDate())
        self._to_date.setMinimumDate(self._from_date.date())
        self._from_date.setMaximumDate(self._to_date.date())
        self._to_date.dateChanged.connect(self._on_to_date_changed)
        date_row.addWidget(self._to_date)
        date_row.addStretch()
        for text, slot in [
            ("Last 7d", lambda: self._set_range(7)),
            ("Last 30d", lambda: self._set_range(30)),
            ("All time", self._set_all_time),
        ]:
            btn = QPushButton(text)
            btn.setObjectName("secondary")
            btn.clicked.connect(slot)
            date_row.addWidget(btn)
        vbox.addLayout(date_row)

        # Checkboxes
        cb_grid = QGridLayout()
        cb_grid.setHorizontalSpacing(24)
        cb_grid.setVerticalSpacing(4)
        self._checkboxes: dict[str, QCheckBox] = {}
        labels = list(_DB_KEYS.keys())
        for i, label in enumerate(labels):
            cb = QCheckBox(label)
            cb.setChecked(label in ("Sales", "Purchases"))
            cb.stateChanged.connect(self._on_filter_changed)
            self._checkboxes[label] = cb
            cb_grid.addWidget(cb, i // 3, i % 3)
        vbox.addLayout(cb_grid)

        # Summary bar
        vbox.addWidget(self._build_summary_widget())

        # Preview header
        preview_hdr = QHBoxLayout()
        lbl_preview = QLabel("Preview")
        lbl_preview.setObjectName("hint")
        preview_hdr.addWidget(lbl_preview)
        preview_hdr.addStretch()
        self._preview_count = QLabel("")
        self._preview_count.setObjectName("hint")
        preview_hdr.addWidget(self._preview_count)
        vbox.addLayout(preview_hdr)

        # Preview table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Type", "Item", "Qty", "Gold", "Date"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(24)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnWidth(3, 80)
        vbox.addWidget(self._table, 1)

        # Pagination controls
        _assets = Path(__file__).parent.parent / "assets"
        pag_row = QHBoxLayout()
        pag_row.setSpacing(0)
        pag_row.setContentsMargins(0, 0, 0, 0)
        self._btn_prev = QPushButton()
        self._btn_prev.setObjectName("secondary")
        self._btn_prev.setFixedSize(28, 28)
        self._btn_prev.setIcon(QIcon(str(_assets / "chevron-left.svg")))
        self._btn_prev.setIconSize(QSize(16, 16))
        self._btn_prev.clicked.connect(self._prev_page)
        self._page_label = QLabel("Page 1 of 1")
        self._page_label.setObjectName("hint")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._btn_next = QPushButton()
        self._btn_next.setObjectName("secondary")
        self._btn_next.setFixedSize(28, 28)
        self._btn_next.setIcon(QIcon(str(_assets / "chevron-right.svg")))
        self._btn_next.setIconSize(QSize(16, 16))
        self._btn_next.clicked.connect(self._next_page)
        pag_row.addWidget(self._btn_prev)
        pag_row.addStretch()
        pag_row.addWidget(self._page_label)
        pag_row.addStretch()
        pag_row.addWidget(self._btn_next)
        vbox.addLayout(pag_row)

        # Item hover tooltip
        self._wow_tooltip = WowItemTooltip()
        self._hover_filter = _ItemHoverFilter(
            self._table, self._wow_tooltip, self._item_cache, self
        )
        self._table.viewport().setMouseTracking(True)
        self._table.viewport().installEventFilter(self._hover_filter)

        # Export button
        self._export_btn = QPushButton("Export to CSV")
        self._export_btn.setFixedHeight(32)
        self._export_btn.clicked.connect(self._export)
        vbox.addWidget(self._export_btn)

    def _build_summary_widget(self) -> QWidget:
        box = QWidget()
        box.setObjectName("accounting-summary")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(32)

        stats = [
            ("_lbl_sales", "Total sales", "#4caf50"),
            ("_lbl_purchases", "Total purchases", "#f44336"),
            ("_lbl_net", "Net gold", "#4caf50"),
            ("_lbl_count", "Transactions", "#f26522"),
        ]
        for attr, header_text, color in stats:
            col = QWidget()
            col.setStyleSheet("background: transparent;")
            col_vbox = QVBoxLayout(col)
            col_vbox.setContentsMargins(0, 0, 0, 0)
            col_vbox.setSpacing(2)
            hdr_lbl = QLabel(header_text)
            hdr_lbl.setStyleSheet("color: #888888; font-size: 11px; background: transparent;")
            val_lbl = QLabel("--")
            val_lbl.setStyleSheet(
                f"color: {color}; font-weight: bold; font-size: 13px; background: transparent;"
            )
            col_vbox.addWidget(hdr_lbl)
            col_vbox.addWidget(val_lbl)
            setattr(self, attr, val_lbl)
            layout.addWidget(col)

        layout.addStretch()
        return box

    # ── Public ───────────────────────────────────────────────────────

    def set_detector(self, detector) -> None:
        self._detector = detector
        self.populate()

    def populate(self) -> None:
        self._accounts = scan_tsm_accounts(self._detector)
        self._account_combo.blockSignals(True)
        self._account_combo.clear()
        for acct in sorted(self._accounts):
            self._account_combo.addItem(acct)
        self._account_combo.blockSignals(False)
        self._on_account_changed(self._account_combo.currentText())

    # ── Slots ────────────────────────────────────────────────────────

    def _on_account_changed(self, account: str) -> None:
        self._realm_combo.blockSignals(True)
        self._realm_combo.clear()
        for realm in self._accounts.get(account, []):
            self._realm_combo.addItem(realm)
        self._realm_combo.blockSignals(False)
        self._sv_cache = {}
        self._sv_cache_key = ""
        self._parsed = {}
        self._on_filter_changed()

    def _on_from_date_changed(self, date: QDate) -> None:
        self._to_date.setMinimumDate(date)
        self._debounce.start()

    def _on_to_date_changed(self, date: QDate) -> None:
        self._from_date.setMaximumDate(date)
        self._debounce.start()

    def _on_filter_changed(self, *_: object) -> None:
        self._debounce.start()

    def _set_range(self, days: int) -> None:
        self._from_date.clearMaximumDate()
        self._to_date.clearMinimumDate()
        self._from_date.setDate(QDate.currentDate().addDays(-days))
        self._to_date.setDate(QDate.currentDate())

    def _set_all_time(self) -> None:
        self._from_date.clearMaximumDate()
        self._to_date.clearMinimumDate()
        self._from_date.setDate(_ALL_TIME_FROM)
        self._to_date.setDate(QDate.currentDate())

    # ── Data loading ─────────────────────────────────────────────────

    def _load_sv(self) -> None:
        account = self._account_combo.currentText()
        realm = self._realm_combo.currentText()
        cache_key = f"{account}|{realm}"
        if cache_key == self._sv_cache_key:
            return

        self._sv_cache = {}
        self._parsed = {}
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
        logger.debug("Loaded SV for %s / %s (%d keys)", account, realm, len(self._sv_cache))

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

    # ── Preview refresh ──────────────────────────────────────────────

    def _refresh_preview(self) -> None:
        self._load_sv()

        from_ts = _qdate_to_ts(self._from_date.date())
        to_ts = _qdate_to_ts(self._to_date.date()) + 86399  # inclusive end of day

        checked = [label for label, cb in self._checkboxes.items() if cb.isChecked()]

        all_rows: list[dict] = []
        for label in checked:
            headers, raw_rows = self._get_parsed(label)
            if not headers:
                continue
            hl = [h.lower().strip() for h in headers]
            t_idx = _find_col(hl, _TIME_COLS)
            unified = _to_unified_rows(raw_rows, headers, label)
            if t_idx < 0:
                all_rows.extend(unified)
                continue
            for r in unified:
                if from_ts <= r["timestamp"] <= to_ts:
                    all_rows.append(r)

        all_rows.sort(key=lambda r: r["timestamp"], reverse=True)
        self._all_rows = all_rows

        total = len(all_rows)
        self._preview_count.setText(f"{total:,} rows")
        self._export_btn.setText(f"Export to CSV ({total:,} rows)")

        # Summary
        sales_c = sum(r["copper"] for r in all_rows if r["label"] == "Sales")
        buys_c = abs(sum(r["copper"] for r in all_rows if r["label"] == "Purchases"))
        net_c = sales_c - buys_c

        self._lbl_sales.setText(_fmt_gold(sales_c))
        self._lbl_purchases.setText(_fmt_gold(buys_c))
        net_str = _fmt_gold(abs(net_c), with_sign=(net_c >= 0))
        if net_c < 0:
            net_str = "-" + _fmt_gold(abs(net_c))
        net_color = "#4caf50" if net_c >= 0 else "#f44336"
        self._lbl_net.setText(net_str)
        self._lbl_net.setStyleSheet(
            f"color: {net_color}; font-weight: bold; font-size: 13px; background: transparent;"
        )
        self._lbl_count.setText(f"{total:,}")

        self._current_page = 0
        self._render_page()

    def _render_page(self) -> None:
        """Populate the table with the current page of _all_rows."""
        self._spinner_timer.stop()
        self._loading_rows = {}
        self._preview_id_rows = {}

        total = len(self._all_rows)
        num_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        self._current_page = max(0, min(self._current_page, num_pages - 1))

        start = self._current_page * _PAGE_SIZE
        page_rows = self._all_rows[start : start + _PAGE_SIZE]

        self._page_label.setText(f"Page {self._current_page + 1} of {num_pages}")
        self._btn_prev.setEnabled(self._current_page > 0)
        self._btn_next.setEnabled(self._current_page < num_pages - 1)

        self._table.setRowCount(len(page_rows))
        missing_ids: list[str] = []

        for i, r in enumerate(page_rows):
            label = r["label"]
            color = _TYPE_COLOR.get(label, "#d0d0d0")
            copper = r["copper"]

            set_table_cell(self._table, i, 0, _TYPE_SHORT.get(label, label), color)

            base = _base_item_str(r["item"])
            item_id = base[2:] if base.startswith("i:") else base
            if not _is_fetchable(item_id):
                set_table_cell(self._table, i, 1, base)
            else:
                cached = self._item_cache.get_name(item_id)
                if cached:
                    set_table_cell(self._table, i, 1, cached)
                else:
                    set_table_cell(self._table, i, 1, _SPINNER_FRAMES[0], _SPINNER_COLOR)
                    self._loading_rows[i] = item_id
                    missing_ids.append(item_id)
                cell = self._table.item(i, 1)
                if cell:
                    cell.setData(Qt.ItemDataRole.UserRole, item_id)
                self._preview_id_rows.setdefault(item_id, []).append(i)

            set_table_cell(self._table, i, 2, str(r["qty"]))
            qty_item = self._table.item(i, 2)
            if qty_item:
                qty_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )

            self._table.setCellWidget(i, 3, _make_gold_cell(copper))

            dt_str = ""
            if r["timestamp"]:
                import contextlib
                with contextlib.suppress(OSError, OverflowError):
                    dt_str = datetime.fromtimestamp(r["timestamp"]).strftime("%d.%m.%y")
            set_table_cell(self._table, i, 4, dt_str)

        # Gold column: ResizeToContents doesn't measure cell widgets, so calculate manually
        fm = QFontMetrics(self._table.font())
        max_w = 60
        for r in page_rows:
            c = r["copper"]
            if c == 0:
                text = "0g"
            else:
                sign = "+" if c > 0 else ""
                text = f"{sign}{c / 10000:,.0f}g"
            max_w = max(max_w, fm.horizontalAdvance(text) + 24)
        self._table.setColumnWidth(3, max_w)

        # Kick off background fetch for any item IDs not yet in cache
        if missing_ids:
            unique_missing = list(dict.fromkeys(missing_ids))
            self._item_cache.ensure_fetched(
                unique_missing,
                lambda fetched, attempted: self._items_fetched.emit((fetched, attempted)),
            )
            self._spinner_timer.start()

    def _prev_page(self) -> None:
        if self._current_page > 0:
            self._current_page -= 1
            self._render_page()

    def _next_page(self) -> None:
        total = len(self._all_rows)
        num_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
        if self._current_page < num_pages - 1:
            self._current_page += 1
            self._render_page()

    def _tick_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_FRAMES)
        char = _SPINNER_FRAMES[self._spinner_frame]
        for row in self._loading_rows:
            cell = self._table.item(row, _ITEM_COL)
            if cell:
                cell.setText(char)

    def _on_items_fetched(self, payload: object) -> None:
        """Called on the Qt main thread when background fetch completes."""
        fetched: dict[str, object]
        attempted: list[str]
        fetched, attempted = payload  # type: ignore[misc]

        for item_id in attempted:
            rows = self._preview_id_rows.get(item_id, [])
            data = fetched.get(item_id)
            name = str(data.get("name")) if isinstance(data, dict) and data.get("name") else None
            for row in rows:
                cell = self._table.item(row, _ITEM_COL)
                if cell:
                    cell.setText(name if name else f"i:{item_id}")
                self._loading_rows.pop(row, None)

        if not self._loading_rows:
            self._spinner_timer.stop()

    # ── Export ───────────────────────────────────────────────────────

    def _export(self) -> None:
        account = self._account_combo.currentText()
        realm = self._realm_combo.currentText()
        if not account or not realm:
            QMessageBox.warning(self, "TSM", "Please select an account and realm.")
            return

        checked = [label for label, cb in self._checkboxes.items() if cb.isChecked()]
        if not checked:
            QMessageBox.warning(self, "TSM", "Please select at least one data type.")
            return

        self._load_sv()
        from_ts = _qdate_to_ts(self._from_date.date())
        to_ts = _qdate_to_ts(self._to_date.date()) + 86399

        export_dir = QFileDialog.getExistingDirectory(
            self, "Select Export Directory", str(self._last_export_dir)
        )
        if not export_dir:
            return
        export_path = Path(export_dir)
        self._last_export_dir = export_path
        self._save_last_dir(export_path)

        from_str = self._from_date.date().toString("yyyyMMdd")
        to_str = self._to_date.date().toString("yyyyMMdd")

        exported = []
        errors = []

        for label in checked:
            headers, raw_rows = self._get_parsed(label)
            if not headers or not raw_rows:
                errors.append(label)
                continue

            hl = [h.lower().strip() for h in headers]
            t_idx = _find_col(hl, _TIME_COLS)

            filtered = []
            for row in raw_rows:
                try:
                    ts = int(row[t_idx]) if 0 <= t_idx < len(row) else 0
                    if from_ts <= ts <= to_ts:
                        filtered.append(row)
                except (ValueError, IndexError):
                    continue

            if not filtered:
                continue

            safe_label = label.replace(" ", "_")
            out_path = export_path / f"Accounting_{realm}_{safe_label}_{from_str}_{to_str}.csv"
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
            msg += f"\nNo data found for: {', '.join(errors)}"
        QMessageBox.information(self, "TSM", msg or "Nothing to export.")


# ── Module-level helpers ──────────────────────────────────────────────────────

def _get_wow_root(detector) -> Path | None:
    if detector is None:
        return None
    installs = detector.installs
    if not installs:
        return None
    return Path(installs[0].path).parent


def _split_account_suffix(account: str) -> tuple[str, str]:
    """Split 'ACCOUNTNAME-Classic' into ('ACCOUNTNAME', '_classic_era_')."""
    for gv, suffix in _SUFFIXES.items():
        if suffix and account.endswith(suffix):
            return (account[: -len(suffix)], gv)
    return (account, "_retail_")
