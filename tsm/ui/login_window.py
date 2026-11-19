"""The embedded Chromium window for the TSM login (QtWebEngine).

The official client signs in inside its own Chromium window. This module does
the same: a persistent web profile (cookies survive, like the official one), the
official user agent, language and client hints, and a callback that is caught
before it reaches the network.

Threads: everything here lives on the Qt main thread. The OIDC code runs on the
async loop, so ``ChromiumLogin.run`` hands the request over with a queued signal
and awaits a ``concurrent.futures.Future`` that the main thread completes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from concurrent.futures import Future, InvalidStateError
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QObject,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWebEngineCore import (
    QWebEngineLoadingInfo,
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
    qWebEngineChromiumVersion,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from tsm.api import chromium
from tsm.api.official import OFFICIAL_CHROMIUM_VERSION
from tsm.api.oidc import LoginCancelled

logger = logging.getLogger(__name__)

WINDOW_SIZE = (600, 960)
# Room kept free for the title bar and panels when the screen is shorter than the window.
SCREEN_MARGIN = 80
MIN_WINDOW_HEIGHT = 480
WINDOW_BACKGROUND = "#1e1e1e"
LOGOUT_TIMEOUT_SECONDS = 15.0
BOOTSTRAP_BASE_URL = "file:///tsm-login/"


def window_size(available_height: int | None) -> tuple[int, int]:
    """The login window size, clamped to the available screen height when it is known."""
    width, height = WINDOW_SIZE
    if available_height is None or available_height <= 0:
        return width, height
    return width, max(MIN_WINDOW_HEIGHT, min(height, available_height - SCREEN_MARGIN))


def _available_screen_height() -> int | None:
    screen = QGuiApplication.primaryScreen()
    return screen.availableGeometry().height() if screen is not None else None


def bootstrap_html(url: str) -> str:
    """A tiny page whose script moves the window to ``url``.

    The official client reaches the authorize page from a page of its own, so the
    request is cross-site, has no Sec-Fetch-User and no Referer. A direct
    ``QWebEnginePage.load`` would send ``Sec-Fetch-Site: none`` and ``Sec-Fetch-User: ?1``.
    """
    target = json.dumps(url).replace("<", "\\u003c")
    return (
        '<!doctype html><meta name="referrer" content="no-referrer">'
        f"<script>location.replace({target})</script>"
    )


def is_bootstrap_target(url: str) -> bool:
    """True for the setHtml load of the bootstrap page.

    Qt may report it as a data: URL or with the base URL it was given, so both pass.
    """
    return url.startswith("data:text/html") or url.startswith(BOOTSTRAP_BASE_URL)


def log_engine_versions() -> None:
    """Log the Chromium behind the login window (it differs per install)."""
    import PySide6

    logger.info(
        "QtWebEngine: PySide6 %s, Chromium %s",
        PySide6.__version__,
        qWebEngineChromiumVersion(),
    )


class _Interceptor(QWebEngineUrlRequestInterceptor):
    """Runs on the IO thread: writes sec-ch-ua and blocks the callback.

    It touches no window: the callback leaves through a signal, which Qt queues to
    the main thread because the receiver lives there.
    """

    callback = Signal(str)

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        url = info.requestUrl().toString()
        if chromium.is_callback_url(url):
            info.block(True)
            self.callback.emit(url)
            return
        info.setHttpHeader(b"sec-ch-ua", chromium.SEC_CH_UA.encode("ascii"))


def configure_profile(profile: QWebEngineProfile, user_agent: str) -> None:
    """Official user agent, language and client hints (client hints need Qt 6.8)."""
    profile.setHttpUserAgent(user_agent)
    profile.setHttpAcceptLanguage(chromium.ACCEPT_LANGUAGE)
    hints = getattr(profile, "clientHints", None)
    if hints is None:
        logger.warning("This Qt has no client hints API: sec-ch-ua headers stay at the engine's")
        return
    client_hints = hints()
    client_hints.setAllClientHintsEnabled(True)
    client_hints.setPlatform(chromium.CLIENT_PLATFORM)
    client_hints.setIsMobile(False)
    client_hints.setFullVersion(OFFICIAL_CHROMIUM_VERSION)
    client_hints.setFullVersionList(dict(chromium.FULL_VERSION_LIST))


class _GuardedPage(QWebEnginePage):
    """Catches the callback and keeps main-frame navigation on the auth origin."""

    callback = Signal(str)

    def __init__(self, profile: QWebEngineProfile, parent: QObject | None = None) -> None:
        super().__init__(profile, parent)
        self._bootstrap_open = False  # the one data: page of ``load_via_bootstrap``
        # The bootstrap page has a file: base URL, which Qt treats as local content:
        # without this its script hop to the https authorize URL is refused with
        # ERR_NETWORK_ACCESS_DENIED.
        self.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )

    def load_via_bootstrap(self, url: str) -> None:
        """Load ``url`` from a page of our own (see ``bootstrap_html``)."""
        self._bootstrap_open = True
        self.setHtml(bootstrap_html(url), QUrl(BOOTSTRAP_BASE_URL))

    def acceptNavigationRequest(  # noqa: N802
        self, url: QUrl | str, nav_type: QWebEnginePage.NavigationType, is_main_frame: bool
    ) -> bool:
        if not is_main_frame:
            return True
        target = url if isinstance(url, str) else url.toString()
        if self._bootstrap_open:
            # Until the script hop reaches the authorize URL only our own page may
            # load; the flag stays set meanwhile and ends at the https target.
            if is_bootstrap_target(target):
                return True
            if chromium.is_allowed_navigation(target) and not chromium.is_callback_url(target):
                self._bootstrap_open = False
            else:
                logger.warning("Blocked navigation during the bootstrap hop to %s", target)
                return False
        if chromium.is_callback_url(target):
            self.callback.emit(target)
            return False
        if not chromium.is_allowed_navigation(target):
            logger.warning("Blocked navigation outside the auth origin: %s", target)
            return False
        return True


class _LoginPage(QWidget):
    """Top-level window around a QWebEngineView. Closing it cancels the login."""

    callback = Signal(str)  # may be emitted from the IO thread: queued
    closed = Signal(object)

    def __init__(self, profile: QWebEngineProfile) -> None:
        super().__init__()
        self.setWindowTitle("TSM - Sign In")
        self.resize(*window_size(_available_screen_height()))
        self.setStyleSheet(f"background-color: {WINDOW_BACKGROUND};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._view = QWebEngineView(self)
        self._page = _GuardedPage(profile, self._view)
        self._page.callback.connect(self.callback)
        self._view.setPage(self._page)
        layout.addWidget(self._view)
        self._fallback_url: str | None = None
        self._page.loadingChanged.connect(self._on_loading_changed)

    def load(self, url: str, via_bootstrap: bool = False) -> None:
        if via_bootstrap:
            # If the script hop is refused, one direct load still gets the user in.
            self._fallback_url = url
            self._page.load_via_bootstrap(url)
        else:
            self._view.load(QUrl(url))

    def _on_loading_changed(self, info: QWebEngineLoadingInfo) -> None:
        url = self._fallback_url
        if url is None:
            return
        if info.status() == QWebEngineLoadingInfo.LoadStatus.LoadFailedStatus:
            self._fallback_url = None
            logger.warning(
                "The login page did not load from the bootstrap page (%s, error %s, url %s), "
                "loading directly",
                info.errorString(),
                info.errorCode(),
                info.url().toString()[:80],
            )
            # The context object cancels the call if the window is gone by then.
            QTimer.singleShot(0, self, lambda: self._view.load(QUrl(url)))
        elif (
            info.status() == QWebEngineLoadingInfo.LoadStatus.LoadSucceededStatus
            and self._page.url().scheme() != "file"
        ):
            self._fallback_url = None

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.closed.emit(self)
        super().closeEvent(event)


class ChromiumLogin(QObject):
    """Opens the login window on the main thread for a caller on the async loop."""

    _open_requested = Signal(str, object, bool)
    _close_requested = Signal()

    def __init__(self, data_dir: Path, user_agent_fn: Callable[[], str]) -> None:
        super().__init__()
        self._dir = data_dir / "webengine"
        self._user_agent_fn = user_agent_fn
        self._profile: QWebEngineProfile | None = None
        self._interceptor: _Interceptor | None = None
        self._window: _LoginPage | None = None  # main thread only
        self._live: set[_LoginPage] = set()  # every window not yet destroyed
        self._shut_down = False
        self._future: Future[dict[str, str]] | None = None
        self._open_requested.connect(self._open)
        self._close_requested.connect(self._close)

    async def run(self, url: str) -> dict[str, str]:
        """Show the login page and return the callback query (code, state, error ...).

        Raises LoginCancelled when the window is closed. Cancelling the awaiting
        task closes the window.
        """
        return await self._navigate(url, visible=True)

    async def logout(self, url: str, timeout: float = LOGOUT_TIMEOUT_SECONDS) -> None:
        """Send the window to the Keycloak logout URL and wait for its redirect.

        Like the official client the navigation ends the Keycloak session and
        clears its cookie in the login profile. The window stays hidden: the app's
        login window opens next. Raises LoginCancelled on timeout.
        """
        try:
            await asyncio.wait_for(self._navigate(url, visible=False), timeout)
        except TimeoutError as e:
            raise LoginCancelled("The logout page did not answer") from e

    def focus(self) -> bool:
        """Bring the visible login window to the front (main thread only).

        Returns False and shows nothing when there is no window or when it is the
        hidden window used for the logout navigation.
        """
        window = self._window
        if window is None or not window.isVisible():
            return False
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()
        return True

    def shutdown(self) -> None:
        """Delete the windows and then the profile now (aboutToQuit, main thread).

        Qt requires every page of a profile to be gone before the profile is
        released. Only deleteLater is used (a second, immediate delete of an object
        with a pending deleteLater is a double free), flushed by hand because the
        event loop is about to end. Calling it again does nothing.
        """
        if self._shut_down:
            return
        self._shut_down = True
        future, self._future = self._future, None
        self._window = None
        if future is not None and not future.done():
            self._finish_exception(future, LoginCancelled("The application is shutting down"))
        for window in list(self._live):
            window.deleteLater()
        self._flush_deletes()
        profile, self._profile = self._profile, None
        if profile is not None:
            profile.setUrlRequestInterceptor(None)  # type: ignore[arg-type]
            profile.deleteLater()
            self._flush_deletes()

    @staticmethod
    def _flush_deletes() -> None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)

    async def _navigate(self, url: str, visible: bool) -> dict[str, str]:
        future: Future[dict[str, str]] = Future()
        self._open_requested.emit(url, future, visible)
        try:
            return await asyncio.wrap_future(future)
        except asyncio.CancelledError:
            self._close_requested.emit()
            raise

    # ---- main thread ----------------------------------------------------- #

    def _ensure_profile(self) -> QWebEngineProfile:
        if self._profile is None:
            self._dir.mkdir(parents=True, exist_ok=True)
            profile = QWebEngineProfile("tsm-login", self)
            profile.setPersistentStoragePath(str(self._dir / "storage"))
            profile.setCachePath(str(self._dir / "cache"))
            profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies
            )
            self._interceptor = _Interceptor(self)
            # Queued explicitly: the interceptor emits from the IO thread.
            self._interceptor.callback.connect(
                self._on_callback, Qt.ConnectionType.QueuedConnection
            )
            profile.setUrlRequestInterceptor(self._interceptor)
            self._profile = profile
        # The version feed may have moved on since the profile was made.
        configure_profile(self._profile, self._user_agent_fn())
        return self._profile

    @Slot(str, object, bool)
    def _open(self, url: str, future: Future[dict[str, str]], visible: bool) -> None:
        if self._shut_down:
            self._finish_exception(future, LoginCancelled("The application is shutting down"))
            return
        if self._window is not None:
            self._finish_exception(future, LoginCancelled("A login window is already open"))
            return
        try:
            window = _LoginPage(self._ensure_profile())
        except Exception as e:  # noqa: BLE001 - reported to the awaiting login
            logger.exception("Could not create the login window")
            self._finish_exception(future, RuntimeError(f"Login window failed: {e}"))
            return
        self._window = window
        self._future = future
        self._live.add(window)
        window.destroyed.connect(lambda _obj=None, w=window: self._live.discard(w))
        window.callback.connect(self._on_callback)
        window.closed.connect(self._on_closed)
        window.load(url, via_bootstrap=visible)
        if visible:
            window.show()
            window.raise_()
            window.activateWindow()
            logger.info("Opened the TSM login window")
        else:
            logger.info("Navigating the login profile to the logout page")

    @Slot(str)
    def _on_callback(self, url: str) -> None:
        query = chromium.parse_callback(url)
        future = self._future
        if query is None or future is None or future.done():
            return
        # Forget both first: the next _open must never see this window or future.
        # _on_closed ignores a window that is no longer current.
        window = self._window
        self._window = None
        self._future = None
        with contextlib.suppress(InvalidStateError):
            future.set_result(query)
        # Close after the navigation that delivered the callback has unwound.
        if window is not None:
            QTimer.singleShot(0, window, window.close)

    @Slot(object)
    def _on_closed(self, window: _LoginPage) -> None:
        window.deleteLater()
        if window is not self._window:
            return  # an earlier window finishing after a new one opened
        future = self._future
        self._window = None
        self._future = None
        if future is not None and not future.done():
            self._finish_exception(future, LoginCancelled("The login window was closed"))

    @Slot()
    def _close(self) -> None:
        window = self._window
        if window is not None:
            window.close()  # closeEvent -> _on_closed

    @staticmethod
    def _finish_exception(future: Future[dict[str, str]], exc: BaseException) -> None:
        with contextlib.suppress(InvalidStateError):
            future.set_exception(exc)
