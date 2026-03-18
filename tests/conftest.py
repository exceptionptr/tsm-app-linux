"""pytest configuration and fixtures."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
