"""Addon Versions tab — addon list from API + installed version from TOC files."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tsm.api.types import AddonVersionInfo

logger = logging.getLogger(__name__)

_GREEN = "#4caf50"
_RED = "#f44336"
_GROUP_HEADER = "#2a2a2a"  # slightly lighter than table bg for group rows
_GROUP_FG = "#f26522"  # TSM orange for group label text

# Game-version suffixes the original TSM app uses (from WoWHelper.SUFFIX_BY_GAME_VERSION)
_SUFFIXES = ["", "-Classic", "-Progression", "-Anniversary"]
_SUFFIX_ORDER = {s: i for i, s in enumerate(_SUFFIXES)}
_SUFFIX_LABEL = {
    "": "Retail",
    "-Classic": "Classic",
    "-Progression": "Progression",
    "-Anniversary": "Anniversary",
}

# Fallback list if the API hasn't returned addon info yet
_DEFAULT_ADDONS = ["TradeSkillMaster", "TSM_AppHelper"]


def _get_suffix(name: str) -> str:
    for s in sorted(_SUFFIXES, key=len, reverse=True):
        if s and name.endswith(s):
            return s
    return ""


def _addon_sort_key(addon: AddonVersionInfo) -> tuple[int, bool, str]:
    """Sort by suffix group first, then put base addons (no '_') before sub-addons."""
    name = addon["name"]
    suffix = _get_suffix(name)
    base = name[: -len(suffix)] if suffix else name
    # Within a group: names without '_' (base addons) sort before those with '_'
    has_underscore = "_" in base
    return (_SUFFIX_ORDER.get(suffix, 99), has_underscore, base)


class AddonVersionsView(QWidget):
    def __init__(self, wow_detector=None, parent=None):
        super().__init__(parent)
        self._detector = wow_detector
        # List of {name, version_str} dicts from the status API
        self._api_addons: list[AddonVersionInfo] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Name", "Version", "Status"])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        vbox.addWidget(self._table, 1)

        self._table.doubleClicked.connect(self._on_double_click)

        # Bottom bar — fixed height so it matches realm-data and backups bars
        bottom = QWidget()
        bottom.setObjectName("realm-bottom")
        bottom.setFixedHeight(39)
        row = QHBoxLayout(bottom)
        row.setContentsMargins(8, 8, 8, 8)
        hint = QLabel("Double-click on an addon to install it.")
        hint.setObjectName("hint")
        row.addWidget(hint)
        row.addStretch()
        vbox.addWidget(bottom)

    def update_from_api(self, addon_versions: list[AddonVersionInfo]) -> None:
        """Called when the status API returns addon info."""
        # API returns [{name, version_str}, ...] for base addons.
        # Expand each with all game-version suffixes (same as original WoWHelper).
        expanded: list[AddonVersionInfo] = []
        for addon in addon_versions:
            base_name = addon["name"]
            for suffix in _SUFFIXES:
                expanded.append(
                    AddonVersionInfo(name=base_name + suffix, version_str=addon["version_str"])
                )
        self._api_addons = expanded
        self._refresh()

    def _refresh(self) -> None:
        addon_list: list[AddonVersionInfo]
        if self._api_addons:
            addon_list = self._api_addons
        else:
            addon_list = [
                AddonVersionInfo(name=base + suffix, version_str="")
                for base in _DEFAULT_ADDONS
                for suffix in _SUFFIXES
            ]

        addon_list = sorted(addon_list, key=_addon_sort_key)
        installed = self._get_installed_versions()

        # Group addons by suffix, inserting a header row before each group
        groups: dict[str, list[AddonVersionInfo]] = {}
        for addon in addon_list:
            suffix = _get_suffix(addon["name"])
            groups.setdefault(suffix, []).append(addon)

        self._table.setRowCount(0)
        self._header_rows: set[int] = set()

        for suffix in _SUFFIXES:
            if suffix not in groups:
                continue
            # Insert group header row
            header_row = self._table.rowCount()
            self._table.insertRow(header_row)
            self._header_rows.add(header_row)
            label = _SUFFIX_LABEL.get(suffix, suffix.lstrip("-"))
            item = QTableWidgetItem(label)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not selectable
            item.setForeground(QBrush(QColor(_GROUP_FG)))
            item.setBackground(QBrush(QColor(_GROUP_HEADER)))
            self._table.setItem(header_row, 0, item)
            for col in (1, 2):
                filler = QTableWidgetItem("")
                filler.setFlags(Qt.ItemFlag.ItemIsEnabled)
                filler.setBackground(QBrush(QColor(_GROUP_HEADER)))
                self._table.setItem(header_row, col, filler)

            for addon in groups[suffix]:
                row = self._table.rowCount()
                self._table.insertRow(row)
                name = addon["name"]
                latest = addon.get("version_str", "")
                version_type, installed_ver = installed.get(name, (0, ""))

                self._set_cell(row, 0, name)
                if version_type == 0:
                    self._set_cell(row, 1, "")
                    self._set_cell(row, 2, "")
                elif version_type == 2:
                    self._set_cell(row, 1, installed_ver)
                    self._set_cell(row, 2, "Up to date", _GREEN)
                elif latest and installed_ver != latest:
                    self._set_cell(row, 1, installed_ver)
                    self._set_cell(row, 2, f"Update available: {latest}", _RED)
                else:
                    self._set_cell(row, 1, installed_ver)
                    self._set_cell(row, 2, "Up to date", _GREEN)

    def _get_installed_versions(self) -> dict[str, tuple[int, str]]:
        """Returns {addon_name: (version_type, version_str)} for all installed addons.
        version_type: 0=not installed, 1=release, 2=dev
        """
        result: dict[str, tuple[int, str]] = {}
        if self._detector is None:
            return result
        try:
            installs = getattr(self._detector, "_installs", []) or []
            for install in installs:
                # install.path is the _retail_ path; parent is the WoW root
                wow_root = Path(install.path).parent
                for suffix, game_ver in {
                    "": "_retail_",
                    "-Classic": "_classic_era_",
                    "-Progression": "_classic_",
                    "-Anniversary": "_anniversary_",
                }.items():
                    addons_dir = wow_root / game_ver / "Interface" / "AddOns"
                    if not addons_dir.exists():
                        addons_dir = wow_root / game_ver / "Interface" / "Addons"
                    if not addons_dir.exists():
                        continue
                    # Check every addon that ends with this suffix
                    for addon_info in self._api_addons or []:
                        name = addon_info["name"]
                        if not name.endswith(suffix if suffix else "") and suffix:
                            continue
                        if suffix == "" and any(name.endswith(s) for s in _SUFFIXES[1:]):
                            continue
                        # Zip always extracts as base_name/ (suffix only picks the gv dir)
                        folder = name[: -len(suffix)] if suffix else name
                        toc = addons_dir / folder / f"{folder}.toc"
                        if toc.exists():
                            result[name] = _parse_toc(toc)
        except Exception:
            logger.debug("Could not detect addon versions", exc_info=True)
        return result

    def _set_cell(self, row: int, col: int, text: str, color: str | None = None) -> None:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if col in (1, 2):
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if color:
            item.setForeground(QBrush(QColor(color)))
        self._table.setItem(row, col, item)

    def _on_double_click(self, index) -> None:
        row = index.row()
        if row in getattr(self, "_header_rows", set()):
            return  # ignore clicks on group header rows
        name_item = self._table.item(row, 0)
        if name_item:
            logger.info("Install/update requested for %s", name_item.text())


def _parse_toc(toc: Path) -> tuple[int, str]:
    """Returns (version_type, version_str). version_type: 1=release, 2=dev."""
    try:
        for line in toc.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("## Version:"):
                ver = line.split(":", 1)[1].strip()
                if ver in ("@project-version@", "@tsm-project-version@"):
                    return (2, "Dev")
                return (1, ver)
    except OSError:
        pass
    return (0, "")
