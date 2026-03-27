"""Qt stylesheet loader."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication


def load_theme(app: QApplication, theme_name: str = "tsm_dark") -> None:
    """Load and apply a QSS stylesheet to the application."""
    styles_dir = Path(__file__).parent
    qss_path = styles_dir / f"{theme_name}.qss"
    if not qss_path.exists():
        return
    assets_dir = (styles_dir.parent / "assets").resolve().as_posix()
    qss = qss_path.read_text(encoding="utf-8").replace("{ASSETS}", assets_dir)
    app.setStyleSheet(qss)
