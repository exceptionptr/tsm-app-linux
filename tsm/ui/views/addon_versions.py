"""Addon Versions tab: collapsible game-version groups with per-row action buttons."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QScrollArea,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from tsm.api.types import AddonVersionInfo
from tsm.core.services.updater import find_addons_dir, toc_version
from tsm.ui.components.collapsible_group import CollapsibleGroup
from tsm.ui.components.hover_button import HoverIconButton
from tsm.ui.views._utils import set_table_cell, table_content_height
from tsm.wow.game_versions import GAME_VERSIONS

logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).parent.parent / "assets"

_GREEN = "#4caf50"
_AMBER = "#ffc107"
_GRAY = "#666666"

# One group per game version, in the order of tsm/wow/game_versions.py. A row is
# named addon + game version suffix ("TradeSkillMaster-Forever"), which is what
# UpdateService.install_or_update_addon expects.
_SUFFIXES = [gv.account_suffix for gv in GAME_VERSIONS]
_SUFFIX_ORDER = {s: i for i, s in enumerate(_SUFFIXES)}
_SUFFIX_LABEL = {gv.account_suffix: gv.label for gv in GAME_VERSIONS}
_FOLDER_BY_SUFFIX = {gv.account_suffix: gv.folder for gv in GAME_VERSIONS}

# Shown before the socket has announced the current releases.
_DEFAULT_ADDONS = ["TradeSkillMaster", "TradeSkillMaster_AppHelper"]

# Module-level icon constants - avoid per-row file I/O
_DL_ICON = QIcon(str(_ASSETS / "download.svg"))
_DL_ICON_HOVER = QIcon(str(_ASSETS / "download-hover.svg"))
_REFRESH_ICON = QIcon(str(_ASSETS / "refresh-cw.svg"))
_REFRESH_ICON_HOVER = QIcon(str(_ASSETS / "refresh-cw-hover.svg"))
_TRASH_ICON = QIcon(str(_ASSETS / "trash.svg"))
_TRASH_ICON_HOVER = QIcon(str(_ASSETS / "trash-hover.svg"))


def _get_suffix(name: str) -> str:
    for s in sorted(_SUFFIXES, key=len, reverse=True):
        if s and name.endswith(s):
            return s
    return ""


def _addon_sort_key(addon: AddonVersionInfo) -> tuple[int, bool, str]:
    """Sort by suffix group first, then base addons (no '_') before sub-addons."""
    name = addon["name"]
    suffix = _get_suffix(name)
    base = name[: -len(suffix)] if suffix else name
    has_underscore = "_" in base
    return (_SUFFIX_ORDER.get(suffix, 99), has_underscore, base)


def _make_action_button(normal_icon: QIcon, hover_icon: QIcon) -> HoverIconButton:
    """Row action button that swaps its icon on hover. Always visible."""
    btn = HoverIconButton(normal_icon, hover_icon)
    btn.setObjectName("row-action")
    btn.setIconSize(QSize(14, 14))
    return btn


_SPINNER_SVG = str(_ASSETS / "loader-circle.svg")


class _SpinnerWidget(QWidget):
    """Rotating loader-circle SVG shown in the action column during a download."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._angle = 0.0
        self._renderer = QSvgRenderer(_SPINNER_SVG, self)
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(30)  # ~33 fps, 12 deg/tick = 1 rotation/sec

    def _tick(self) -> None:
        self._angle = (self._angle + 12.0) % 360.0
        self.update()

    def paintEvent(self, event) -> None:
        size = min(self.width(), self.height()) - 4
        x = (self.width() - size) / 2
        y = (self.height() - size) / 2
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(self._angle)
        p.translate(-self.width() / 2, -self.height() / 2)
        self._renderer.render(p, QRectF(x, y, size, size))
        p.end()


def _make_status_cell(status: str, color: str) -> QWidget:
    """Return a transparent widget with a colored dot and status label."""
    w = QWidget()
    w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    w.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(w)
    layout.setContentsMargins(6, 0, 6, 0)
    layout.setSpacing(6)
    dot = QLabel()
    dot.setFixedSize(10, 10)
    dot.setStyleSheet(f"border-radius: 5px; background: {color};")
    lbl = QLabel(status)
    lbl.setStyleSheet(f"background: transparent; color: {color};")
    layout.addWidget(dot)
    layout.addWidget(lbl)
    layout.addStretch()
    return w


class _AddonGroupWidget(QWidget):
    """Collapsible group for one game-version suffix (Retail, Classic, etc.)."""

    def __init__(self, suffix: str, parent=None):
        super().__init__(parent)
        self._suffix = suffix
        self._setup_ui()

    def _setup_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Name", "Latest", "Installed", "Status", ""])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(28)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(3, 140)
        self._table.setColumnWidth(4, 28)
        hdr.setMinimumSectionSize(16)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        label = _SUFFIX_LABEL.get(self._suffix, self._suffix.lstrip("-"))
        self._group = CollapsibleGroup(label, self._table)
        vbox.addWidget(self._group)

    # ── Data update ───────────────────────────────────────────────────

    def refresh(
        self,
        addons: list[AddonVersionInfo],
        installed: dict[str, tuple[int, str]],
        on_delete: Callable[[str], None] | None = None,
        on_install: Callable[[str, str], None] | None = None,
        downloading: set[str] | None = None,
    ) -> None:
        """Rebuild table rows. Addons must already be filtered to this suffix."""
        installed_count = 0
        downloading = downloading or set()

        self._table.setRowCount(len(addons))
        for row, addon in enumerate(addons):
            name = addon["name"]
            latest = addon.get("version_str", "")
            version_type, inst_ver = installed.get(name, (0, ""))

            set_table_cell(self._table, row, 0, name)
            set_table_cell(self._table, row, 1, latest)

            if version_type == 0:
                set_table_cell(self._table, row, 2, "")
                self._table.setCellWidget(row, 3, _make_status_cell("Not installed", _GRAY))
                if name in downloading:
                    self._table.setCellWidget(row, 4, _SpinnerWidget())
                else:
                    btn = _make_action_button(_DL_ICON, _DL_ICON_HOVER)
                    if on_install is not None:
                        btn.clicked.connect(lambda _, n=name, v=latest: on_install(n, v))
                    self._table.setCellWidget(row, 4, btn)
            elif version_type != 2 and latest and inst_ver != latest:
                installed_count += 1
                set_table_cell(self._table, row, 2, inst_ver)
                self._table.setCellWidget(row, 3, _make_status_cell("Update available", _AMBER))
                if name in downloading:
                    self._table.setCellWidget(row, 4, _SpinnerWidget())
                else:
                    btn = _make_action_button(_REFRESH_ICON, _REFRESH_ICON_HOVER)
                    if on_install is not None:
                        btn.clicked.connect(lambda _, n=name, v=latest: on_install(n, v))
                    self._table.setCellWidget(row, 4, btn)
            else:
                installed_count += 1
                set_table_cell(self._table, row, 2, inst_ver)
                self._table.setCellWidget(row, 3, _make_status_cell("Up to date", _GREEN))
                btn = _make_action_button(_TRASH_ICON, _TRASH_ICON_HOVER)
                if on_delete is not None:
                    btn.clicked.connect(lambda _, n=name: on_delete(n))
                self._table.setCellWidget(row, 4, btn)

        # Compute and lock table height to its exact content size
        height = table_content_height(self._table, len(addons))
        self._table.setFixedHeight(height)

        # Update header summary
        if installed_count == 0:
            summary = ""
        elif installed_count == 1:
            summary = "1 installed"
        else:
            summary = f"{installed_count} installed"
        self._group.set_summary(summary)

        # Expand on the first fill only when something is installed
        self._group.set_content_height(height, expand_if_content=installed_count > 0)

    def set_wow_installed(self, installed: bool | None) -> None:
        """Show WoW installation status. None hides the label (state unknown)."""
        labels: dict[bool | None, str] = {None: "", True: "Installed", False: "Not installed"}
        self._group.set_side_label(labels[installed])


class AddonVersionsView(QWidget):
    install_completed: Signal = Signal()  # emitted after any successful addon install

    def __init__(self, wow_detector=None, update_service=None, parent=None):
        super().__init__(parent)
        self._detector = wow_detector
        self._update_service = update_service
        self._api_addons: list[AddonVersionInfo] = []
        self._downloading: set[str] = set()
        self._setup_ui()

    def _setup_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        content_vbox = QVBoxLayout(content)
        content_vbox.setContentsMargins(0, 0, 0, 0)
        content_vbox.setSpacing(0)

        self._groups: dict[str, _AddonGroupWidget] = {}
        for suffix in _SUFFIXES:
            grp = _AddonGroupWidget(suffix)
            self._groups[suffix] = grp
            content_vbox.addWidget(grp)

        content_vbox.addStretch()
        scroll.setWidget(content)
        vbox.addWidget(scroll)

    def update_from_api(self, addon_versions: list[AddonVersionInfo]) -> None:
        """Called when the status API returns addon info."""
        # Expand each base addon to all game-version suffixes
        expanded: list[AddonVersionInfo] = []
        for addon in addon_versions:
            base_name = addon["name"]
            for suffix in _SUFFIXES:
                expanded.append(
                    AddonVersionInfo(name=base_name + suffix, version_str=addon["version_str"])
                )
        self._api_addons = sorted(expanded, key=_addon_sort_key)
        self._refresh()

    def _refresh(self) -> None:
        addon_list: list[AddonVersionInfo]
        if self._api_addons:
            addon_list = self._api_addons
        else:
            addon_list = sorted(
                [
                    AddonVersionInfo(name=base + suffix, version_str="")
                    for base in _DEFAULT_ADDONS
                    for suffix in _SUFFIXES
                ],
                key=_addon_sort_key,
            )

        installed = self._get_installed_versions()
        wow_installed_suffixes = self._get_wow_installed_suffixes()

        # Group addons by suffix and update each group widget
        groups: dict[str, list[AddonVersionInfo]] = {}
        for addon in addon_list:
            suffix = _get_suffix(addon["name"])
            groups.setdefault(suffix, []).append(addon)

        for suffix, grp in self._groups.items():
            grp_addons = groups.get(suffix, [])
            grp.setVisible(bool(grp_addons))
            if grp_addons:
                grp.refresh(
                    grp_addons,
                    installed,
                    on_delete=self._delete_addon,
                    on_install=self._install_or_update_addon,
                    downloading=self._downloading,
                )
            if wow_installed_suffixes is None:
                grp.set_wow_installed(None)
            else:
                grp.set_wow_installed(suffix in wow_installed_suffixes)

    def _install_or_update_addon(self, name: str, version: str) -> None:
        """Download and install the addon via AsyncBridge, then refresh the view."""
        if self._update_service is None:
            logger.warning("No update service available - cannot install %s", name)
            return
        from tsm.workers.bridge import AsyncBridge

        self._downloading.add(name)
        self._refresh()  # show spinner immediately

        def _done(_) -> None:
            self._downloading.discard(name)
            self._refresh()
            self.install_completed.emit()

        def _error(err: object) -> None:
            logger.error("Install failed for %s: %s", name, err)
            self._downloading.discard(name)
            self._refresh()

        bridge = AsyncBridge(self)
        bridge.result_ready.connect(_done)
        bridge.error_occurred.connect(_error)
        bridge.run(self._update_service.install_or_update_addon(name, version))

    def _find_addon_paths(self, name: str) -> list[Path]:
        """Return all Interface/AddOns/<folder> paths on disk for the given addon name."""
        paths: list[Path] = []
        if self._detector is None:
            return paths
        suffix = _get_suffix(name)
        game_ver = _FOLDER_BY_SUFFIX.get(suffix, "")
        if not game_ver:
            return paths
        folder_name = name[: -len(suffix)] if suffix else name
        try:
            from tsm.wow.utils import normalize_wow_base

            for install in self._detector.installs:
                base = normalize_wow_base(Path(install.path))
                addons_dir = find_addons_dir(base / game_ver)
                if addons_dir is not None and (addons_dir / folder_name).is_dir():
                    paths.append(addons_dir / folder_name)
        except Exception:
            logger.debug("Could not locate addon folder for %s", name, exc_info=True)
        return paths

    def _delete_addon(self, name: str) -> None:
        """Confirm with the user, then delete the addon folder(s) from Interface/AddOns."""
        paths = self._find_addon_paths(name)
        if not paths:
            QMessageBox.warning(self, "TSM", f"Could not find addon folder for '{name}'.")
            return
        reply = QMessageBox.question(
            self,
            "TSM",
            f"Are you sure you want to delete '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for path in paths:
            try:
                shutil.rmtree(path)
                logger.info("Deleted addon folder: %s", path)
            except OSError:
                logger.warning("Failed to delete addon folder: %s", path, exc_info=True)
        self._refresh()

    def _get_wow_installed_suffixes(self) -> set[str] | None:
        """Return the set of suffixes whose WoW game-version directory exists on disk.

        Returns None if no detector is available (state unknown).
        """
        if self._detector is None:
            return None
        _game_ver_by_suffix = _FOLDER_BY_SUFFIX
        result: set[str] = set()
        try:
            from tsm.wow.utils import installed_versions, normalize_wow_base

            installs = self._detector.installs if self._detector is not None else []
            for install in installs:
                base = normalize_wow_base(Path(install.path))
                present = installed_versions(base)
                for suffix, gv in _game_ver_by_suffix.items():
                    if gv in present:
                        result.add(suffix)
        except Exception:
            logger.debug("Could not determine WoW installed versions", exc_info=True)
        return result

    def _get_installed_versions(self) -> dict[str, tuple[int, str]]:
        """Return {addon_name: (version_type, version_str)} for all installed addons.
        version_type: 0=not installed, 1=release, 2=dev
        """
        result: dict[str, tuple[int, str]] = {}
        if self._detector is None:
            return result
        try:
            from tsm.wow.utils import normalize_wow_base

            installs = self._detector.installs if self._detector is not None else []
            for install in installs:
                base = normalize_wow_base(Path(install.path))
                for suffix, game_ver in _FOLDER_BY_SUFFIX.items():
                    addons_dir = find_addons_dir(base / game_ver)
                    if addons_dir is None:
                        continue
                    for addon_info in self._api_addons or []:
                        name = addon_info["name"]
                        if suffix and not name.endswith(suffix):
                            continue
                        if not suffix and any(name.endswith(s) for s in _SUFFIXES[1:]):
                            continue
                        folder = name[: -len(suffix)] if suffix else name
                        vt = toc_version(addons_dir / folder)
                        if vt[0]:
                            result[name] = vt
        except Exception:
            logger.debug("Could not detect addon versions", exc_info=True)
        return result

