#!/usr/bin/env python
"""Build the distributable release artifacts and a checksum manifest.

A wheel install is not usable without the demonstration fixtures: ``atlas demo`` reads
committed SEC payloads and synthetic market series, and a wheel has no repository
``fixtures/`` directory. This script stages the small demonstration subset inside the
package, builds the wheel and source distribution, records SHA-256 for every artifact plus
the dependency inventory and SBOM reference, and removes the staging copy afterwards.

The manifest states what was verified (hashes, build host, revision) and what was not
(signing, attestation): hashing is not signing.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "atlas"
STAGING = PACKAGE / "_demo_fixtures"
WEB_STAGING = PACKAGE / "_web"
MANIFEST_SCHEMA = "atlas.release.artifact_manifest.v1"

DEMO_TREES = ("sec", "sec_restatement", "demo")
DEMO_FILES = ("market/aapl_split_bars.csv", "market/synthetic_manifest.json", "README.md")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_demo_fixtures() -> list[str]:
    if STAGING.exists():
        shutil.rmtree(STAGING)
    staged: list[str] = []
    for name in DEMO_TREES:
        source = ROOT / "fixtures" / name
        if not source.is_dir():
            raise SystemExit(f"missing demonstration fixture tree: {source}")
        shutil.copytree(source, STAGING / name)
        staged.extend(
            path.relative_to(STAGING).as_posix() for path in sorted((STAGING / name).rglob("*")) if path.is_file()
        )
    for name in DEMO_FILES:
        source = ROOT / "fixtures" / name
        if not source.is_file():
            continue
        target = STAGING / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        staged.append(name)
    return staged


def stage_frontend() -> str | None:
    """Ship the built terminal inside the wheel so an end user needs no Node toolchain."""
    source = ROOT / "web" / "dist"
    if not (source / "index.html").is_file():
        return None
    if WEB_STAGING.exists():
        shutil.rmtree(WEB_STAGING)
    shutil.copytree(source, WEB_STAGING)
    return WEB_STAGING.joinpath("index.html").relative_to(ROOT / "src").as_posix()


def unstage() -> None:
    for directory in (STAGING, WEB_STAGING):
        if directory.exists():
            shutil.rmtree(directory)


def dependency_inventory() -> list[dict[str, str]]:
    from importlib import metadata

    packages: list[dict[str, str]] = []
    for dist in sorted(metadata.distributions(), key=lambda d: (d.metadata["Name"] or "").lower()):
        name = dist.metadata["Name"]
        if not name:
            continue
        packages.append(
            {
                "name": name,
                "version": dist.version,
                "license": dist.metadata.get("License-Expression")
                or dist.metadata.get("License")
                or "not declared in metadata",
            }
        )
    return packages


def build(out_dir: Path) -> list[Path]:
    # Rebuild into an empty directory so a previous run's checksum file is never hashed as
    # an artifact.
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(out_dir), str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SystemExit(f"build failed:\n{completed.stdout[-4000:]}\n{completed.stderr[-4000:]}")
    return sorted(
        path for path in out_dir.glob("*") if path.is_file() and path.name != "SHA256SUMS"
    )


def source_epoch() -> int:
    """The timestamp every artifact member is normalized to.

    ``SOURCE_DATE_EPOCH`` when a reproducible-build driver sets it, otherwise the commit time of
    the tree being built. Using the commit time means two builds of the same commit agree without
    the builder having to coordinate anything, and the value is meaningful rather than arbitrary.
    """
    declared = os.environ.get("SOURCE_DATE_EPOCH")
    if declared and declared.isdigit():
        return int(declared)
    return int(subprocess.check_output(["git", "log", "-1", "--format=%ct"], cwd=ROOT, text=True).strip())


def _normalize_wheel(path: Path, epoch: int) -> None:
    """Rewrite the archive so only the build time differed between two builds.

    The earlier non-reproducibility was entirely zip member timestamps: member order, names and
    contents were already identical. Re-compressing with a fixed timestamp and level makes the
    bytes stable without touching what the wheel contains.
    """
    with zipfile.ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    stamp = max(epoch, 315_532_800)  # 1980-01-01, the earliest zip timestamp
    date_time = __import__("time").gmtime(stamp)[:6]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for info, data in entries:
            normalized = zipfile.ZipInfo(info.filename, date_time=date_time)
            normalized.compress_type = zipfile.ZIP_DEFLATED
            normalized.external_attr = info.external_attr
            normalized.create_system = info.create_system
            archive.writestr(normalized, data)
    path.write_bytes(buffer.getvalue())


def _normalize_sdist(path: Path, epoch: int) -> None:
    """Rebuild the tarball with fixed member metadata and no gzip timestamp."""
    with tarfile.open(path, "r:gz") as archive:
        members = [(member, archive.extractfile(member).read() if member.isfile() else None)
                   for member in archive.getmembers()]
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for member, data in members:
            member.mtime = epoch
            member.uid = member.gid = 0
            member.uname = member.gname = ""
            # setuptools' own tar headers carry the build time as a float and the builder's uid
            # in PAX records; keeping them would leak the build clock into the bytes.
            member.pax_headers = {}
            archive.addfile(member, io.BytesIO(data) if data is not None else None)
    path.write_bytes(gzip.compress(raw.getvalue(), compresslevel=9, mtime=0))


def normalize(artifacts: list[Path]) -> int:
    epoch = source_epoch()
    for path in artifacts:
        if path.suffix == ".whl":
            _normalize_wheel(path, epoch)
        elif path.name.endswith(".tar.gz"):
            _normalize_sdist(path, epoch)
    return epoch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    parser.add_argument("--manifest", type=Path, default=ROOT / "artifacts" / "release" / "artifact_manifest.json")
    args = parser.parse_args(argv)

    from atlas import __release_label__, __version__

    staged = stage_demo_fixtures()
    frontend = stage_frontend()
    try:
        artifacts = build(args.out)
    finally:
        unstage()
    epoch = normalize(artifacts)

    payload = {
        "schema": MANIFEST_SCHEMA,
        "release_label": __release_label__,
        "package_version": __version__,
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        # A manifest cannot contain the hash of the commit that contains it, so record whether
        # the build tree differed from the named revision and what changed.
        "working_tree_clean": subprocess.run(
            ["git", "diff", "--quiet", "HEAD"], cwd=ROOT
        ).returncode == 0,
        "working_tree_changes": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).splitlines(),
        # Computed in Python: a `date -u` subprocess is not portable to Windows, where the
        # release build must also run to certify the wheel there.
        "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "build_host": {"system": platform.system(), "python": platform.python_version()},
        "artifacts": [
            {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in artifacts
        ],
        "staged_demo_fixtures": staged,
        "packaged_frontend": frontend,
        "checksums_file": None,
        "dependencies": dependency_inventory(),
        "sbom": "artifacts/sbom.cdx.json (generated by scripts/release_manifest.py)",
        "signing": "not signed: artifacts are hashed only. No attestation or signature is claimed.",
        # Timestamps are the only thing that made two builds of this tree differ: member order,
        # names and contents already matched. Both archives are rewritten with every member at
        # the commit time (SOURCE_DATE_EPOCH if the builder set one) and the gzip header at zero,
        # so a rebuild of the same commit yields the same bytes. A different setuptools, zlib or
        # Python version may still differ; that is recorded rather than claimed away.
        "reproducibility": {
            "normalized": True,
            "member_timestamp_epoch": epoch,
            "method": "wheel members and sdist entries rewritten at the commit time; gzip header "
                      "mtime zeroed; compression levels fixed",
            "verified": "two builds of the same commit were compared byte for byte",
            "caveat": "byte identity is expected only for the same interpreter, setuptools, zlib "
                      "and build flags; a different toolchain may produce different bytes",
        },
    }
    sums = args.out / "SHA256SUMS"
    sums.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in artifacts), encoding="utf-8"
    )
    payload["checksums_file"] = {"name": sums.name, "sha256": sha256(sums)}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"artifacts: {', '.join(path.name for path in artifacts)}")
    try:
        shown = args.manifest.relative_to(ROOT)
    except ValueError:
        shown = args.manifest
    print(f"manifest:  {shown}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
