"""Tests for the single instance lock."""

from __future__ import annotations

from tsm.core.single_instance import acquire_instance_lock


def test_first_acquire_succeeds(tmp_path):
    lock = acquire_instance_lock(tmp_path / "app.lock")
    assert lock is not None
    lock.close()


def test_second_acquire_fails_while_held(tmp_path):
    path = tmp_path / "app.lock"
    first = acquire_instance_lock(path)
    assert first is not None
    try:
        # flock is held per open file, so a second open in the same process
        # conflicts exactly like a second app instance would.
        assert acquire_instance_lock(path) is None
    finally:
        first.close()


def test_lock_is_free_again_after_release(tmp_path):
    path = tmp_path / "app.lock"
    first = acquire_instance_lock(path)
    assert first is not None
    first.close()

    second = acquire_instance_lock(path)
    assert second is not None
    second.close()


def test_creates_missing_parent_directory(tmp_path):
    lock = acquire_instance_lock(tmp_path / "missing" / "dir" / "app.lock")
    assert lock is not None
    lock.close()
