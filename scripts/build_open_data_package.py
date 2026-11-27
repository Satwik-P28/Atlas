#!/usr/bin/env python3
"""Build a rights-gated, reproducible distribution archive.

Only datasets whose registry entry permits public distribution are included. The
archive contains the exact raw source bytes, their manifests, the registry and an
attribution file. It never includes local-use, restricted or unverified data.

This script does not upload anything. Publishing is a separate, explicitly authorized
step (see docs/OPEN_DATA_DISTRIBUTION.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data.engine import AcquisitionEngine  # noqa: E402
from atlas.open_data.registry import Registry  # noqa: E402
from atlas.open_data.rights import evaluate  # noqa: E402


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="dist/atlas-open-data.tar.zst")
    parser.add_argument("--dataset", action="append", dest="datasets")
    parser.add_argument("--max-bytes", type=int, default=2_000_000_000)
    parser.add_argument("--level", type=int, default=3, help="zstd compression level")
    parser.add_argument("--index", help="write a per-dataset release index JSON here")
    parser.add_argument("--expect-verified", action="store_true", default=True,
                        help="refuse snapshots whose stored bytes fail verification")
    parser.add_argument("--open-root", default=os.environ.get("ATLAS_OPEN_DATA_ROOT", "var/open_data"))
    parser.add_argument("--open-db", default=os.environ.get("ATLAS_OPEN_DATA_DB", "var/open_data/atlas_open_data.db"))
    args = parser.parse_args(argv)
    try:
        import zstandard as zstd
    except ImportError:
        print("zstandard is required to build the package", file=sys.stderr)
        return 2

    engine = AcquisitionEngine(store_root=args.open_root, index_path=args.open_db)
    try:
        registry = engine.registry
        selected = []
        for snapshot in engine.store.list_snapshots():
            if args.datasets and snapshot.dataset_id not in set(args.datasets):
                continue
            dataset = registry.get(snapshot.dataset_id)
            decision = evaluate(dataset.raw, "publish", public_distribution=True)
            if not decision.allowed:
                print(f"exclude {snapshot.dataset_id}: {decision.reason}", file=sys.stderr)
                continue
            verification = engine.store.verify(snapshot, deep=True)
            if not verification["ok"]:
                print(f"exclude {snapshot.dataset_id}/{snapshot.snapshot_id}: failed verification",
                      file=sys.stderr)
                continue
            selected.append((snapshot, dataset))
        if not selected:
            print("no distributable snapshots matched", file=sys.stderr)
            return 1
        total_raw = sum(sum(int(f["bytes"]) for f in snapshot.files) for snapshot, _ in selected)
        if total_raw > args.max_bytes:
            print(f"selection is {total_raw} bytes, above --max-bytes {args.max_bytes}", file=sys.stderr)
            return 1

        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            catalogue = []
            attributions = []
            for snapshot, dataset in selected:
                target = staging / "datasets" / snapshot.dataset_id / snapshot.snapshot_id
                (target / "files").mkdir(parents=True, exist_ok=True)
                for entry in snapshot.files:
                    source = snapshot.path / "files" / entry["path"]
                    destination = target / "files" / entry["path"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists():
                        continue
                    try:
                        os.link(source, destination)
                    except OSError:
                        import shutil
                        shutil.copy2(source, destination)
                import shutil
                shutil.copy2(snapshot.path / "manifest.json", target / "manifest.json")
                shutil.copy2(snapshot.path / "manifest.sha256", target / "manifest.sha256")
                catalogue.append({
                    "dataset_id": snapshot.dataset_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "provider": dataset.provider,
                    "title": dataset["title"],
                    "source_url": dataset.download_endpoint,
                    "license_name": dataset["license_name"],
                    "license_url": dataset.get("license_url"),
                    "rights_class": dataset.rights_class.value,
                    "rights_decision": {"allowed": decision.allowed, "reason": decision.reason},
                    "attribution_required": dataset["attribution_required"],
                    "attribution_text": dataset["attribution_text"],
                    "third_party_exclusions": dataset["third_party_exclusions"],
                    "files": snapshot.files,
                    "manifest_sha256": snapshot.manifest_sha256,
                })
                if dataset["attribution_required"]:
                    attributions.append(f"- {dataset['title']} ({dataset.provider}): {dataset['attribution_text']}")
            package_manifest = {
                "package_version": 2,
                "generated_at": utcnow(),
                "registry_reviewed_at": registry.payload.get("reviewed_at"),
                "policy": "Only public_domain, permissive and redistributable_conditions datasets "
                          "with redistribution, commercial use, a current review and cleared exclusions.",
                "datasets": catalogue,
                "raw_bytes": total_raw,
                "attribution": attributions,
            }
            (staging / "PACKAGE_MANIFEST.json").write_text(
                json.dumps(package_manifest, indent=2) + "\n", encoding="utf-8")
            # The licence and attribution travel *inside* the archive. A package
            # whose rights were only corrected in the external index would still
            # distribute the superseded terms to everyone who downloads it.
            licences = {
                "schema": "atlas.open_data.package_licences.v1",
                "generated_at": package_manifest["generated_at"],
                "registry_reviewed_at": package_manifest["registry_reviewed_at"],
                "datasets": [{
                    "dataset_id": item["dataset_id"],
                    "title": item["title"],
                    "provider": item["provider"],
                    "source_url": item["source_url"],
                    "license_name": item["license_name"],
                    "license_url": item["license_url"],
                    "rights_class": item["rights_class"],
                    "rights_decision": item["rights_decision"],
                    "attribution_required": item["attribution_required"],
                    "attribution_text": item["attribution_text"],
                    "third_party_exclusions": item["third_party_exclusions"],
                } for item in catalogue],
            }
            (staging / "LICENSES.json").write_text(
                json.dumps(licences, indent=2) + "\n", encoding="utf-8")
            licence_lines = ["# Licences and attribution", "",
                             f"Registry review: {package_manifest['registry_reviewed_at']}", ""]
            for item in catalogue:
                licence_lines += [
                    f"## {item['title']} (`{item['dataset_id']}`)", "",
                    f"- Provider: {item['provider']}",
                    f"- Licence: {item['license_name']}",
                    f"- Licence URL: {item['license_url'] or '(not recorded)'}",
                    f"- Rights class: {item['rights_class']}",
                    f"- Publication decision: {item['rights_decision']['reason']}",
                    f"- Attribution required: {'yes' if item['attribution_required'] else 'no'}",
                ]
                if item["attribution_required"]:
                    licence_lines.append(f"- Attribution: {item['attribution_text']}")
                if item["third_party_exclusions"]:
                    licence_lines.append(
                        "- Third-party exclusions: " + "; ".join(
                            str(entry) for entry in item["third_party_exclusions"]))
                licence_lines.append("")
            (staging / "LICENSES.md").write_text("\n".join(licence_lines), encoding="utf-8")
            (staging / "ATTRIBUTION.md").write_text(
                "# Attribution\n\n" + ("\n".join(attributions) or "No attribution is required by the included licences.")
                + "\n", encoding="utf-8")
            import shutil
            shutil.copy2(ROOT / "data/open_data/registry.json", staging / "registry.json")

            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with out.open("wb") as raw_out:
                with zstd.ZstdCompressor(level=args.level, threads=2).stream_writer(raw_out) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w|") as archive:
                        for path in sorted(staging.rglob("*")):
                            if path.is_file():
                                archive.add(path, arcname=path.relative_to(staging).as_posix())
            with out.open("rb") as stream:
                while chunk := stream.read(4 << 20):
                    digest.update(chunk)
            sidecar = out.with_suffix(out.suffix + ".sha256")
            sidecar.write_text(f"{digest.hexdigest()}  {out.name}\n", encoding="utf-8")
            summary = {
                "package": str(out), "bytes": out.stat().st_size, "raw_bytes": total_raw,
                "datasets": len(catalogue), "sha256": digest.hexdigest(),
                "manifest": "PACKAGE_MANIFEST.json", "uploaded": False,
                "items": [{
                    "dataset_id": item["dataset_id"], "snapshot_id": item["snapshot_id"],
                    "provider": item["provider"], "license_name": item["license_name"],
                    "license_url": item["license_url"], "rights_class": item["rights_class"],
                    "attribution_required": item["attribution_required"],
                    "attribution_text": item["attribution_text"],
                    "rights_decision": item["rights_decision"],
                    "license_embedded": "LICENSES.md",
                    "manifest_sha256": item["manifest_sha256"],
                    "raw_bytes": sum(int(f["bytes"]) for f in item["files"]),
                    "files": [{"path": f["path"], "bytes": f["bytes"], "sha256": f["sha256"]}
                              for f in item["files"]],
                } for item in catalogue],
            }
            if args.index:
                index_path = Path(args.index)
                index_path.parent.mkdir(parents=True, exist_ok=True)
                index_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8")
            print(json.dumps(summary, indent=2))
            return 0
    finally:
        engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
