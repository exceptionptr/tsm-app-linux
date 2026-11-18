"""The login window forgets its window and future before it resolves the future."""

from __future__ import annotations

from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6.QtWidgets")

from tsm.ui import login_window  # noqa: E402


def test_callback_clears_window_and_future_before_resolving(monkeypatch):
    monkeypatch.setattr(login_window.chromium, "parse_callback", lambda url: {"code": "x"})
    monkeypatch.setattr(login_window.QTimer, "singleShot", lambda ms, ctx, fn: None)
    future: Future = Future()
    seen: dict = {}
    future.add_done_callback(lambda f: seen.update(window=obj._window, future=obj._future))
    obj = SimpleNamespace(_window=MagicMock(), _future=future)

    login_window.ChromiumLogin._on_callback(obj, "http://localhost/auth/callback?code=x")  # type: ignore[arg-type]

    assert future.result() == {"code": "x"}
    assert seen == {"window": None, "future": None}
    assert obj._window is None and obj._future is None


def _accept(page, url: str, main: bool = True) -> bool:
    nav = login_window.QWebEnginePage.NavigationType.NavigationTypeTyped
    return login_window._GuardedPage.acceptNavigationRequest(page, url, nav, main)  # type: ignore[arg-type]


def test_bootstrap_html_escapes_and_sets_no_referrer():
    html = login_window.bootstrap_html("https://id.tradeskillmaster.com/a?x=</script><b>")
    assert 'content="no-referrer"' in html
    assert "location.replace(" in html
    assert "</script><b>" not in html


AUTHORIZE = "https://id.tradeskillmaster.com/realms/app/protocol/openid-connect/auth?x=1"


def test_guard_accepts_the_bootstrap_page_however_qt_reports_it():
    page = SimpleNamespace(_bootstrap_open=True, callback=MagicMock())
    assert _accept(page, "data:text/html;charset=UTF-8,%3Cmeta")
    assert _accept(page, "file:///tsm-login/")
    assert _accept(page, "file:///tsm-login/index.html")
    assert page._bootstrap_open is True  # kept until the authorize URL


def test_guard_clears_the_bootstrap_flag_only_at_the_authorize_url():
    page = SimpleNamespace(_bootstrap_open=True, callback=MagicMock())
    assert _accept(page, AUTHORIZE)
    assert page._bootstrap_open is False
    assert not _accept(page, "data:text/html;charset=UTF-8,%3Cmeta")


def test_guard_bootstrap_flag_does_not_open_other_origins(caplog):
    page = SimpleNamespace(_bootstrap_open=True, callback=MagicMock())
    with caplog.at_level("WARNING"):
        assert not _accept(page, "https://evil.example.com/")
        assert not _accept(page, "file:///etc/passwd")
    assert page._bootstrap_open is True
    assert "https://evil.example.com/" in caplog.text


def test_guard_after_bootstrap_allows_only_auth_origin_and_callback():
    page = SimpleNamespace(_bootstrap_open=False, callback=MagicMock())
    assert _accept(page, "https://id.tradeskillmaster.com/realms/app/protocol/openid-connect/auth")
    assert not _accept(page, "https://evil.example.com/")
    assert not _accept(page, "data:text/html,x")
    assert not _accept(page, "http://localhost/auth/callback?code=x")
    page.callback.emit.assert_called_once()
