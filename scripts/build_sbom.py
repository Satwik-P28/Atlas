#!/usr/bin/env python
"""Write a CycloneDX software bill of materials for the release artifacts.

The SBOM lists what actually ships: the Atlas component, its declared Python dependencies and the
frontend packages compiled into the bundle. Development-only npm packages are excluded because they
are not in the artifact; that choice is stated in the document rather than left implicit.

Usage::

    .venv/bin/python scripts/build_sbom.py --wheel dist/atlas_quant-<version>-py3-none-any.whl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, default=None)
    parser.add_argument("--inventory", type=Path, default=ROOT / "docs" / "DEPENDENCY_LICENSES.json")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "release" / "sbom.cdx.json")
    args = parser.parse_args(argv)

    from atlas import __version__ as version

    inventory = json.loads(args.inventory.read_text())
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                            capture_output=True, text=True).stdout.strip()
    wheel = args.wheel
    if wheel is None:
        candidates = sorted((ROOT / "dist").glob("*.whl"))
        wheel = candidates[-1] if candidates else None

    components: list[dict[str, Any]] = []
    for row in inventory.get("python", []):
        if not row.get("version"):
            continue
        entry: dict[str, Any] = {
            "type": "library",
            "name": row["name"],
            "version": row["version"],
            "purl": f"pkg:pypi/{row['name']}@{row['version']}",
            "scope": "required",
        }
        if row.get("license"):
            entry["licenses"] = [{"license": {"name": row["license"]}}]
        components.append(entry)
    for row in inventory.get("npm_bundled", []):
        if not row.get("version"):
            continue
        entry = {
            "type": "library",
            "name": row["name"],
            "version": row["version"],
            "purl": f"pkg:npm/{row['name'].replace('@', '%40')}@{row['version']}",
            "scope": "required",
            "properties": [{"name": "atlas:bundled_in_frontend", "value": "true"}],
        }
        if row.get("license"):
            entry["licenses"] = [{"license": {"name": row["license"]}}]
        components.append(entry)

    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{hashlib.sha256(commit.encode()).hexdigest()[:8]}-"
                        f"{hashlib.sha256(commit.encode()).hexdigest()[8:12]}-"
                        f"{hashlib.sha256(commit.encode()).hexdigest()[12:16]}-"
                        f"{hashlib.sha256(commit.encode()).hexdigest()[16:20]}-"
                        f"{hashlib.sha256(commit.encode()).hexdigest()[20:32]}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tools": [{"vendor": "Atlas", "name": "scripts/build_sbom.py", "version": "10.5"}],
            "component": {
                "type": "application",
                "name": "atlas_quant",
                "version": inventory.get("commit", "")[:12] or commit[:12],
                "purl": f"pkg:pypi/atlas-quant@{version}",
                "properties": [{"name": "atlas:source_commit", "value": commit}],
            },
        },
        "components": sorted(components, key=lambda item: (item["type"], item["name"])),
        "properties": [
            {"name": "atlas:scope_note",
             "value": "Python runtime dependencies and frontend packages bundled into the wheel; "
                      "development-only npm packages are omitted because they do not ship."},
            {"name": "atlas:licence_note",
             "value": "Licences are as declared by each package; this SBOM grants no rights."},
        ],
    }
    if wheel and wheel.is_file():
        document["metadata"]["component"]["hashes"] = [
            {"alg": "SHA-256", "content": sha256(wheel)},
        ]
        document["metadata"].setdefault("properties", []).append(
            {"name": "atlas:wheel_filename", "value": wheel.name})

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, indent=2) + "\n")
    print(f"sbom: {len(components)} components -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
