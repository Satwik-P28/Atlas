#!/usr/bin/env python3
"""Package every dataset in a validated release plan.

Economy datasets become one asset. Datasets the plan declared oversized become
multipart packages: period packages when the archive has recognisable
year/quarter members, otherwise deterministic byte slices. The plan is the only
input, so the workflow never re-parses human input.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data import multipart  # noqa: E402
from atlas.open_data.engine import AcquisitionEngine  # noqa: E402


def _package(dataset_id: str, out: Path, open_root: str, open_db: str) -> dict:
    target = out / f"{dataset_id}.tar.zst"
    index = out / f"{dataset_id}.index.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/build_open_data_package.py"),
         "--dataset", dataset_id, "--out", str(target), "--index", str(index),
         "--open-root", open_root, "--open-db", open_db],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"packaging {dataset_id} failed: {result.stderr.strip()}")
    return {"dataset_id": dataset_id, "mode": "package", "asset": target.name,
            "bytes": target.stat().st_size}


def _multipart(dataset_id: str, out: Path, open_root: str, open_db: str,
               part_limit: int) -> dict:
    engine = AcquisitionEngine(store_root=open_root, index_path=open_db)
    try:
        snapshot = engine.store.latest(dataset_id)
        if snapshot is None:
            raise SystemExit(f"no stored snapshot for {dataset_id}")
        report = engine.store.verify(snapshot, deep=True)
        if not report["ok"]:
            raise SystemExit(f"{dataset_id} fails verification: {report['errors'][:3]}")
        if len(snapshot.files) != 1:
            raise SystemExit(f"{dataset_id} has {len(snapshot.files)} files; cannot multipart")
        source = snapshot.path / "files" / snapshot.files[0]["path"]
        detail = multipart.period_partitions(source)
        if len(detail) > 1 and all(period != "unpartitioned" for period in detail):
            built = multipart.build_period_parts(
                source, out, dataset_id=dataset_id, snapshot_id=snapshot.snapshot_id,
                part_limit=part_limit)
        else:
            built = multipart.split_source(
                source, out, dataset_id=dataset_id, snapshot_id=snapshot.snapshot_id,
                part_limit=part_limit)
        return {
            "dataset_id": dataset_id,
            "mode": built["mode"],
            "parts": len(built["parts"]),
            "bytes": sum(part["bytes"] for part in built["parts"]),
            "largest": max(part["bytes"] for part in built["parts"]),
            "periods": [item["period"] for item in built.get("periods") or []],
        }
    finally:
        engine.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", default="dist/release-plan.json")
    parser.add_argument("--out", default="dist")
    parser.add_argument("--part-limit", type=int, default=multipart.PART_LIMIT_BYTES)
    parser.add_argument("--open-root", default="/tmp/atlas_open_data")
    parser.add_argument("--open-db", default="/tmp/atlas_open_data/index.db")
    args = parser.parse_args(argv)

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    oversized = {item["dataset_id"] for item in plan.get("oversized") or []}
    built: list[dict] = []
    for item in plan.get("datasets") or []:
        dataset_id = item["dataset_id"]
        if dataset_id in oversized:
            built.append(_multipart(dataset_id, out, args.open_root, args.open_db,
                                    args.part_limit))
        else:
            built.append(_package(dataset_id, out, args.open_root, args.open_db))
    if not built:
        print("the plan selected no datasets", file=sys.stderr)
        return 1
    for entry in built:
        size = entry.get("largest") or entry.get("bytes") or 0
        if size > args.part_limit:
            print(f"{entry['dataset_id']} produced an asset above the limit: {size}",
                  file=sys.stderr)
            return 1
    print(json.dumps({"plan": args.plan, "packages": built}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
