#!/usr/bin/env python
"""Verify that the committed fixtures are distributable and that the market path works.

Checks, in order:

1. no restricted vendor market file is present under ``fixtures/``;
2. the synthetic hash manifest matches the tracked bytes;
3. the market manifest declares synthetic, vendor-free, public-domain terms;
4. a synthetic import, a correction and an exact pin replay work in a throwaway database
   using only committed fixtures;
5. optionally (``--require-demo-db``) the demo database was built and its market series is
   labelled synthetic.

Exit status is 0 only when every check passes. The script touches nothing outside a
temporary directory, so it is safe to run in an ordinary CI checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.entities.master import SecurityMaster  # noqa: E402
from atlas.research.prices import (  # noqa: E402
    import_price_series,
    price_for_pin,
    price_on_or_before,
)
from atlas.storage.db import Database  # noqa: E402
from atlas.storage.sources import ensure_default_sources  # noqa: E402

MARKET = ROOT / "fixtures" / "market"
VENDOR_PREFIXES = ("nasdaq_", "ibm_")
VENDOR_SUFFIXES = ("_alphavantage.json",)


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def check_no_vendor_files() -> int:
    hits = []
    for path in (ROOT / "fixtures").rglob("*"):
        if not path.is_file():
            continue
        name = path.name
        if name.startswith(VENDOR_PREFIXES) or name.endswith(VENDOR_SUFFIXES):
            hits.append(path.relative_to(ROOT).as_posix())
    if hits:
        fail(f"restricted vendor market fixtures are tracked: {hits}")
    return 0


def check_hashes() -> int:
    manifest = json.loads((MARKET / "synthetic_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("synthetic") is not True or manifest.get("contains_vendor_data") is not False:
        fail("synthetic hash manifest must declare synthetic=true and contains_vendor_data=false")
    for entry in manifest["files"]:
        payload = (ROOT / entry["path"]).read_bytes()
        if len(payload) != entry["bytes"]:
            fail(f"{entry['path']} has {len(payload)} bytes, expected {entry['bytes']}")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != entry["sha256"]:
            fail(f"{entry['path']} sha256 drifted: {digest}")
    return len(manifest["files"])


def check_market_manifest() -> dict:
    manifest = json.loads((MARKET / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("synthetic") is not True or manifest.get("contains_vendor_data") is not False:
        fail("fixtures/market/manifest.json must declare a synthetic, vendor-free dataset")
    from atlas.research import rights as data_rights

    decision = data_rights.classify(
        manifest.get("redistribution"),
        copyright_licence=manifest.get("copyright_licence"),
        copyright_holder=manifest.get("copyright_holder"),
    )
    if decision["redistribution"] != data_rights.PROJECT_AUTHORED:
        fail(
            "the synthetic fixture must be classified project_authored, not public_domain: "
            "project authorship is a copyright licence, not a public-domain dedication"
        )
    if not decision["export_allowed"]:
        fail("project-authored original fixtures must remain exportable")
    if not manifest.get("copyright_licence"):
        fail("project-authored fixtures must declare their copyright licence")
    if not manifest.get("authorization_basis"):
        fail("a redistributable fixture must state its authorization basis")
    for series in manifest["series"]:
        if not (ROOT / series["path"]).exists():
            fail(f"manifest references a missing series: {series['path']}")
    return manifest


def check_market_pipeline(manifest: dict) -> dict:
    import csv

    with tempfile.TemporaryDirectory() as directory:
        db = Database(Path(directory) / "fixtures.db")
        db.migrate()
        ensure_default_sources(db)
        master = SecurityMaster(db)
        master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
        issuer = master.register_issuer(legal_name="Atlas Synthetic Markets Corp", cik="0009999999", sic="9999")
        security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
        listing = master.ensure_listing(security, "XNAS", valid_from="2019-01-01", is_primary=True)
        master.assign_ticker(
            listing, "ATLS", valid_from="2019-01-01", confidence=1.0, status="confirmed",
            source_id="sec-edgar", evidence_note="Synthetic fixture identity.",
        )
        with (ROOT / manifest["series"][0]["path"]).open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        imported = import_price_series(
            db, ticker="ATLS", rows=rows,
            source_name="Atlas synthetic market fixture", licence=manifest["licence"],
            redistribution=manifest["redistribution"],
            adjustment_semantics=manifest["adjustment_semantics"],
            retrieved_at="2024-12-13T21:00:00Z",
            authorization_basis=manifest["authorization_basis"],
            collection_method="synthetic_fixture", security_id=security, mic="XNAS",
        )
        selected = price_on_or_before(db, security, "2024-12-13")
        pin = selected["pin"]
        replay = price_for_pin(db, pin)
        if not replay["exact_replay"]:
            fail(f"exact pin replay failed: {replay['status']}")
        if replay["price"]["close"] != selected["close"]:
            fail("pinned replay returned a different value")
        if imported["session_identity"]["sessions_checked"] != len(rows):
            fail("session identity was not verified for every observed session")
        db.close()
        return {
            "rows": len(rows),
            "cells": len(rows) * 5,
            "observation_id": pin["observation_id"],
            "revision_seq": pin["revision_seq"],
            "exact_replay": replay["exact_replay"],
            "export_allowed": imported["source"]["export_allowed"],
        }


def check_demo_db() -> dict:
    path = ROOT / "var" / "atlas.db"
    if not path.exists():
        fail("--require-demo-db was requested but var/atlas.db does not exist")
    db = Database(path, create=False)
    row = db.query_one(
        "SELECT s.name, s.kind, s.redistribution, COUNT(*) AS rows FROM bar b "
        "JOIN source s ON s.source_id = b.source_id GROUP BY s.source_id ORDER BY rows DESC"
    )
    db.close()
    if row is None:
        fail("the demo database contains no market observations")
    if str(row["kind"]) != "synthetic":
        fail(f"the demo market series is not registered as synthetic (kind={row['kind']})")
    return {"source": row["name"], "kind": row["kind"], "redistribution": row["redistribution"], "rows": int(row["rows"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-demo-db", action="store_true")
    args = parser.parse_args()

    check_no_vendor_files()
    hashed = check_hashes()
    manifest = check_market_manifest()
    pipeline = check_market_pipeline(manifest)
    result: dict = {
        "schema": "atlas.distributable_fixtures.v1",
        "vendor_files_present": False,
        "hashed_files": hashed,
        "market_pipeline": pipeline,
        "status": "pass",
    }
    if args.require_demo_db:
        result["demo_db"] = check_demo_db()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
