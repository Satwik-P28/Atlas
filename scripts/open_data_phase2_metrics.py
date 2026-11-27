#!/usr/bin/env python3
"""Collect the measured Phase II artifact.

Every number in the report is produced here from the store, the index, the integrated
Atlas database and the release index. Nothing is copied by hand, and a missing store is
reported as missing rather than replaced with a remembered figure.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data.durable import DEFAULT_MANIFESTS, inventory  # noqa: E402
from atlas.open_data.registry import Registry  # noqa: E402
from atlas.open_data.research import run_models  # noqa: E402
from atlas.open_data.store import SnapshotStore  # noqa: E402
from atlas.storage.db import open_database  # noqa: E402
from atlas.terminal import read_models  # noqa: E402


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open-root", default="/tmp/atlas_raw_store")
    parser.add_argument("--open-db", default="/tmp/atlas_raw_store/index.db")
    parser.add_argument("--atlas-db", default="/tmp/atlas.db")
    parser.add_argument("--out", default="artifacts/open_data_phase2.json")
    parser.add_argument("--models", type=int, default=25)
    parser.add_argument("--refresh-rights", action="store_true",
                        help="Re-derive only the rights fields of an existing --out artifact from "
                             "the current registry. The store is not read, because a rights "
                             "reclassification must not require re-acquiring the bytes.")
    args = parser.parse_args(argv)

    registry = Registry.load()
    if args.refresh_rights:
        target = Path(args.out)
        payload = json.loads(target.read_text(encoding="utf-8"))
        refreshed = 0
        for entry in payload.get("datasets") or []:
            try:
                dataset = registry.get(entry["dataset_id"])
            except KeyError:
                continue
            entry["manifest_rights_class"] = (entry.get("manifest_rights_class")
                                              or entry.get("rights_class"))
            entry["rights_class"] = dataset.rights_class.value
            refreshed += 1
        payload["rights_refreshed_at"] = utcnow()
        payload["rights_source"] = "registry"
        target.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"refreshed": refreshed, "out": str(target)}, indent=2))
        return 0

    store = SnapshotStore(args.open_root)
    durability = inventory(store, registry, manifests_root=DEFAULT_MANIFESTS)

    datasets = []
    for snapshot in store.list_snapshots():
        stats = snapshot.manifest.get("stats") or {}
        extras = stats.get("extra") or {}
        manifest_rights = (snapshot.manifest.get("rights") or {}).get("rights_class")
        try:
            dataset = registry.get(snapshot.dataset_id)
        except KeyError:
            dataset = None
        datasets.append({
            "dataset_id": snapshot.dataset_id,
            "snapshot_id": snapshot.snapshot_id,
            "files": len(snapshot.files),
            "stored_bytes": sum(int(entry.get("bytes") or 0) for entry in snapshot.files),
            "decompressed_bytes": stats.get("decompressed_bytes"),
            "source_records": stats.get("record_count"),
            "unique_entities": stats.get("entity_count"),
            "obs_start": stats.get("obs_start"),
            "obs_end": stats.get("obs_end"),
            "observation_limit": extras.get("observation_limit_applied"),
            "partial_scope": extras.get("partial_scope"),
            "issues": [issue.get("code") for issue in stats.get("issues") or []],
            "rights_class": dataset.rights_class.value if dataset else manifest_rights,
            "manifest_rights_class": manifest_rights,
        })

    index_counts = {"source_records": 0, "observations": 0}
    if Path(args.open_db).exists():
        connection = sqlite3.connect(f"file:{args.open_db}?mode=ro", uri=True)
        try:
            index_counts["source_records"] = connection.execute(
                "SELECT COALESCE(SUM(acquired_records),0) FROM coverage"
            ).fetchone()[0]
            index_counts["observations"] = connection.execute(
                "SELECT COUNT(*) FROM observation"
            ).fetchone()[0]
            index_counts["snapshots"] = connection.execute("SELECT COUNT(*) FROM snapshot").fetchone()[0]
            index_counts["runs_failed"] = connection.execute(
                "SELECT COUNT(*) FROM acquisition_run WHERE status='failed'"
            ).fetchone()[0]
        finally:
            connection.close()

    atlas = {}
    timings = {}
    models = {}
    if Path(args.atlas_db).exists():
        db = open_database(args.atlas_db)
        try:
            atlas = {
                "issuers": int(db.scalar("SELECT COUNT(*) FROM issuer", default=0) or 0),
                "issuers_with_evidence": int(db.scalar(
                    "SELECT COUNT(DISTINCT entity_id) FROM evidence", default=0) or 0),
                "evidence_facts": int(db.scalar("SELECT COUNT(*) FROM evidence", default=0) or 0),
                "securities": int(db.scalar("SELECT COUNT(*) FROM security", default=0) or 0),
                "ticker_assignments": int(db.scalar(
                    "SELECT COUNT(*) FROM ticker_assignment", default=0) or 0),
                "issuers_with_sic": int(db.scalar(
                    "SELECT COUNT(*) FROM issuer WHERE sic IS NOT NULL", default=0) or 0),
                "supersessions": int(db.scalar(
                    "SELECT COUNT(*) FROM evidence_supersession", default=0) or 0),
                "schema_version": db.schema_version(),
                "bars": int(db.scalar("SELECT COUNT(*) FROM bar", default=0) or 0),
            }
            issuer = db.query_one(
                "SELECT iss.cik FROM issuer iss JOIN evidence e ON e.entity_id=iss.issuer_id "
                "GROUP BY iss.issuer_id ORDER BY COUNT(*) DESC LIMIT 1"
            )
            if issuer:
                start = time.perf_counter()
                statement = read_models.statements(db, issuer["cik"], statement="income",
                                                   period="FY", limit=6)
                timings["statement_seconds"] = round(time.perf_counter() - start, 3)
                timings["statement_rows"] = len(statement["rows"])
                timings["cik"] = issuer["cik"]
        finally:
            db.close()
        models = run_models(args.atlas_db, limit=args.models)

    release_index = ROOT / "data/open_data/releases/index.json"
    release = json.loads(release_index.read_text(encoding="utf-8")) if release_index.exists() else None
    audit_path = ROOT / "artifacts/open_data_audit.json"
    audit = None
    if audit_path.exists():
        payload = json.loads(audit_path.read_text(encoding="utf-8"))
        audit = {
            "registry": payload.get("registry"),
            "endpoint_failures": len(payload.get("endpoint_failures") or []),
            "endpoint_transient": len(payload.get("endpoint_transient") or []),
            "samples_ok": (payload.get("samples") or {}).get("ok"),
        }

    payload = {
        "schema": "atlas.open_data.phase2_metrics.v1",
        "generated_at": utcnow(),
        "store_root": str(store.root),
        "durability": {key: durability[key] for key in (
            "datasets", "snapshots", "by_status", "latest_datasets", "latest_by_status",
            "latest_verified_datasets", "source_bytes_committed", "stored_bytes_present",
            "by_acquisition_scope",
        )},
        "datasets": datasets,
        "index": index_counts,
        "atlas": atlas,
        "timings": timings,
        "models": {key: models.get(key) for key in (
            "issuers", "executed", "economically_supported",
        )},
        "model_items": models.get("items", [])[:25],
        "release": release,
        "audit": audit,
        "limitations": [
            "The previous /tmp raw store did not survive the workspace; current bytes were re-acquired from providers and hashed against the manifests exported now.",
            "Provider archives are revised, so a re-acquisition is not guaranteed to reproduce an older snapshot byte for byte.",
            "FSDS is 5.7 GB and is not a single release asset; it is recoverable from 70 official URLs recorded in its manifest.",
            "Insider archives have one provider gap (2026 Q3 was not published at acquisition time).",
            "No redistributable market-price provider was found; price data is local/authorised only.",
        ],
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in (
        "generated_at", "durability", "index", "atlas", "timings", "models",
    )}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
