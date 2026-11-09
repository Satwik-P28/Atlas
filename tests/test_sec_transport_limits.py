"""Transport-level limits for the SEC client.

Phase 9.2.4 review found that ``gzip.decompress``/``zlib.decompress`` expanded the whole
stream before ``_MAX_BODY_BYTES`` was applied, so a small compressed response could use
unbounded memory. These tests pin the bounded behaviour so the limit stays enforceable.
"""

from __future__ import annotations

import gzip
import zlib

import pytest

from atlas.core.errors import ProviderPayloadError
from atlas.ingestion import sec_client
from atlas.ingestion.sec_client import _decompress


def test_gzip_body_round_trips() -> None:
    payload = b'{"facts": "ok"}' * 100
    assert _decompress(gzip.compress(payload), {"Content-Encoding": "gzip"}) == payload


def test_deflate_body_round_trips() -> None:
    payload = b'{"facts": "ok"}' * 100
    assert _decompress(zlib.compress(payload), {"content-encoding": "deflate"}) == payload


def test_identity_body_is_returned_unchanged() -> None:
    assert _decompress(b"plain", {}) == b"plain"
    assert _decompress(b"plain", {"Content-Encoding": "br"}) == b"plain"


def test_compressed_body_over_the_limit_is_rejected_before_expansion(monkeypatch) -> None:
    limit = 4096
    monkeypatch.setattr(sec_client, "_MAX_BODY_BYTES", limit)
    bomb = gzip.compress(b"\0" * (limit * 100))
    with pytest.raises(ProviderPayloadError) as error:
        _decompress(bomb, {"Content-Encoding": "gzip"})
    assert "size limit" in str(error.value)


def test_deflate_body_over_the_limit_is_rejected(monkeypatch) -> None:
    limit = 1024
    monkeypatch.setattr(sec_client, "_MAX_BODY_BYTES", limit)
    bomb = zlib.compress(b"A" * (limit * 20))
    with pytest.raises(ProviderPayloadError):
        _decompress(bomb, {"Content-Encoding": "deflate"})


def test_corrupt_gzip_is_reported_as_a_payload_error() -> None:
    with pytest.raises(ProviderPayloadError) as error:
        _decompress(b"not-a-gzip-stream", {"Content-Encoding": "gzip"})
    assert "cannot decompress" in str(error.value)


def test_body_exactly_at_the_limit_is_accepted(monkeypatch) -> None:
    limit = 2048
    monkeypatch.setattr(sec_client, "_MAX_BODY_BYTES", limit)
    payload = b"\0" * limit
    assert _decompress(gzip.compress(payload), {"Content-Encoding": "gzip"}) == payload
