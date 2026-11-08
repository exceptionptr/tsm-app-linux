"""Tests for the keyring wrapper.

The backend is swapped in on keyring.core, so no real keyring is touched and
the fakes cannot leak into other tests: monkeypatch puts the original back.
"""

from __future__ import annotations

import keyring.core as kcore
import pytest
from keyring.errors import KeyringLocked, NoKeyringError

from tsm.storage import secrets
from tsm.storage.secrets import KeyringUnavailable


class _Memory:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.data.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.data[(service, username)] = password


class _Broken:
    """What keyring settles on when the Secret Service was not up yet."""

    def get_password(self, *_args: object) -> str:
        raise NoKeyringError("No recommended backend was available")

    set_password = get_password


class _Locked:
    def get_password(self, *_args: object) -> str:
        raise KeyringLocked("Failed to unlock the collection!")

    set_password = get_password


@pytest.fixture
def redetect(monkeypatch):
    """Install `first` as the process backend; detection then finds `second`."""
    calls: list[int] = []

    def install(first, second):
        monkeypatch.setattr(kcore, "_keyring_backend", first)

        def init_backend(limit=None):
            calls.append(1)
            kcore._keyring_backend = second

        monkeypatch.setattr(kcore, "init_backend", init_backend)
        return calls

    return install


def test_missing_entry_is_none_not_unavailable(redetect):
    calls = redetect(_Memory(), _Memory())
    assert secrets.get_username() is None
    assert secrets.get_refresh_token("someone") is None
    assert calls == []


def test_backend_is_detected_again_after_a_failure(redetect):
    working = _Memory()
    working.data[(secrets.SERVICE_NAME, secrets.USERNAME_KEY)] = "user@example.com"
    calls = redetect(_Broken(), working)

    assert secrets.get_username() == "user@example.com"
    assert calls == [1]


def test_unavailable_when_the_backend_stays_down(redetect):
    redetect(_Broken(), _Broken())
    with pytest.raises(KeyringUnavailable):
        secrets.get_username()
    with pytest.raises(KeyringUnavailable):
        secrets.get_refresh_token("someone")


def test_locked_keyring_is_not_retried(redetect):
    calls = redetect(_Locked(), _Memory())
    assert secrets.get_username() is None
    assert calls == []


def test_store_credentials_round_trip(redetect):
    memory = _Memory()
    redetect(memory, memory)

    assert secrets.store_credentials("user@example.com", "rt") is True
    assert secrets.get_username() == "user@example.com"
    assert secrets.get_refresh_token("user@example.com") == "rt"


def test_store_credentials_removes_a_legacy_password(redetect):
    memory = _Memory()
    memory.data[(secrets.SERVICE_NAME, secrets.USERNAME_KEY)] = "user@example.com"
    memory.data[(secrets.SERVICE_NAME, secrets.PASSWORD_PREFIX + "user@example.com")] = "pw"
    deleted: list[str] = []
    memory.delete_password = lambda _s, key: (deleted.append(key), memory.data.pop((_s, key)))  # type: ignore[attr-defined]
    redetect(memory, memory)

    assert secrets.has_legacy_password("user@example.com")
    assert secrets.store_credentials("user@example.com", "rt") is True
    assert deleted == [secrets.PASSWORD_PREFIX + "user@example.com"]
    assert not secrets.has_legacy_password("user@example.com")


def test_store_credentials_survives_a_late_secret_service(redetect):
    working = _Memory()
    redetect(_Broken(), working)

    assert secrets.store_credentials("user@example.com", "pw") is True
    saved = working.data[(secrets.SERVICE_NAME, secrets.REFRESH_PREFIX + "user@example.com")]
    assert saved == "pw"


def test_store_credentials_reports_failure(redetect):
    redetect(_Broken(), _Broken())
    assert secrets.store_credentials("user@example.com", "pw") is False
