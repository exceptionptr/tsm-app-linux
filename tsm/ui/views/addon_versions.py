"""Addon Versions tab: collapsible game-version groups with per-row action buttons."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
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
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from tsm.api.types import AddonVersionInfo
from tsm.ui.components.hover_button import HoverIconButton
from tsm.ui.views._utils import set_table_cell

logger = logging.getLogger(__name__)

_ASSETS = Path(__file__).parent.parent / "assets"

_GREEN = "#4caf50"
_AMBER = "#ffc107"
_GRAY = "#666666"

# Game-version suffixes the original TSM app uses (from WoWHelper.SUFFIX_BY_GAME_VERSION)
_SUFFIXES = ["", "-Classic", "-Progression", "-Anniversary"]
_SUFFIX_ORDER = {s: i for i, s in enumerate(_SUFFIXES)}
_SUFFIX_LABEL = {
    "": "Retail",
    "-Classic": "Classic",
    "-Progression": "Progression",
    "-Anniversary": "Anniversary",
}

# Fallback list if the API has not returned addon info yet
_DEFAULT_ADDONS = ["TradeSkillMaster", "TSM_AppHelper"]

_ANIM_MS = 180  # collapse/expand animation duration (ms)

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


class _GroupHeader(QWidget):
    """Clickable group header with arrow, group name, and installed summary."""

    clicked: Signal = Signal()

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self.setObjectName("addon-group-header")
        self.setFixedHeight(32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        self._arrow = QLabel("▶")
        self._arrow.setObjectName("addon-group-arrow")
        self._arrow.setFixedWidth(12)
        layout.addWidget(self._arrow)

        name_lbl = QLabel(label)
        name_lbl.setObjectName("addon-group-name")
        layout.addWidget(name_lbl)

        self._wow_lbl = QLabel("")
        self._wow_lbl.setObjectName("addon-group-wow")
        layout.addWidget(self._wow_lbl)

        layout.addStretch()

        self._summary = QLabel("")
        self._summary.setObjectName("addon-group-summary")
        layout.addWidget(self._summary)

    def set_expanded(self, expanded: bool) -> None:
        self._arrow.setText("▼" if expanded else "▶")

    def set_summary(self, text: str) -> None:
        self._summary.setText(text)

    def set_wow_installed(self, installed: bool | None) -> None:
        """Show WoW installation status. None hides the label (state unknown)."""
        if installed is None:
            self._wow_lbl.setText("")
        elif installed:
            self._wow_lbl.setText("Installed")
        else:
            self._wow_lbl.setText("Not installed")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _AddonGroupWidget(QWidget):
    """Collapsible group for one game-version suffix (Retail, Classic, etc.)."""

    def __init__(self, suffix: str, parent=None):
        super().__init__(parent)
        self._suffix = suffix
        self._expanded = False
        self._initialized = False
        self._natural_height = 0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._setup_ui()

    def _setup_ui(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        label = _SUFFIX_LABEL.get(self._suffix, self._suffix.lstrip("-"))
        self._header = _GroupHeader(label)
        self._header.clicked.connect(self._toggle)
        vbox.addWidget(self._header)

        # Collapsible body
        self._body = QWidget()
        self._body.setMaximumHeight(0)
        body_vbox = QVBoxLayout(self._body)
        body_vbox.setContentsMargins(0, 0, 0, 0)
        body_vbox.setSpacing(0)

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

        body_vbox.addWidget(self._table)
        vbox.addWidget(self._body)

        self._anim = QPropertyAnimation(self._body, b"maximumHeight")
        self._anim.setDuration(_ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim.finished.connect(self._on_anim_finished)

    # ── Toggle ────────────────────────────────────────────────────────

    def _toggle(self) -> None:
        if self._expanded:
            self._anim.stop()
            self._anim.setStartValue(self._body.height())
            self._anim.setEndValue(0)
            self._expanded = False
        else:
            self._anim.stop()
            self._anim.setStartValue(self._body.maximumHeight())
            self._anim.setEndValue(self._natural_height)
            self._expanded = True
        self._header.set_expanded(self._expanded)
        self._anim.start()

    def _on_anim_finished(self) -> None:
        if self._expanded:
            # Remove constraint so table can grow if rows are added later
            self._body.setMaximumHeight(16777215)

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
        hdr_h = self._table.horizontalHeader().sizeHint().height()
        if hdr_h < 1:
            hdr_h = 28
        row_h = self._table.verticalHeader().defaultSectionSize()
        self._natural_height = hdr_h + len(addons) * row_h
        self._table.setFixedHeight(self._natural_height)

        # Update header summary
        if installed_count == 0:
            summary = ""
        elif installed_count == 1:
            summary = "1 installed"
        else:
            summary = f"{installed_count} installed"
        self._header.set_summary(summary)

        # Set initial expand/collapse on first call
        if not self._initialized:
            self._initialized = True
            if installed_count > 0:
                self._expanded = True
                self._header.set_expanded(True)
                self._body.setMaximumHeight(16777215)
            # else: stays collapsed (maximumHeight == 0)
        elif self._expanded:
            # Already expanded - keep the height constraint removed
            self._body.setMaximumHeight(16777215)

    def set_wow_installed(self, installed: bool | None) -> None:
        """Delegate WoW installation status to the group header."""
        self._header.set_wow_installed(installed)


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
        game_ver_map = {
            "": "_retail_",
            "-Classic": "_classic_era_",
            "-Progression": "_classic_",
            "-Anniversary": "_anniversary_",
        }
        game_ver = game_ver_map.get(suffix, "")
        if not game_ver:
            return paths
        folder_name = name[: -len(suffix)] if suffix else name
        try:
            from tsm.wow.utils import normalize_wow_base

            for install in self._detector.installs:
                base = normalize_wow_base(Path(install.path))
                for sub in ("AddOns", "Addons"):
                    candidate = base / game_ver / "Interface" / sub / folder_name
                    if candidate.is_dir():
                        paths.append(candidate)
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
        _game_ver_by_suffix = {
            "": "_retail_",
            "-Classic": "_classic_era_",
            "-Progression": "_classic_",
            "-Anniversary": "_anniversary_",
        }
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
                for suffix, game_ver in {
                    "": "_retail_",
                    "-Classic": "_classic_era_",
                    "-Progression": "_classic_",
                    "-Anniversary": "_anniversary_",
                }.items():
                    addons_dir = base / game_ver / "Interface" / "AddOns"
                    if not addons_dir.exists():
                        addons_dir = base / game_ver / "Interface" / "Addons"
                    if not addons_dir.exists():
                        continue
                    for addon_info in self._api_addons or []:
                        name = addon_info["name"]
                        if suffix and not name.endswith(suffix):
                            continue
                        if not suffix and any(name.endswith(s) for s in _SUFFIXES[1:]):
                            continue
                        folder = name[: -len(suffix)] if suffix else name
                        toc = addons_dir / folder / f"{folder}.toc"
                        if toc.exists():
                            result[name] = _parse_toc(toc)
        except Exception:
            logger.debug("Could not detect addon versions", exc_info=True)
        return result


def _parse_toc(toc: Path) -> tuple[int, str]:
    """Return (version_type, version_str). version_type: 1=release, 2=dev."""
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
