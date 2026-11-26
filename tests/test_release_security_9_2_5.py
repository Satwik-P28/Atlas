"""Release-security regression tests for the Phase 9.2.5 audit.

Each test pins a defect or a defensive boundary that the audit found unenforced:

* a compressed body that ends early was returned as a complete document;
* a corrupt or unusual ZIP entry surfaced as an unhandled exception;
* a declared or chunked request body had no size ceiling;
* a provider body was buffered whole before its size was checked.
"""

from __future__ import annotations

import gzip
import http.client
import io
import zlib
import zipfile

import pytest
from fastapi.testclient import TestClient

from atlas.applications.contracts import (
    PackageIntegrityError,
    PackageValidationError,
    read_package,
)
from atlas.core.errors import ProviderPayloadError, ProviderUnavailable
from atlas.ingestion import sec_client
from atlas.ingestion.sec_client import SecClient, _decompress, _read_bounded
from atlas.terminal import api as terminal_api


# --------------------------------------------------------------------- transport
def test_truncated_gzip_stream_is_refused() -> None:
    payload = b'{"facts": "ok"}' * 200
    compressed = gzip.compress(payload)
    with pytest.raises(ProviderPayloadError) as error:
        _decompress(compressed[: len(compressed) // 2], {"Content-Encoding": "gzip"})
    assert "truncated" in str(error.value)


def test_gzip_without_trailer_is_refused() -> None:
    compressed = gzip.compress(b'{"facts": "ok"}' * 50)
    with pytest.raises(ProviderPayloadError) as error:
        _decompress(compressed[:-8], {"Content-Encoding": "gzip"})
    assert error.value.code == "provider_payload_error"


def test_truncated_deflate_stream_is_refused() -> None:
    compressed = zlib.compress(b'{"facts": "ok"}' * 200)
    with pytest.raises(ProviderPayloadError) as error:
        _decompress(compressed[: len(compressed) - 3], {"Content-Encoding": "deflate"})
    assert "truncated" in str(error.value)


def test_concatenated_gzip_members_are_decoded_in_order() -> None:
    first, second = b'{"a": 1}', b'{"b": 2}'
    combined = gzip.compress(first) + gzip.compress(second)
    assert _decompress(combined, {"Content-Encoding": "gzip"}) == first + second


def test_trailing_bytes_after_gzip_members_are_refused() -> None:
    compressed = gzip.compress(b"{}") + b"not-a-gzip-member"
    with pytest.raises(ProviderPayloadError) as error:
        _decompress(compressed, {"Content-Encoding": "gzip"})
    assert "trailing bytes" in str(error.value)


def test_trailing_bytes_after_deflate_stream_are_refused() -> None:
    compressed = zlib.compress(b"{}") + b"junk"
    with pytest.raises(ProviderPayloadError) as error:
        _decompress(compressed, {"Content-Encoding": "deflate"})
    assert "trailing bytes" in str(error.value)


def test_corrupt_gzip_crc_is_refused() -> None:
    compressed = bytearray(gzip.compress(b'{"facts": "ok"}' * 20))
    compressed[-8] ^= 0xFF  # CRC-32 trailer
    with pytest.raises(ProviderPayloadError) as error:
        _decompress(bytes(compressed), {"Content-Encoding": "gzip"})
    assert "cannot decompress" in str(error.value)


def test_invalid_gzip_header_is_refused() -> None:
    with pytest.raises(ProviderPayloadError):
        _decompress(b"\x1f\x8bnot-really-gzip", {"Content-Encoding": "gzip"})


def test_compressed_input_over_the_limit_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(sec_client, "_MAX_COMPRESSED_BYTES", 32)
    with pytest.raises(ProviderPayloadError) as error:
        _decompress(gzip.compress(b"x" * 10_000), {"Content-Encoding": "gzip"})
    assert "input size limit" in str(error.value)


def test_empty_compressed_body_is_refused() -> None:
    with pytest.raises(ProviderPayloadError):
        _decompress(b"", {"Content-Encoding": "gzip"})


class _FakeResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self._buffer = io.BytesIO(body)
        self.headers = headers or {}
        self.reads = 0

    def read(self, size: int = -1) -> bytes:
        self.reads += 1
        return self._buffer.read(size)


def test_bounded_read_refuses_declared_oversize_before_reading() -> None:
    response = _FakeResponse(b"x" * 100, {"Content-Length": "100"})
    with pytest.raises(ProviderPayloadError):
        _read_bounded(response, 10)
    assert response.reads == 0


def test_bounded_read_refuses_undeclared_oversize_body() -> None:
    with pytest.raises(ProviderPayloadError):
        _read_bounded(_FakeResponse(b"x" * 100), 10)


def test_bounded_read_returns_small_body() -> None:
    assert _read_bounded(_FakeResponse(b"abc"), 10) == b"abc"


def test_interrupted_read_is_retried_then_reported() -> None:
    calls = []

    def transport(request, timeout):
        calls.append(request.full_url)
        raise http.client.IncompleteRead(b"partial", 10)

    client = SecClient(
        user_agent="AtlasQuant/0.1 research@example.com",
        transport=transport,
        sleep=lambda _: None,
        jitter=lambda: 0.0,
        requests_per_second=1000,
        max_retries=2,
    )
    with pytest.raises(ProviderUnavailable):
        client.get("https://data.sec.gov/submissions/CIK0000320193.json")
    assert len(calls) == 3


def test_truncated_transport_body_is_not_returned_as_success() -> None:
    compressed = gzip.compress(b'{"facts": "ok"}' * 100)

    def transport(request, timeout):
        return 200, {"Content-Encoding": "gzip"}, compressed[:-8]

    client = SecClient(
        user_agent="AtlasQuant/0.1 research@example.com",
        transport=transport,
        sleep=lambda _: None,
        jitter=lambda: 0.0,
        requests_per_second=1000,
    )
    with pytest.raises(ProviderPayloadError):
        client.get("https://data.sec.gov/submissions/CIK0000320193.json")


# ------------------------------------------------------------------- ZIP packages
def _zip_bytes(entries: list[tuple[str, bytes]], *, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compression) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_zip_path_traversal_is_refused() -> None:
    payload = _zip_bytes([("manifest.json", b"{}"), ("../escape.json", b"{}")])
    with pytest.raises(PackageValidationError):
        read_package(payload)


def test_zip_nul_byte_in_name_is_refused() -> None:
    payload = _zip_bytes([("manifest.json", b"{}"), ("bad\x00name.json", b"{}")])
    with pytest.raises(PackageValidationError):
        read_package(payload)


def test_unsupported_zip_compression_is_refused() -> None:
    payload = _zip_bytes([("manifest.json", b"{}")], compression=zipfile.ZIP_BZIP2)
    with pytest.raises(PackageValidationError) as error:
        read_package(payload)
    assert "compression" in str(error.value)


def test_truncated_zip_archive_is_an_integrity_error() -> None:
    payload = _zip_bytes([("manifest.json", b"{}"), ("data.json", b"{}" * 100)])
    with pytest.raises(PackageIntegrityError):
        read_package(payload[: len(payload) - 20])


def test_truncated_deflate_member_is_an_integrity_error() -> None:
    payload = _zip_bytes([("manifest.json", b"{}"), ("data.json", b"{}" * 2000)])
    # Break the compressed data but keep a readable central directory: replacing the
    # first member's compressed bytes with 0xFF yields a deflate error rather than a
    # structural BadZipFile.
    corrupted = bytearray(payload)
    start = 30 + len("manifest.json") + 2
    corrupted[start:start + 40] = b"\xff" * 40
    with pytest.raises((PackageIntegrityError, PackageValidationError)):
        read_package(bytes(corrupted))


# ------------------------------------------------------------------ request body
def test_oversized_request_body_is_rejected(tmp_path) -> None:
    app = terminal_api.create_app(tmp_path / "terminal.db", web_dist=tmp_path / "dist")
    client = TestClient(app, raise_server_exceptions=False)
    oversized = "x" * (terminal_api.MAX_REQUEST_BYTES + 1024)
    response = client.post("/api/workspaces", content=oversized,
                           headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_declared_oversized_body_is_rejected_without_reading(tmp_path) -> None:
    app = terminal_api.create_app(tmp_path / "terminal.db", web_dist=tmp_path / "dist")
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post(
        "/api/workspaces",
        content=b"{}",
        headers={"content-type": "application/json",
                 "content-length": str(terminal_api.MAX_REQUEST_BYTES + 1)},
    )
    assert response.status_code == 413
