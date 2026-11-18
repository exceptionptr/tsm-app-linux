"""AsyncBridge: owned by the application, deleted on the main thread after its answer."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402

from tsm.workers.async_runner import AsyncRunner  # noqa: E402
from tsm.workers.bridge import AsyncBridge  # noqa: E402


@pytest.fixture
def runner():
    app = QCoreApplication.instance() or QCoreApplication([])
    r = AsyncRunner()
    r.start()
    r.wait_ready()
    yield app
    r.stop()


def _pump(app: QCoreApplication, until, seconds: float = 5.0) -> None:
    end = time.monotonic() + seconds
    while not until() and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def test_parentless_bridge_belongs_to_the_application(runner):
    bridge = AsyncBridge()
    assert bridge.parent() is runner


def test_result_is_delivered_then_the_bridge_is_deleted_on_the_main_thread(runner):
    import shiboken6

    async def work() -> int:
        return 7

    got: list[object] = []
    bridge = AsyncBridge()
    bridge.result_ready.connect(got.append)
    bridge.run(work())
    _pump(runner, lambda: bool(got))
    assert got == [7]
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    _pump(runner, lambda: not shiboken6.isValid(bridge), 2.0)
    assert not shiboken6.isValid(bridge)


def test_error_is_delivered_as_text(runner):
    async def boom() -> None:
        raise RuntimeError("nope")

    errors: list[str] = []
    bridge = AsyncBridge()
    bridge.error_occurred.connect(errors.append)
    bridge.run(boom())
    _pump(runner, lambda: bool(errors))
    assert errors == ["nope"]


def test_stop_cancels_a_coroutine_in_flight_without_noise(capfd):
    import asyncio

    app = QCoreApplication.instance() or QCoreApplication([])
    r = AsyncRunner()
    r.start()
    r.wait_ready()
    cleaned: list[bool] = []

    async def hang() -> None:
        try:
            await asyncio.sleep(60)
        finally:
            cleaned.append(True)  # runs while the loop is still open

    bridge = AsyncBridge()
    bridge.run(hang())
    _pump(app, lambda: False, 0.2)
    r.stop()
    assert cleaned == [True]
    assert "Event loop is closed" not in capfd.readouterr().err
