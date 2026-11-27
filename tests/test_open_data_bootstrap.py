"""Offline contract tests for the public-source snapshot downloader."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("fetch_open_data", ROOT / "scripts/fetch_open_data.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Response(io.BytesIO):
    def __init__(self, data, url):
        super().__init__(data)
        self.url = url

    def geturl(self):
        return self.url


def test_snapshot_and_exact_hash(tmp_path):
    data = b'{"facts":{}}'
    dataset = {"id": "test", "url": "https://example.org/data", "kind": "json",
               "filename": "data.json", "max_bytes": 100}
    path = mod.fetch(dataset, tmp_path, "test@example.org",
                     lambda req, **kw: Response(data, req.full_url))
    manifest = json.loads((path / "manifest.json").read_text())
    assert (path / "data.json").read_bytes() == data
    assert manifest["files"][0]["sha256"] == hashlib.sha256(data).hexdigest()


def test_bad_payload_not_published(tmp_path):
    dataset = {"id": "test", "url": "https://example.org/data", "kind": "json",
               "filename": "data.json", "max_bytes": 100}
    with pytest.raises(ValueError):
        mod.fetch(dataset, tmp_path, "test@example.org",
                  lambda req, **kw: Response(b"not-json", req.full_url))
    assert not list((tmp_path / "test").iterdir())


def test_size_limit(tmp_path):
    with pytest.raises(ValueError, match="byte limit"):
        mod.download("https://example.org/data", tmp_path / "data", 2, "test",
                     lambda req, **kw: Response(b"abc", req.full_url))


def test_pagination(tmp_path, monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda _: None)
    dataset = {"id": "test", "url": "https://example.org/data",
               "kind": "fiscal_api", "max_bytes": 10000}
    def opener(req, **kw):
        n = 2 if "page%5Bnumber%5D=2" in req.full_url else 1
        payload = {"data": [{"record_date": str(n)}],
                   "meta": {"total-pages": 2, "total-count": 2}}
        return Response(json.dumps(payload).encode(), req.full_url)
    path = mod.fetch(dataset, tmp_path, "test@example.org", opener)
    assert len(json.loads((path / "manifest.json").read_text())["files"]) == 2


def test_catalog():
    data = json.loads(mod.CATALOG.read_text())
    ids = [d["id"] for d in data["datasets"]]
    assert len(ids) == len(set(ids))
    assert all(d["url"].startswith("https://") and d["policy_url"].startswith("https://")
               and d["rights"] and d["max_bytes"] > 0 for d in data["datasets"])


@pytest.mark.parametrize("kind,raw", [("csv", b"date,yield\n1990-01-02,7.94\n"),
                                     ("tsv", b"series\tvalue\nA\t1\n")])
def test_tabular_archives(tmp_path, kind, raw):
    dataset = {"id": "test", "url": "https://example.org/data",
               "kind": kind, "filename": "data." + kind, "max_bytes": 1000}
    out = mod.fetch(dataset, tmp_path, "test@example.org",
                    lambda req, **kw: Response(raw, req.full_url))
    assert (out / dataset["filename"]).read_bytes() == raw


def test_yield_sample():
    import csv
    from decimal import Decimal
    path = ROOT / "data/open_data/samples/treasury_yields_1990_01.csv"
    with path.open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 21
    dates = [r["record_date"] for r in rows]
    assert dates == sorted(set(dates))
    assert dates[0] == "1990-01-02" and dates[-1] == "1990-01-31"
    assert rows[0]["yield_10y_pct"] == "7.94"
    assert rows[-1]["yield_30y_pct"] == "8.46"
    assert all(len(r) == 10 and all(Decimal(v).is_finite() for k, v in r.items()
                                  if k != "record_date") for r in rows)
