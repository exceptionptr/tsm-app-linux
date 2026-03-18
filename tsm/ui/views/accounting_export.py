"""Accounting Export tab — reads WoW SavedVariables for accounting data."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tsm.storage.config_store import CONFIG_DIR

logger = logging.getLogger(__name__)

# Maps checkbox label → TSM DB key suffix
_DB_KEYS = {
    "Sales": "csvSales",
    "Purchases": "csvBuys",
    "Income": "csvIncome",
    "Expenses": "csvExpense",
    "Expired Auctions": "csvExpired",
    "Canceled Auctions": "csvCancelled",
}

_GAME_VERSIONS = ("_retail_", "_classic_era_", "_classic_", "_anniversary_")
_SUFFIXES = {
    "_retail_": "",
    "_classic_era_": "-Classic",
    "_classic_": "-Progression",
    "_anniversary_": "-Anniversary",
}


_LAST_DIR_FILE = CONFIG_DIR / "last_export_dir"


class AccountingExportView(QWidget):
    def __init__(self, wow_detector=None, parent=None):
        super().__init__(parent)
        self._detector = wow_detector
        self._last_export_dir: Path = self._load_last_dir()
        self._setup_ui()
        self._populate()

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

    def set_detector(self, detector) -> None:
        self._detector = detector
        self._populate()

    def _setup_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(10)

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
        ar_row.addWidget(self._realm_combo)
        vbox.addLayout(ar_row)

        # Checkboxes
        cb_grid = QGridLayout()
        cb_grid.setHorizontalSpacing(24)
        cb_grid.setVerticalSpacing(4)
        self._checkboxes: dict[str, QCheckBox] = {}
        labels = list(_DB_KEYS.keys())
        for i, label in enumerate(labels):
            cb = QCheckBox(label)
            cb.setChecked(label in ("Sales", "Purchases"))
            self._checkboxes[label] = cb
            cb_grid.addWidget(cb, i // 2, i % 2)
        vbox.addLayout(cb_grid)

        export_btn = QPushButton("Export to CSV")
        export_btn.setFixedHeight(32)
        export_btn.clicked.connect(self._export)
        vbox.addWidget(export_btn)

        vbox.addStretch()

        # Internal: {account_key: [realm, ...]}
        self._accounts: dict[str, list[str]] = {}

    def _populate(self) -> None:
        self._accounts = _scan_accounts(self._detector)
        self._account_combo.blockSignals(True)
        self._account_combo.clear()
        for acct in sorted(self._accounts):
            self._account_combo.addItem(acct)
        self._account_combo.blockSignals(False)
        self._on_account_changed(self._account_combo.currentText())

    def _on_account_changed(self, account: str) -> None:
        self._realm_combo.clear()
        for realm in self._accounts.get(account, []):
            self._realm_combo.addItem(realm)

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

        # Find the SavedVariables file for this account
        wow_root = _get_wow_root(self._detector)
        if not wow_root:
            QMessageBox.warning(self, "TSM", "Could not find WoW installation.")
            return

        # Strip game version suffix from account to get dir name + game version
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
            QMessageBox.warning(self, "TSM", f"No TSM data found for account {account}.")
            return

        export_dir = QFileDialog.getExistingDirectory(
            self, "Select Export Directory", str(self._last_export_dir)
        )
        if not export_dir:
            return
        export_path = Path(export_dir)
        self._last_export_dir = export_path
        self._save_last_dir(export_path)

        from tsm.wow.saved_variables import read_saved_variables

        db = read_saved_variables(sv_path)

        exported = []
        errors = []

        for label in checked:
            db_key = f"r@{realm}@internalData@{_DB_KEYS[label]}"
            csv_data = db.get(db_key)
            if not csv_data:
                errors.append(label)
                continue
            out_path = export_path / f"Accounting_{realm}_{label.replace(' ', '_')}.csv"
            try:
                _write_csv(csv_data, out_path)
                exported.append(str(out_path))
                logger.info("Exported %s → %s", label, out_path)
            except Exception as e:
                logger.error("Export failed for %s: %s", label, e)
                errors.append(label)

        msg = ""
        if exported:
            msg += f"Exported {len(exported)} file(s) to {export_path}."
        if errors:
            msg += f"\nNo data found for: {', '.join(errors)}"
        QMessageBox.information(self, "TSM", msg or "Nothing to export.")


def _write_csv(csv_string: str, path: Path) -> None:
    """Parse TSM's \\n-delimited CSV string and write a proper CSV file."""
    # TSM stores CSV with literal \n separators (not actual newlines)
    lines = csv_string.replace("\\n", "\n").split("\n")
    rows = list(csv.reader(lines, delimiter=","))
    rows = [r for r in rows if r]  # drop empty rows
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def _scan_accounts(detector) -> dict[str, list[str]]:
    """Return {account_display_name: [realm, ...]} from WTF directories."""
    result: dict[str, list[str]] = {}
    if detector is None:
        return result
    installs = getattr(detector, "_installs", []) or []
    for install in installs:
        wow_root = Path(install.path).parent
        for gv in _GAME_VERSIONS:
            suffix = _SUFFIXES.get(gv, "")
            wtf_accounts = wow_root / gv / "WTF" / "Account"
            if not wtf_accounts.is_dir():
                continue
            for acct_dir in wtf_accounts.iterdir():
                if not acct_dir.is_dir():
                    continue
                if not re.match(r"^[A-Za-z0-9#]+$", acct_dir.name):
                    continue
                if acct_dir.name == "SavedVariables":
                    continue
                # Only show accounts with TSM SavedVariables
                sv = acct_dir / "SavedVariables" / "TradeSkillMaster.lua"
                if not sv.exists():
                    continue
                acct_key = acct_dir.name + suffix
                realms = _scan_realms(acct_dir)
                if realms:
                    result.setdefault(acct_key, []).extend(realms)
    return result


def _scan_realms(acct_dir: Path) -> list[str]:
    """Return realm names from WTF Account/ACCOUNT/SERVER/CHAR structure."""
    realms = []
    for item in acct_dir.iterdir():
        if item.is_dir() and item.name != "SavedVariables":
            realms.append(item.name)
    return sorted(realms)


def _get_wow_root(detector) -> Path | None:
    if detector is None:
        return None
    installs = getattr(detector, "_installs", []) or []
    if not installs:
        return None
    return Path(installs[0].path).parent


def _split_account_suffix(account: str) -> tuple[str, str]:
    """Split 'ACCOUNTNAME-Classic' into ('ACCOUNTNAME', '_classic_era_')."""
    for gv, suffix in _SUFFIXES.items():
        if suffix and account.endswith(suffix):
            return (account[: -len(suffix)], gv)
    return (account, "_retail_")
