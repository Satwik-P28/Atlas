"""Offline tests for the rights-aware open-data engine.

No test in this module touches the network. Live acquisition is exercised by the
`open-data-live-smoke` workflow and by recorded manifests, not by unit tests.
"""
from __future__ import annotations

import io
import json
import zipfile
from email.message import Message
from pathlib import Path

import pytest

from atlas.open_data import archives, rights
from atlas.open_data.adapters import analyze_tabular, normalise_date
from atlas.open_data.engine import AcquisitionEngine
from atlas.open_data.index import Observation, OpenDataIndex
from atlas.open_data.registry import Registry, audit_rights, validate_payload
from atlas.open_data.store import SnapshotStore
from atlas.open_data.transport import (DownloadResult, HttpTransport, RedirectRefused,
                                       TransportConfig, TransportError)


# --------------------------------------------------------------------------- #
# Rights and registry
# --------------------------------------------------------------------------- #
def _dataset(**overrides):
    base = {
        "id": "test.dataset", "rights_class": "public_domain", "rights_verified_at": "2026-01-01",
        "redistribution": True, "commercial_use": True, "modification": True,
        "third_party_exclusions": [], "exclusions_cleared": False, "license_name": "PD",
        "license_url": "https://example.org/pd", "attribution_required": False,
        "attribution_text": "",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("rights_class,allowed", [
    ("public_domain", True), ("permissive", True), ("redistributable_conditions", True),
    ("local_use_only", False), ("restricted", False), ("unverified", False),
])
def test_only_three_classes_may_distribute(rights_class, allowed):
    decision = rights.evaluate(_dataset(rights_class=rights_class), "publish", public_distribution=True)
    assert decision.allowed is allowed


def test_unverified_cannot_be_acquired_automatically_or_manually():
    dataset = _dataset(rights_class="unverified", redistribution=False)
    assert not rights.evaluate(dataset, "acquire").allowed
    assert not rights.evaluate(dataset, "acquire", automated=True).allowed


def test_local_use_can_be_acquired_but_not_published():
    dataset = _dataset(rights_class="local_use_only", redistribution=False, commercial_use=False)
    assert rights.evaluate(dataset, "acquire").allowed
    assert not rights.evaluate(dataset, "publish").allowed


def test_stale_review_blocks_automated_work():
    dataset = _dataset(rights_verified_at="2020-01-01")
    assert rights.evaluate(dataset, "acquire", automated=True).allowed is False
    assert rights.evaluate(dataset, "acquire", automated=False).allowed is True


def test_third_party_exclusions_must_be_cleared():
    dataset = _dataset(third_party_exclusions=["vendor index"])
    decision = rights.evaluate(dataset, "publish", public_distribution=True)
    assert not decision.allowed and "third-party" in decision.reason
    dataset["exclusions_cleared"] = True
    assert rights.evaluate(dataset, "publish", public_distribution=True).allowed


def test_committed_registry_is_valid_and_denies_negative_results():
    registry = Registry.load()
    assert len(registry) >= 50
    payload = registry.payload
    assert validate_payload(payload) == []
    decisions = {row["id"]: row for row in audit_rights(payload)}
    assert decisions["fred.series"]["distribution_allowed"] is False
    assert decisions["market.equity_ohlcv"]["distribution_allowed"] is False
    assert decisions["sec.companyfacts"]["distribution_allowed"] is True
    # SEC bulk archives are compilations of issuer-authored filings. 17 USC 105 does not
    # reach registrant documents, so the categorical public-domain classification is wrong.
    assert decisions["sec.companyfacts"]["rights_class"] == "redistributable_conditions"
    sec_entry = registry.get("sec.companyfacts").raw
    assert sec_entry["issuer_authored"] is True
    assert "exclude" in sec_entry["license_name"].lower() or "issuer" in sec_entry["license_name"].lower()
    # Narrative note text is excluded, so the raw notes archive must not be publishable.
    assert decisions["sec.notes_data_sets"]["distribution_allowed"] is False


def test_registry_rejects_missing_licence_and_bad_class():
    payload = {
        "registry_version": 1,
        "datasets": [{
            **{k: v for k, v in _dataset().items() if k not in {"license_url"}},
            "provider": "X", "title": "T", "description": "D",
            "official_source_url": "https://example.org", "download_endpoint": "https://example.org/x",
            "rights_evidence": "e", "geographic_coverage": "US",
            "historical_coverage": {"start": None, "end": None}, "update_frequency": "daily",
            "auth_required": False, "expected_size_bytes": None, "schema_version": "1",
            "ingestion_status": "discovered", "adapter": "archive", "formats": ["zip"],
            "third_party_exclusions": [],
        }],
    }
    errors = validate_payload(payload)
    assert any("license_url" in error for error in errors)
    bad = json.loads(json.dumps(payload))
    bad["datasets"][0]["rights_class"] = "probably_fine"
    bad["datasets"][0]["license_url"] = "https://example.org/licence"
    assert any("rights_class" in error for error in validate_payload(bad))


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #
class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str, status: int = 200, headers=None):
        super().__init__(data)
        self.url = url
        self.status = status
        message = Message()
        for key, value in (headers or {}).items():
            message[key] = value
        self.headers = message

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_transport_refuses_cross_host_redirect(tmp_path):
    opener = FakeOpener([FakeResponse(b"data", "https://evil.example.org/file")])
    transport = HttpTransport(TransportConfig(default_rate_limit=None), opener=opener)
    with pytest.raises(RedirectRefused):
        transport.download("https://example.org/file", tmp_path / "file")
    assert not (tmp_path / "file").exists()


def test_transport_retries_503_then_succeeds(tmp_path):
    import urllib.error
    error = urllib.error.HTTPError("https://example.org/f", 503, "unavailable", Message(), None)
    opener = FakeOpener([error, FakeResponse(b"payload", "https://example.org/f")])
    transport = HttpTransport(TransportConfig(default_rate_limit=None, backoff_base=0.0), opener=opener)
    result = transport.download("https://example.org/f", tmp_path / "f")
    assert result.bytes_downloaded == 7 and result.attempts == 2
    assert (tmp_path / "f").read_bytes() == b"payload"


def test_transport_resume_uses_range_and_206(tmp_path):
    part = tmp_path / "f.part"
    part.write_bytes(b"head")
    opener = FakeOpener([FakeResponse(b"tail", "https://example.org/f", status=206,
                                      headers={"Content-Range": "bytes 4-7/8", "Content-Length": "4"})])
    transport = HttpTransport(TransportConfig(default_rate_limit=None), opener=opener)
    result = transport.download("https://example.org/f", tmp_path / "f")
    assert result.resumed_from == 4
    assert (tmp_path / "f").read_bytes() == b"headtail"
    assert opener.requests[0].get_header("Range") == "bytes=4-"


def test_transport_refuses_oversized_declared_download(tmp_path):
    opener = FakeOpener([FakeResponse(b"1234567890", "https://example.org/f",
                                      headers={"Content-Length": "10"})])
    transport = HttpTransport(TransportConfig(default_rate_limit=None), opener=opener)
    with pytest.raises(Exception, match="exceeds limit"):
        transport.download("https://example.org/f", tmp_path / "f", max_bytes=5)


def test_transport_rejects_short_read(tmp_path):
    opener = FakeOpener([FakeResponse(b"abc", "https://example.org/f", headers={"Content-Length": "10"})])
    transport = HttpTransport(TransportConfig(default_rate_limit=None), opener=opener)
    with pytest.raises(TransportError, match="short read"):
        transport.download("https://example.org/f", tmp_path / "f")


# --------------------------------------------------------------------------- #
# Archives
# --------------------------------------------------------------------------- #
def _zip(path: Path, members: dict[str, bytes], symlink: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (0o120777 << 16)
            archive.writestr(info, "/etc/passwd")
    return path


def test_archive_rejects_path_traversal(tmp_path):
    path = _zip(tmp_path / "bad.zip", {"../evil.txt": b"x"})
    with pytest.raises(archives.ArchiveRejected, match="traversal"):
        archives.inspect(path)


def test_archive_rejects_symlink(tmp_path):
    path = _zip(tmp_path / "link.zip", {"ok.txt": b"x"}, symlink="link")
    with pytest.raises(archives.ArchiveRejected, match="symlink"):
        archives.inspect(path)


def test_archive_rejects_absolute_path(tmp_path):
    path = _zip(tmp_path / "abs.zip", {"/etc/evil": b"x"})
    with pytest.raises(archives.ArchiveRejected, match="absolute"):
        archives.inspect(path)


def test_archive_rejects_bomb_ratio(tmp_path):
    path = _zip(tmp_path / "bomb.zip", {"zeros.txt": b"\0" * 2_000_000})
    with pytest.raises(archives.ArchiveRejected, match="ratio"):
        archives.inspect(path, archives.ArchiveLimits(max_compression_ratio=10))


def test_safe_extraction_roundtrip_and_limits(tmp_path):
    path = _zip(tmp_path / "ok.zip", {"dir/a.txt": b"alpha", "b.txt": b"beta"})
    written = archives.safe_extract(path, tmp_path / "out")
    assert {p.relative_to(tmp_path / "out").as_posix() for p in written} == {"dir/a.txt", "b.txt"}
    assert (tmp_path / "out/dir/a.txt").read_bytes() == b"alpha"
    with pytest.raises(archives.ArchiveRejected):
        archives.safe_extract(path, tmp_path / "out")


# --------------------------------------------------------------------------- #
# Snapshot store
# --------------------------------------------------------------------------- #
def test_store_commit_verify_and_tamper_detection(tmp_path):
    store = SnapshotStore(tmp_path)
    staging = store.new_staging("test.dataset")
    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")
    entry = store.add_file(staging, source, name="source.bin")
    snapshot = store.commit(staging, {"dataset_id": "test.dataset", "files": [entry],
                                      "source": {"etag": "abc"}})
    assert snapshot.snapshot_id.startswith("20")
    report = store.verify(snapshot)
    assert report["ok"] and report["files"][0]["sha256"] == entry["sha256"]
    target = snapshot.path / "files" / "source.bin"
    with pytest.raises(PermissionError):
        target.write_bytes(b"tampered")
    target.chmod(0o644)
    target.write_bytes(b"tampered")
    assert store.verify(snapshot)["ok"] is False


def test_store_deduplicates_identical_blobs(tmp_path):
    store = SnapshotStore(tmp_path)
    for index in range(2):
        staging = store.new_staging("test.dataset")
        source = tmp_path / f"source{index}.bin"
        source.write_bytes(b"same bytes")
        entry = store.add_file(staging, source, name="data.bin")
        store.commit(staging, {"dataset_id": "test.dataset", "files": [entry],
                               "natural_key": index})
    report = store.storage_report()
    assert report["unique_blobs"] == 1
    assert report["deduplicated_blob_bytes"] == len(b"same bytes")


def test_store_quarantines_abandoned_staging(tmp_path):
    store = SnapshotStore(tmp_path)
    staging = store.new_staging("test.dataset")
    moved = store.quarantine(staging, "test.dataset", "simulated crash")
    assert (moved / "quarantine.json").exists()
    assert store.list_snapshots("test.dataset") == []


# --------------------------------------------------------------------------- #
# Index: idempotency, revisions, point-in-time
# --------------------------------------------------------------------------- #
def test_observations_are_idempotent_and_restatements_are_appended(tmp_path):
    index = OpenDataIndex(tmp_path / "index.db")
    first = Observation(dataset_id="test.dataset", series_key="series", obs_date="2024-01-01",
                        value_numeric="1.0", unit="index", published_at="2024-02-01T00:00:00Z")
    assert index.ingest_observations([first], snapshot_id="s1")["inserted"] == 1
    assert index.ingest_observations([first], snapshot_id="s2")["duplicates"] == 1
    restated = Observation(dataset_id="test.dataset", series_key="series", obs_date="2024-01-01",
                           value_numeric="1.5", unit="index", published_at="2024-03-01T00:00:00Z")
    result = index.ingest_observations([restated], snapshot_id="s3")
    assert result["inserted"] == 1 and result["revisions"] == 1
    rows = index.observations("test.dataset", latest_only=False)
    assert len(rows) == 2
    assert {row["revision_seq"] for row in rows} == {1, 2}
    assert len(index.observations("test.dataset")) == 1
    assert index.observations("test.dataset")[0]["value_numeric"] == "1.5"
    index.close()


def test_as_of_never_infers_publication_time(tmp_path):
    index = OpenDataIndex(tmp_path / "index.db")
    unknown = Observation(dataset_id="d", series_key="s", obs_date="2020-01-01", value_numeric="1")
    published = Observation(dataset_id="d", series_key="s2", obs_date="2020-01-01",
                            value_numeric="2", published_at="2020-02-01T00:00:00Z")
    index.ingest_observations([unknown, published], snapshot_id="snap")
    assert [row["series_key"] for row in index.observations("d", as_of="2021-01-01")] == ["s2"]
    index.close()


def test_concurrent_ingestion_into_the_same_index(tmp_path):
    import threading
    path = tmp_path / "index.db"
    OpenDataIndex(path).close()
    errors: list[Exception] = []

    def worker(dataset_id: str) -> None:
        try:
            store = OpenDataIndex(path)
            observations = [
                Observation(dataset_id=dataset_id, series_key=f"s{number}", obs_date="2024-01-15",
                            value_numeric=str(number)) for number in range(1, 41)
            ]
            store.ingest_observations(observations, snapshot_id=f"snap-{dataset_id}")
            store.close()
        except Exception as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"d{number}",)) for number in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    index = OpenDataIndex(path)
    assert len(index.observations("d0", limit=100)) == 40
    assert len(index.observations("d1", limit=100)) == 40
    index.close()


def test_coverage_keeps_acquired_and_observed_counts_separate(tmp_path):
    index = OpenDataIndex(tmp_path / "index.db")
    entry = {"id": "d", "provider": "P", "title": "T", "rights_class": "public_domain",
             "license_name": "PD", "license_url": "https://x", "redistribution": True,
             "commercial_use": True}
    index.register(entry)

    class FakeSnapshot:
        snapshot_id = "s1"
        dataset_id = "d"
        manifest_sha256 = "abc"
        path = Path("snapshots/d/s1")
        manifest = {"completed_at": "2026-01-01T00:00:00Z", "source": {}}
        files = []

    index.record_snapshot(FakeSnapshot(), validation_status="valid", rights_class="public_domain",
                          redistributable=True, stats={"record_count": 100, "entity_count": 4,
                                                       "obs_start": "1990-01-01", "obs_end": "2020-01-01"})
    index.ingest_observations([Observation(dataset_id="d", series_key="s", obs_date="2020-01-01",
                                           value_numeric="1")], snapshot_id="s1")
    metrics = index.dashboard()
    assert metrics["datasets_downloaded"] == 1
    assert metrics["datasets_with_observations"] == 1
    assert metrics["datasets_integrated"] == 0  # typed rows are not an Atlas evidence bridge
    assert metrics["datasets_discovered"] == 1
    index.close()


# --------------------------------------------------------------------------- #
# Adapters
# --------------------------------------------------------------------------- #
def test_date_and_decimal_normalisation():
    assert normalise_date("01/02/1990") == "1990-01-02"
    assert normalise_date("2024-03-31T12:00:00Z") == "2024-03-31"
    assert normalise_date("not-a-date") is None


def test_tabular_adapter_reads_wide_yield_curve(tmp_path):
    path = tmp_path / "yields.csv"
    path.write_text("Date,1 Mo,10 Yr\n01/02/1990,7.5,7.94\n01/03/1990,7.6,\n")
    analysis = __import__("atlas.open_data.adapters", fromlist=["Analysis"]).Analysis()
    dataset = {"id": "treasury.test", "adapter": "tabular",
               "parse": {"mode": "wide", "date_column": "Date", "unit": "percent"},
               "download_endpoint": "https://example.org"}
    analyze_tabular(dataset, {"yields.csv": path}, analysis)
    assert analysis.record_count == 2
    assert len(analysis.observations) == 3
    assert analysis.obs_start == "1990-01-02" and analysis.obs_end == "1990-01-03"
    assert {o.series_key for o in analysis.observations} == {
        "treasury.test.1_mo", "treasury.test.10_yr"}


# --------------------------------------------------------------------------- #
# Engine (offline, fake transport)
# --------------------------------------------------------------------------- #
def _engine(tmp_path, dataset, payload: bytes = b"Date,10 Yr\n01/02/1990,7.94\n"):
    registry_payload = {
        "registry_version": 1,
        "datasets": [{
            "id": dataset, "provider": "TEST", "title": "test", "description": "test",
            "official_source_url": "https://example.org", "download_endpoint": "https://example.org/data.csv",
            "license_name": "public domain", "license_url": "https://example.org/licence",
            "rights_class": "public_domain", "rights_verified_at": "2026-01-01",
            "rights_evidence": "test", "commercial_use": True, "redistribution": True,
            "modification": True, "attribution_required": False, "attribution_text": "",
            "third_party_exclusions": [], "geographic_coverage": "US",
            "historical_coverage": {"start": "1990-01-01", "end": None},
            "update_frequency": "daily", "auth_required": False, "expected_size_bytes": 1000,
            "schema_version": "1", "ingestion_status": "implemented", "adapter": "tabular",
            "formats": ["csv"],
            "acquisition": {"kind": "bulk", "filename": "data.csv", "max_bytes": 10_000},
            "parse": {"mode": "wide", "date_column": "Date", "unit": "percent"},
        }],
    }
    registry = Registry(registry_payload)
    engine = AcquisitionEngine(
        registry=registry, store=SnapshotStore(tmp_path / "store"),
        index=OpenDataIndex(tmp_path / "index.db"),
        transport=HttpTransport(TransportConfig(default_rate_limit=None)),
        store_root=tmp_path / "store", index_path=tmp_path / "index.db",
    )

    def fake_head(url, **kwargs):
        return {"status": 200, "etag": "abc", "content_length": len(payload)}

    def fake_download(url, destination, **kwargs):
        Path(destination).write_bytes(payload)
        return DownloadResult(url=url, final_url=url, status=200, path=Path(destination),
                              bytes_downloaded=len(payload), sha256="0" * 64, etag="abc",
                              content_length=len(payload), elapsed_seconds=0.01, attempts=1)

    engine.transport.head = fake_head
    engine.transport.download = fake_download
    return engine


def test_engine_acquires_validates_and_manifests(tmp_path):
    engine = _engine(tmp_path, "test.dataset")
    result = engine.acquire("test.dataset")
    assert result.status == "acquired" and result.snapshot_id
    snapshot = engine.store.latest("test.dataset")
    manifest = json.loads((snapshot.path / "manifest.json").read_text())
    assert manifest["rights"]["rights_class"] == "public_domain"
    import hashlib
    assert manifest["files"][0]["sha256"] == hashlib.sha256(b"Date,10 Yr\n01/02/1990,7.94\n").hexdigest()
    assert manifest["validation"]["status"] == "valid"
    assert engine.verify("test.dataset")["ok"] is True
    assert engine.index.observations("test.dataset")[0]["value_numeric"] == "7.94"
    engine.close()


def test_engine_quarantines_invalid_payload(tmp_path):
    engine = _engine(tmp_path, "test.dataset", payload=b"a,b\n")
    result = engine.acquire("test.dataset")
    assert result.status == "failed"
    assert engine.store.latest("test.dataset") is None
    assert list((tmp_path / "store/quarantine/test.dataset").iterdir())
    engine.close()
