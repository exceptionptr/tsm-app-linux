"""Secret masking and shortening of the debug trace."""

from __future__ import annotations

import logging

import pytest

from tsm.api import trace

JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ4In0.c2lnbmF0dXJl"


def test_mask_bearer_and_jwt():
    assert JWT not in trace.mask(f"token {JWT} end")
    assert "abc123" not in trace.mask("Authorization: Bearer abc123")


def test_mask_signed_url_parameters():
    url = "https://example.com/blob?X-Amz-Signature=deadbeef&X-Amz-Credential=cred&keep=1"
    masked = trace.mask(url)
    assert "deadbeef" not in masked
    assert "cred&" not in masked
    assert "keep=1" in masked


def test_mask_json_token_fields():
    masked = trace.mask('{"access_token": "secret1", "name": "Max Mustermann"}')
    assert "secret1" not in masked
    assert "Max Mustermann" in masked


def test_mask_headers():
    masked = trace.mask_headers({"Authorization": "Bearer abc", "Accept": "*/*"})
    assert masked == {"Authorization": trace.MASK, "Accept": "*/*"}


def test_shorten():
    assert trace.shorten("abc", 10) == "abc"
    assert trace.shorten("a" * 20, 10).startswith("a" * 10 + "...")


def test_log_frame_masks_and_respects_level(caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO, logger="tsm.trace"):
        trace.log_frame("<-", "ws", f'42["x","{JWT}"]')
    assert not caplog.records
    with caplog.at_level(logging.DEBUG, logger="tsm.trace"):
        trace.log_frame("<-", "ws", f'42["x","{JWT}"]')
    assert len(caplog.records) == 1
    assert JWT not in caplog.text
