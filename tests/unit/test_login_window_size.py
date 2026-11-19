"""The login window is tall enough for error messages but fits the screen."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtWebEngineWidgets", exc_type=ImportError)

from tsm.ui.login_window import (  # noqa: E402
    MIN_WINDOW_HEIGHT,
    SCREEN_MARGIN,
    WINDOW_SIZE,
    window_size,
)


def test_unknown_screen_uses_default():
    assert window_size(None) == WINDOW_SIZE
    assert window_size(0) == WINDOW_SIZE


def test_tall_screen_keeps_default():
    assert window_size(2000) == WINDOW_SIZE


def test_short_screen_is_clamped_with_margin():
    assert window_size(900) == (WINDOW_SIZE[0], 900 - SCREEN_MARGIN)


def test_tiny_screen_keeps_minimum_height():
    assert window_size(300) == (WINDOW_SIZE[0], MIN_WINDOW_HEIGHT)
