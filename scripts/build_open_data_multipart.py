#!/usr/bin/env python3
"""Build multipart packages for a dataset that cannot be one release asset.

Two modes:

``bytes``   deterministic fixed-size slices of the exact source archive. Reassembly
            reproduces the original file byte for byte.
``period``  one package per reporting period (``2024q1``), so a user can install a
            single quarter without downloading the whole archive.

Only verified, currently rights-approved snapshots are packaged, exactly like the
single-asset builder. Nothing is uploaded here.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data import multipart  # noqa: E402
from atlas.open_data.engine import AcquisitionEngine  # noqa: E402
from atlas.open_data.rights import evaluate  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--snapshot", default=None, help="defaults to the latest snapshot")
    parser.add_argument("--mode", choices=["bytes", "period"], default="period")
    parser.add_argument("--out", default="dist")
    parser.add_argument("--part-limit", type=int, default=multipart.PART_LIMIT_BYTES)
    parser.add_argument("--open-root", default=os.environ.get("ATLAS_OPEN_DATA_ROOT", "var/open_data"))
    parser.add_argument("--open-db", default=os.environ.get("ATLAS_OPEN_DATA_DB",
                                                            "var/open_data/atlas_open_data.db"))
    args = parser.parse_args(argv)

    engine = AcquisitionEngine(store_root=args.open_root, index_path=args.open_db)
    try:
        dataset = engine.registry.get(args.dataset)
        decision = evaluate(dataset.raw, "publish", public_distribution=True)
        if not decision.allowed:
            print(f"REJECTED: {args.dataset} may not be distributed: {decision.reason}",
                  file=sys.stderr)
            return 1
        snapshots = engine.store.list_snapshots(args.dataset)
        if args.snapshot:
            snapshots = [item for item in snapshots if item.snapshot_id == args.snapshot]
        if not snapshots:
            print(f"no stored snapshot for {args.dataset}", file=sys.stderr)
            return 1
        snapshot = snapshots[-1]
        report = engine.store.verify(snapshot, deep=True)
        if not report["ok"]:
            print(f"REJECTED: {args.dataset}/{snapshot.snapshot_id} fails verification: "
                  f"{report['errors'][:3]}", file=sys.stderr)
            return 1
        if len(snapshot.files) != 1:
            print(f"{args.dataset} has {len(snapshot.files)} files; multipart packaging "
                  "expects a single source archive", file=sys.stderr)
            return 1
        entry = snapshot.files[0]
        source = snapshot.path / "files" / entry["path"]
        out = Path(args.out)
        if args.mode == "bytes":
            result = multipart.split_source(
                source, out, dataset_id=args.dataset, snapshot_id=snapshot.snapshot_id,
                part_limit=args.part_limit)
        else:
            result = multipart.build_period_parts(
                source, out, dataset_id=args.dataset, snapshot_id=snapshot.snapshot_id,
                part_limit=args.part_limit)
        print(json.dumps({
            "dataset_id": args.dataset,
            "snapshot_id": snapshot.snapshot_id,
            "mode": args.mode,
            "source_bytes": result["source"]["bytes"],
            "source_sha256": result["source"]["sha256"],
            "parts": len(result["parts"]),
            "part_bytes": sum(part["bytes"] for part in result["parts"]),
            "largest_part_bytes": max(part["bytes"] for part in result["parts"]),
            "periods": [item["period"] for item in result.get("periods") or []],
            "index": result["index"],
        }, indent=2))
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
