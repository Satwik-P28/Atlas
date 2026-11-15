"""Bounds on the live source fetch used by strict certificate verification.

Live verification is the only code path that reaches the network during a verification, so it must
follow a fixed endpoint shape rather than whatever URL a manifest happens to contain. A certificate
or manifest that points elsewhere is refused, not followed.
"""

from __future__ import annotations

import pytest

from atlas.research.certificate_verify import (
    MANIFEST_SCHEMA,
    TrustedEvidence,
    VerificationError,
    fetch_source_bytes,
)


@pytest.mark.parametrize("url", [
    "http://www.sec.gov/Archives/edgar/data/66740/000006674023000014/doc.htm",
    "https://evil.example.com/Archives/edgar/data/66740/x.htm",
    "https://www.sec.gov.evil.example/Archives/edgar/data/66740/x.htm",
    "https://www.sec.gov/submissions/CIK0000066740.json",
    "https://www.sec.gov/Archives/../../etc/passwd",
    "file:///etc/passwd",
    "https://www.sec.gov/Archives/edgar/data/1/%2e%2e/private",
    "https://www.sec.gov/Archives/edgar/data/1/../../etc/passwd",
    "https://www.sec.gov/Archives/edgar/data/1/doc.htm?redirect=evil",
    "https://user:pass@www.sec.gov/Archives/edgar/data/1/doc.htm",
    "",
    None,
])
def test_live_fetch_refuses_urls_outside_the_approved_endpoint(url):
    assert fetch_source_bytes(url, "AtlasQuant/0.1 ops@example.com") is None


def test_live_fetch_requires_a_declared_user_agent():
    url = "https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/doc.htm"
    assert fetch_source_bytes(url, None) is None
    assert fetch_source_bytes(url, "") is None


def test_manifest_with_wrong_schema_is_rejected(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text('{"schema": "something-else", "documents": {}}', encoding="utf-8")
    with pytest.raises(VerificationError):
        TrustedEvidence.from_manifest_file(path)


def test_snapshot_takes_precedence_over_network():
    """A local snapshot is used without any network call, even when live fetching is enabled."""
    manifest = {"schema": MANIFEST_SCHEMA, "documents": {}}
    evidence = TrustedEvidence(manifest=manifest, snapshots={"A": b"bytes"}, live_sec=True,
                               user_agent="AtlasQuant/0.1 ops@example.com")
    payload, route = evidence.source_bytes("A", {})
    assert payload == b"bytes"
    assert route == "snapshot"


def test_unavailable_network_is_reported_not_raised():
    """An unreachable host must produce missing evidence, not an exception mid-verification."""
    manifest = {"schema": MANIFEST_SCHEMA, "documents": {}}
    evidence = TrustedEvidence(
        manifest=manifest, live_sec=True, user_agent="AtlasQuant/0.1 ops@example.com")
    payload, route = evidence.source_bytes(
        "MISSING", {"primary_document_url": "https://www.sec.gov/Archives/edgar/data/1/x.htm"})
    assert route in {"unavailable", "sec_live"}
    assert payload is None or isinstance(payload, bytes)
