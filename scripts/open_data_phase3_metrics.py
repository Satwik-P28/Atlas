#!/usr/bin/env python3
"""Measure the Phase III release, restoration and integration facts.

Every number is read from a file or recomputed from bytes, never typed in by
hand:

* packages and hashes from the published mirror, re-hashed here;
* availability states from the release catalogue;
* restored snapshots from the store that a clean install produced;
* multipart part counts and sizes from the part indexes;
* integration counts from the Atlas database, when one is supplied.

The output deliberately records what did *not* happen (for example, no GitHub
upload) so a reader cannot mistake a local mirror for a real release.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data.durable import DEFAULT_MANIFESTS, inventory  # noqa: E402
from atlas.open_data.release import (  # noqa: E402
    DEFAULT_DOWNLOADS, DEFAULT_INDEX, read_downloads, read_release_index,
    release_catalog,
)
from atlas.open_data.registry import Registry  # noqa: E402
from atlas.open_data.store import SnapshotStore, sha256_file  # noqa: E402


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _multipart_summary(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    parts = payload.get("parts") or []
    return {
        "index": path,
        "dataset_id": payload.get("dataset_id"),
        "snapshot_id": payload.get("snapshot_id"),
        "mode": payload.get("mode"),
        "source_bytes": (payload.get("source") or {}).get("bytes"),
        "source_sha256": (payload.get("source") or {}).get("sha256"),
        "parts": len(parts),
        "part_bytes": sum(int(part.get("bytes") or 0) for part in parts),
        "largest_part_bytes": max((int(part.get("bytes") or 0) for part in parts), default=0),
        "periods": [part.get("period") for part in parts if part.get("period")],
        "per_part_sha256": [part.get("sha256") for part in parts],
    }


def _atlas_counts(path: str | None) -> dict:
    if not path or not Path(path).exists():
        return {}
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        def scalar(sql: str) -> int:
            try:
                return int(connection.execute(sql).fetchone()[0] or 0)
            except sqlite3.Error:
                return 0
        return {
            "issuers": scalar("SELECT COUNT(*) FROM issuer"),
            "evidence_facts": scalar("SELECT COUNT(*) FROM evidence"),
            "evidence_issuers": scalar("SELECT COUNT(DISTINCT entity_id) FROM evidence"),
            "securities": scalar("SELECT COUNT(*) FROM security"),
        }
    finally:
        connection.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--releases", default=str(DEFAULT_INDEX))
    parser.add_argument("--downloads", default=str(DEFAULT_DOWNLOADS))
    parser.add_argument("--mirror", default=None,
                        help="directory holding the published bytes; every file is re-hashed")
    parser.add_argument("--store", default=None, help="restored store to measure")
    parser.add_argument("--manifests", default=str(DEFAULT_MANIFESTS))
    parser.add_argument("--multipart", action="append", default=[],
                        help="a *.parts.json index to summarise")
    parser.add_argument("--atlas-db", default=None)
    parser.add_argument("--integration", default=None,
                        help="JSON written by `atlas data integrate sec-facts`")
    parser.add_argument("--github-uploaded", action="store_true",
                        help="set only when the GitHub API returned the assets")
    parser.add_argument("--github-url", default=None)
    parser.add_argument("--out", default="artifacts/open_data_phase3.json")
    args = parser.parse_args(argv)

    started = time.time()
    registry = Registry.load()
    index = read_release_index(args.releases)
    assets = []
    mirror = Path(args.mirror) if args.mirror else None
    for asset in index.get("assets") or []:
        row = {key: asset.get(key) for key in (
            "dataset_id", "snapshot_id", "asset", "asset_bytes", "asset_sha256",
            "rights_class", "license_name", "attribution_required", "mode")}
        if mirror and asset.get("asset"):
            published = mirror / str(asset["asset"])
            row["mirror_present"] = published.exists()
            row["mirror_bytes"] = published.stat().st_size if published.exists() else None
            if published.exists():
                digest = sha256_file(published)
                row["mirror_sha256"] = digest
                row["mirror_matches_index"] = digest == asset.get("asset_sha256")
        assets.append(row)

    import tempfile

    catalog_store = SnapshotStore(args.store or tempfile.mkdtemp(prefix="atlas-phase3-"))
    catalog = release_catalog(registry, catalog_store, index_path=args.releases,
                              downloads_path=args.downloads)
    restoration: dict = {}
    if args.store:
        store = SnapshotStore(args.store)
        report = inventory(store, registry, manifests_root=args.manifests)
        restoration = {
            "store": args.store,
            "snapshots": report["snapshots"],
            "verified_snapshots": report["verified_snapshots"],
            "durable_datasets": report["durable_datasets"],
            "stored_bytes_present": report["stored_bytes_present"],
            "restored_from_package": sum(
                1 for snapshot in store.list_snapshots()
                if snapshot.manifest.get("restored_from")),
            "datasets": sorted({snapshot.dataset_id for snapshot in store.list_snapshots()}),
        }

    payload = {
        "schema": "atlas.open_data.phase3.v1",
        "generated_at": utcnow(),
        "registry": {
            "datasets": len(list(registry)),
            "rights_approved_for_publication": catalog["summary"]["rights_approved_total"],
        },
        "release": {
            "tag": index.get("release_tag"),
            "assets_declared": len(assets),
            "asset_bytes_declared": sum(int(item.get("asset_bytes") or 0) for item in assets),
            "rights_source": index.get("rights_source"),
            "assets": assets,
            "mini_release_shas": [
                item for item in index.get("assets") or [] if item.get("asset_sha256")
            ],
        },
        "catalog": {
            "summary": catalog["summary"],
            "states": catalog["states"],
            "packaged": sorted(row["dataset_id"] for row in catalog["datasets"]
                               if row["state"] == "packaged"),
        },
        "downloads_recorded": len(read_downloads(args.downloads)),
        "restoration": restoration,
        "multipart": [_multipart_summary(path) for path in args.multipart],
        "integration": _atlas_counts(args.atlas_db),
        "github_publication": {
            "uploaded": bool(args.github_uploaded),
            "url": args.github_url,
            "reason": None if args.github_uploaded else (
                "No GitHub credential exists in this execution environment, so no asset was "
                "uploaded. Assets were published to a local mirror and installed from it; the "
                "GitHub path is implemented and dispatchable only from the default branch."
            ),
        },
        "elapsed_seconds": round(time.time() - started, 3),
    }
    if args.integration and Path(args.integration).exists():
        payload["integration_run"] = json.loads(Path(args.integration).read_text(encoding="utf-8"))
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(target), "assets": len(assets),
                      "states": payload["catalog"]["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
