"""Tests for tsm.core.services.item_cache."""

from __future__ import annotations

import json
import threading
from unittest.mock import patch

from tsm.core.services.item_cache import ItemCache


def test_get_returns_none_when_empty():
    cache = ItemCache.__new__(ItemCache)
    cache._lock = threading.Lock()
    cache._data = {}
    assert cache.get("12345") is None


def test_get_returns_cached_entry():
    cache = ItemCache.__new__(ItemCache)
    cache._lock = threading.Lock()
    cache._data = {"12345": {"name": "Hearthstone", "quality": 1}}
    result = cache.get("12345")
    assert result is not None
    assert result["name"] == "Hearthstone"


def test_get_name_returns_none_when_missing():
    cache = ItemCache.__new__(ItemCache)
    cache._lock = threading.Lock()
    cache._data = {}
    assert cache.get_name("99") is None


def test_get_name_returns_string():
    cache = ItemCache.__new__(ItemCache)
    cache._lock = threading.Lock()
    cache._data = {"1": {"name": "Sword", "quality": 2}}
    assert cache.get_name("1") == "Sword"


def test_get_name_none_when_name_missing_from_entry():
    cache = ItemCache.__new__(ItemCache)
    cache._lock = threading.Lock()
    cache._data = {"1": {"quality": 2}}
    assert cache.get_name("1") is None


def test_ensure_fetched_skips_known_items():
    cache = ItemCache.__new__(ItemCache)
    cache._lock = threading.Lock()
    cache._data = {"1": {"name": "X"}}
    called = []
    cache.ensure_fetched(["1"], lambda fetched, attempted: called.append((fetched, attempted)))
    assert called == []


def test_ensure_fetched_spawns_thread_for_missing(tmp_path):
    cache = ItemCache.__new__(ItemCache)
    cache._lock = threading.Lock()
    cache._data = {}

    fake_item = {"name": "TestItem", "quality": 1}
    done = threading.Event()
    results = {}

    def on_done(fetched, attempted):
        results["fetched"] = fetched
        results["attempted"] = attempted
        done.set()

    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = mock_open.return_value.__enter__.return_value
        mock_resp.read.return_value = json.dumps(fake_item).encode()
        with patch.object(cache, "_save"):
            cache.ensure_fetched(["42"], on_done)
            done.wait(timeout=5)

    assert results["attempted"] == ["42"]
    assert results["fetched"].get("42", {}).get("name") == "TestItem"


def test_ensure_fetched_handles_network_error(tmp_path):
    cache = ItemCache.__new__(ItemCache)
    cache._lock = threading.Lock()
    cache._data = {}

    done = threading.Event()
    results = {}

    def on_done(fetched, attempted):
        results["fetched"] = fetched
        results["attempted"] = attempted
        done.set()

    with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        cache.ensure_fetched(["99"], on_done)
        done.wait(timeout=5)

    assert results["fetched"] == {}
    assert results["attempted"] == ["99"]


def test_load_populates_data(tmp_path):
    data = {"1": {"name": "Hearthstone"}}
    cache_file = tmp_path / "item_cache.json"
    cache_file.write_text(json.dumps(data), encoding="utf-8")

    cache = ItemCache.__new__(ItemCache)
    cache._lock = threading.Lock()
    cache._data = {}
    with patch("tsm.core.services.item_cache._CACHE_FILE", cache_file):
        cache._load()

    assert cache._data == data


def test_save_writes_file(tmp_path):
    cache = ItemCache.__new__(ItemCache)
    cache._lock = threading.Lock()
    cache._data = {"5": {"name": "Staff"}}
    cache_file = tmp_path / "item_cache.json"
    with patch("tsm.core.services.item_cache._CACHE_FILE", cache_file):
        cache._save()

    saved = json.loads(cache_file.read_text(encoding="utf-8"))
    assert saved["5"]["name"] == "Staff"
