#!/usr/bin/env python3
"""Write the committable index of a rights-gated open-data release.

The bulk assets stay outside Git. This index records exactly what was packaged: the
snapshot, the source manifest hash, the package hash and the rights decision. A fresh
installation can verify a downloaded asset against it and restore the original snapshot
identity without trusting the uploader's description.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data.registry import Registry  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def refresh_rights(target: Path) -> int:
    """Re-derive the rights fields of an existing index from the current registry.

    Package and manifest hashes are left untouched. A rights reclassification (for
    example, recategorising issuer-authored SEC filings from ``public_domain`` to
    ``redistributable_conditions``) must not require rebuilding the archived bytes, and
    a published index must never keep describing the superseded class.
    """
    payload = json.loads(target.read_text(encoding="utf-8"))
    registry = Registry.load()
    updated = []
    for asset in payload.get("assets") or []:
        try:
            dataset = registry.get(asset.get("dataset_id"))
        except KeyError:
            continue
        before = asset.get("rights_class")
        asset["manifest_rights_class"] = asset.get("manifest_rights_class") or before
        asset.update({
            "rights_class": dataset.rights_class.value,
            "license_name": dataset.get("license_name"),
            "license_url": dataset.get("license_url"),
            "attribution_required": dataset.get("attribution_required"),
            "attribution_text": dataset.get("attribution_text"),
        })
        updated.append({"dataset_id": asset["dataset_id"], "from": before,
                        "to": dataset.rights_class.value})
    payload["rights_refreshed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload["rights_source"] = "registry"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"index": str(target), "updated": updated}, indent=2))
    return 0


PART_KEYS = ("part", "name", "bytes", "sha256", "period", "offset", "members",
             "source_bytes", "asset_kind")


def _index_part(part: dict) -> dict:
    """Copy every field an installer needs, including a nested split.

    A period package above the asset limit is itself split. Dropping ``split`` here
    left the release index describing a container that was deleted after splitting,
    so an install could never install that period: the named asset did not exist and
    the sub-parts were never listed. The nested split keeps its own ``part`` order
    and per-part hashes.
    """
    copied = {key: part.get(key) for key in PART_KEYS}
    nested = part.get("split")
    if nested:
        copied["split"] = {
            "schema": nested.get("schema"),
            "mode": nested.get("mode"),
            "dataset_id": nested.get("dataset_id"),
            "snapshot_id": nested.get("snapshot_id"),
            "source": nested.get("source") or {},
            "parts": [{key: sub.get(key) for key in ("part", "name", "bytes", "sha256",
                                                    "offset", "asset_kind")}
                      for sub in nested.get("parts") or []],
        }
    return copied


def _entry_bytes(part: dict) -> int:
    """Downloadable bytes for a part, counting a nested split's sub-parts."""
    nested = part.get("split") or {}
    if nested.get("parts"):
        return sum(int(sub.get("bytes") or 0) for sub in nested["parts"])
    return int(part.get("bytes") or 0)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", default="dist", help="directory of built packages")
    parser.add_argument("--refresh-rights", action="store_true",
                        help="Rewrite only the rights fields of an existing --out index from "
                             "the current registry; package and manifest hashes are unchanged.")
    parser.add_argument("--out", default="data/open_data/releases/index.json")
    parser.add_argument("--release-tag", default=None)
    parser.add_argument("--oversized", action="append", default=[],
                        help="dataset=bytes entries that exceed the asset limit")
    parser.add_argument("--asset-base", default=None,
                        help="URL prefix that assets are published under; per-asset URLs from the "
                             "GitHub API are merged at install time")
    args = parser.parse_args(argv)

    if args.refresh_rights:
        return refresh_rights(Path(args.out))

    assets = []
    for record in sorted(Path(args.packages).glob("*.index.json")):
        payload = json.loads(record.read_text(encoding="utf-8"))
        package = Path(payload["package"])
        if not package.exists():
            package = Path(args.packages) / Path(payload["package"]).name
        item = payload["items"][0] if payload.get("items") else {}
        assets.append({
            "dataset_id": item.get("dataset_id"),
            "snapshot_id": item.get("snapshot_id"),
            "provider": item.get("provider"),
            "rights_class": item.get("rights_class"),
            "license_name": item.get("license_name"),
            "license_url": item.get("license_url"),
            "attribution_required": item.get("attribution_required"),
            "attribution_text": item.get("attribution_text"),
            "manifest_sha256": item.get("manifest_sha256"),
            "raw_bytes": payload.get("raw_bytes"),
            "files": item.get("files") or [],
            "asset": package.name,
            "asset_bytes": package.stat().st_size if package.exists() else payload.get("bytes"),
            "asset_sha256": sha256(package) if package.exists() else payload.get("sha256"),
            "restore": f"atlas data restore {package.name} --expect-sha256 <asset_sha256>",
        })

    # Multipart packages are described by their own index next to the parts. The
    # release index records the part list, per-part hash and mode so an installer
    # can download one period without a second metadata fetch.
    multipart: dict[str, dict] = {}
    for record in sorted(Path(args.packages).glob("*.parts.json")):
        try:
            detail = json.loads(record.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        dataset_id = detail.get("dataset_id")
        if not dataset_id:
            continue
        multipart[dataset_id] = {
            "mode": detail.get("mode"),
            "parts_index": record.name,
            "snapshot_id": detail.get("snapshot_id"),
            "source": {
                "sha256": (detail.get("source") or {}).get("sha256"),
                "bytes": (detail.get("source") or {}).get("bytes"),
            },
            "parts": [_index_part(part) for part in detail.get("parts") or []],
            "periods": detail.get("periods") or [],
        }

    # A dataset distributed only as multipart parts still needs a catalogue entry,
    # otherwise `atlas data install` cannot resolve it at all.
    seen = {asset["dataset_id"] for asset in assets}
    registry = Registry.load()
    for dataset_id, detail in sorted(multipart.items()):
        if dataset_id in seen:
            continue
        dataset = registry.get(dataset_id)
        assets.append({
            "dataset_id": dataset_id,
            "snapshot_id": detail.get("snapshot_id"),
            "provider": dataset.provider,
            "rights_class": dataset.rights_class.value,
            "license_name": dataset.get("license_name"),
            "license_url": dataset.get("license_url"),
            "attribution_required": dataset.get("attribution_required"),
            "attribution_text": dataset.get("attribution_text"),
            "manifest_sha256": None,
            "raw_bytes": (detail.get("source") or {}).get("bytes"),
            "files": [],
            "asset": None,
            "asset_bytes": sum(_entry_bytes(part) for part in detail.get("parts") or []),
            "asset_sha256": (detail.get("source") or {}).get("sha256"),
            "mode": detail.get("mode"),
            "restore": f"atlas data install {dataset_id}",
        })

    oversized = []
    for entry in args.oversized:
        dataset, _, size = entry.partition("=")
        oversized.append({"dataset_id": dataset, "raw_bytes": int(size or 0),
                          "reason": "exceeds the 2 GiB release-asset limit; recover with atlas data sync"})
    payload = {
        "schema": "atlas.open_data.release.v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "release_tag": args.release_tag,
        "policy": (
            "Only snapshots whose stored bytes match a committed manifest and whose registry "
            "entry permits public redistribution are packaged. Third-party exclusions must be "
            "cleared. Local-use, restricted and unverified data is never packaged."
        ),
        "asset_limit_bytes": 2_000_000_000,
        "assets": assets,
        "multipart": multipart,
        "asset_base_url": args.asset_base,
        "asset_count": len(assets),
        "asset_bytes": sum(int(asset.get("asset_bytes") or 0) for asset in assets),
        "oversized": oversized,
        "upload": {
            "status": "not_verified_by_this_run",
            "mechanism": ".github/workflows/open-data-release.yml publishes through a draft release",
            "verification": (
                "Availability is only claimed after the GitHub API returns the asset or after "
                "`atlas data install` downloads and hashes it. A hash in this file is not "
                "evidence that any asset was uploaded."
            ),
        },
        "restore": (
            "atlas data restore <asset> --expect-sha256 <asset_sha256>; the restore verifies the "
            "package hash, the embedded manifest and every file before publishing the snapshot."
        ),
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"index": str(target), "assets": len(assets),
                      "asset_bytes": payload["asset_bytes"], "oversized": len(oversized)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
