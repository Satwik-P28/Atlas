#!/usr/bin/env python
"""Create a reproducible release manifest and a conservative CycloneDX-style SBOM.

Only tracked or explicitly non-ignored project files are hashed. Generated databases,
virtual environments, browser fixtures and secrets are excluded by Git ignore rules.
No claim of a signed release is made: the manifest records hashes and the current revision.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "artifacts"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT
    )
    paths = []
    for item in raw.split(b"\0"):
        if not item:
            continue
        relative = item.decode("utf-8")
        if relative.startswith("artifacts/"):
            continue
        path = ROOT / relative
        if path.is_file():
            paths.append((relative, path))
    files = [{"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size}
             for relative, path in sorted(paths)]
    dirty = bool(command("git", "status", "--porcelain"))
    revision = command("git", "rev-parse", "HEAD")
    manifest = {
        "schema": "atlas.release_manifest.v1",
        "project": "atlas-quant",
        "revision": revision,
        "dirty_worktree": dirty,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "files": files,
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "phase8_package": "fixtures/phase8/flagship_weather_demand.atlas" if (
            ROOT / "fixtures/phase8/flagship_weather_demand.atlas").exists() else None,
        "signature": None,
        "note": "Hashes establish byte identity, not publisher identity or a signed release.",
    }
    components = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name")
        version = distribution.version
        if name and version:
            components.append({"type": "library", "name": name, "version": version})
    components.sort(key=lambda item: (item["name"].lower(), item["version"]))
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:atlas:sha256:{hashlib.sha256(revision.encode()).hexdigest()[:32]}",
        "version": 1,
        "metadata": {
            "component": {"type": "application", "name": "atlas-quant"},
            "properties": [
                {"name": "atlas:revision", "value": revision},
                {"name": "atlas:dirty_worktree", "value": str(dirty).lower()},
                {"name": "atlas:phase8_package", "value": manifest["phase8_package"] or "absent"},
            ],
        },
        "components": components,
    }
    (out / "release_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "sbom.cdx.json").write_text(
        json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"manifest": str(out / "release_manifest.json"),
                      "sbom": str(out / "sbom.cdx.json"),
                      "files": len(files), "components": len(components),
                      "revision": revision, "dirty": dirty}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
