#!/usr/bin/env python3
"""One reviewed entry point for each step of the release workflow.

The workflow calls this script with a validated plan. Keeping the steps here
rather than inline in YAML means they are the same code that can be run and
tested locally, and no step needs a workflow input interpolated into a shell.

Subcommands
-----------
acquire       acquire the plan's datasets through the normal rights-aware CLI
index         write the committable release index and the release notes
check-assets  reject oversized, unsafe or missing assets before upload
draft         refuse an existing tag, then create a draft release
publish       flip an existing draft to public
verify        read the release back through the GitHub API and record the outcome
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data.release import (  # noqa: E402
    ReleaseInputError, fetch_github_release, published_assets, read_release_index,
    validate_filenames, write_publication_record,
)

ASSET_SUFFIXES = (".tar.zst", ".sha256", ".parts.json", ".index.json")


def _plan(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _dataset_ids(plan: dict) -> list[str]:
    return [item["dataset_id"] for item in plan["datasets"]]


# ------------------------------------------------------------------------- acquire
def acquire(plan_path: str, out_path: str) -> int:
    plan = _plan(plan_path)
    ids = _dataset_ids(plan)
    result = subprocess.run(
        [sys.executable, "-m", "atlas.cli", "data", "sync", *ids, "--automated"],
        check=False,
    )
    payload = {"datasets": ids, "exit": result.returncode,
               "tag": plan["release_tag"]}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return result.returncode


# --------------------------------------------------------------------------- index
def index(plan_path: str, out_path: str, packages: str = "dist") -> int:
    import importlib.util

    plan = _plan(plan_path)
    spec = importlib.util.spec_from_file_location(
        "index_open_data_release", ROOT / "scripts/index_open_data_release.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    argv = ["--packages", packages, "--out", out_path,
            "--release-tag", plan["release_tag"]]
    for item in plan.get("oversized") or []:
        argv += ["--oversized", f"{item['dataset_id']}={item['raw_bytes']}"]
    code = module.main(argv)
    if code != 0:
        return code
    payload = read_release_index(out_path)
    notes = ["# Atlas open data " + plan["release_tag"], "",
             "Every asset in this release was built from bytes that match a committed "
             "SHA-256 manifest and whose registry entry permits public redistribution.", "",
             "| Dataset | Rights class | Licence | Asset | Bytes |", "| --- | --- | --- | --- | --- |"]
    for asset in payload.get("assets") or []:
        notes.append(
            f"| `{asset.get('dataset_id')}` | {asset.get('rights_class')} | "
            f"{asset.get('license_name')} | {asset.get('asset') or '(multipart)'} | "
            f"{asset.get('asset_bytes') or 0} |")
    notes += ["", "## Restore", "",
              "```bash",
              f"atlas data install {' '.join(_dataset_ids(plan))} --index data/open_data/releases/index.json",
              "```", "",
              "Each install downloads only what is missing, verifies every asset's SHA-256 "
              "before use and never replaces an existing snapshot. Licence and attribution "
              "terms are embedded inside each package (`LICENSES.md`, `LICENSES.json`).", ""]
    Path(out_path).with_name("RELEASE_NOTES.md").write_text("\n".join(notes), encoding="utf-8")
    return 0


# -------------------------------------------------------------------- check assets
def check_assets(dist: str, limit: int, plan_path: str | None = None) -> int:
    directory = Path(dist)
    problems: list[str] = []
    assets: list[dict] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.name in {"release-plan.json", "RELEASE_NOTES.md"}:
            continue
        if not (path.name.endswith(ASSET_SUFFIXES) or path.name == "release-index.json"):
            continue
        size = path.stat().st_size
        assets.append({"asset": path.name, "bytes": size})
        if size > limit:
            problems.append(f"{path.name} is {size} bytes, above the {limit} byte limit")
    if not assets:
        problems.append("no release assets were built")
    ids = [item["dataset_id"] for item in _plan(plan_path)["datasets"]] if plan_path else []
    try:
        validate_filenames([item["asset"] for item in assets], allowed_dataset_ids=ids)
    except ReleaseInputError as exc:
        problems.append(str(exc))
    for item in assets:
        if item["asset"].endswith(".tar.zst"):
            sidecar = directory / (item["asset"] + ".sha256")
            if not sidecar.exists():
                problems.append(f"{item['asset']} has no .sha256 sidecar")
        if item["asset"].endswith(".tar.zst.sha256"):
            declared = (directory / item["asset"]).read_text(encoding="utf-8").split()
            target = directory / item["asset"].removesuffix(".sha256")
            import hashlib
            digest = hashlib.sha256()
            with target.open("rb") as stream:
                while chunk := stream.read(4 << 20):
                    digest.update(chunk)
            if not declared or declared[0] != digest.hexdigest():
                problems.append(f"{target.name} does not match its sidecar")
    result = {"assets": assets, "count": len(assets),
              "bytes": sum(item["bytes"] for item in assets),
              "largest": max((item["bytes"] for item in assets), default=0),
              "problems": problems}
    print(json.dumps(result, indent=2))
    return 1 if problems else 0


# ------------------------------------------------------------------ draft / publish
def _release_assets(directory: Path) -> list[str]:
    files: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.is_file() and (path.name.endswith(ASSET_SUFFIXES)
                               or path.name in {"release-index.json", "RELEASE_NOTES.md"}):
            files.append(str(path))
    return files


def _tag_exists(tag: str) -> bool:
    result = subprocess.run(["gh", "release", "view", tag],
                            capture_output=True, text=True, check=False)
    return result.returncode == 0


def draft(plan_path: str, dist: str) -> int:
    plan = _plan(plan_path)
    tag = plan["release_tag"]
    directory = Path(dist)
    if _tag_exists(tag):
        print(f"release {tag} already exists; publish a new -rN tag instead", file=sys.stderr)
        write_publication_record({"status": "refused_existing_tag", "tag": tag})
        return 1
    files = _release_assets(directory)
    if not files:
        print("no assets to publish", file=sys.stderr)
        return 1
    notes = directory / "RELEASE_NOTES.md"
    command = ["gh", "release", "create", tag, "--draft",
               "--title", f"Atlas open data {tag}"]
    if notes.exists():
        command += ["--notes-file", str(notes)]
    command += files
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        write_publication_record({"status": "draft_failed", "tag": tag,
                                  "error": result.stderr.strip(),
                                  "assets": [Path(item).name for item in files]})
        return result.returncode
    write_publication_record({"status": "draft_created", "tag": tag,
                              "assets": [Path(item).name for item in files]})
    return 0


def publish(plan_path: str) -> int:
    plan = _plan(plan_path)
    tag = plan["release_tag"]
    result = subprocess.run(["gh", "release", "edit", tag, "--draft=false"],
                            capture_output=True, text=True, check=False)
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        write_publication_record({"status": "publish_failed", "tag": tag,
                                  "error": result.stderr.strip()})
    return result.returncode


# -------------------------------------------------------------------------- verify
def _metadata_reconciliation(index: Mapping, release: Mapping, index_path: str) -> dict:
    """API-level reconciliation: names, sizes and any digest the API supplies."""
    from atlas.open_data.verification import expected_assets

    assets = published_assets(release)
    by_name = {str(item.get("asset")): item for item in assets}
    expected = expected_assets(index, index_path=index_path)
    problems: list[str] = []
    for entry in expected:
        name = entry["asset"]
        uploaded = by_name.get(name)
        if uploaded is None:
            problems.append(f"{name} is not in the published release")
            continue
        if entry.get("bytes") is not None and uploaded.get("bytes") != entry["bytes"]:
            problems.append(f"{name} is {uploaded.get('bytes')} bytes, index says {entry['bytes']}")
        if uploaded.get("sha256") and entry.get("sha256") \
                and uploaded["sha256"] != entry["sha256"]:
            problems.append(f"{name} digest {uploaded['sha256']} != index {entry['sha256']}")
    unexpected = sorted(set(by_name) - {entry["asset"] for entry in expected})
    if unexpected:
        problems.append(f"assets in the release are not described by the index: {unexpected}")
    return {"assets": assets, "expected": expected, "problems": problems,
            "unexpected": unexpected}


def verify(index_path: str, repo: str | None = None, *, download_dir: str | None = None,
           fresh_store: str | None = None, metadata_only: bool = False,
           require_byte_verification: bool = False) -> int:
    """Verify a published release, by metadata and (by default) by bytes.

    ``metadata_only`` is recorded explicitly rather than being passed off as
    verification. ``require_byte_verification`` fails the step when any expected asset
    could not be downloaded, hashed and restored, which is what publication claims.
    """
    index = read_release_index(index_path)
    tag = index.get("release_tag")
    repo = repo or os.environ.get("GITHUB_REPOSITORY")
    if not tag or not repo:
        print("an index tag and a repository are required", file=sys.stderr)
        return 2
    record: dict = {"tag": tag, "repository": repo}
    try:
        release = fetch_github_release(repo, tag, token=os.environ.get("GH_TOKEN"))
    except Exception as exc:  # noqa: BLE001 - recorded as the publication outcome
        record.update({"status": "failed", "error": str(exc)})
        write_publication_record(record)
        print(json.dumps(record, indent=2), file=sys.stderr)
        return 1

    metadata = _metadata_reconciliation(index, release, index_path)
    problems: list[str] = list(metadata["problems"])
    verification: dict | None = None
    if not metadata_only:
        import tempfile

        from atlas.open_data.verification import verify_release

        directory = download_dir or tempfile.mkdtemp(prefix="atlas-release-verify-")
        try:
            verification = verify_release(
                repo=repo, tag=tag, index_path=index_path, download_dir=directory,
                fresh_store=fresh_store, token=os.environ.get("GH_TOKEN"), release=release,
            )
            problems.extend(verification["problems"])
        except Exception as exc:  # noqa: BLE001 - a failed verification is an outcome
            problems.append(f"byte verification failed: {type(exc).__name__}: {exc}")

    byte_verified = verification["byte_verified_count"] if verification else 0
    metadata_only_assets = verification["metadata_only_count"] if verification else len(
        metadata["expected"])
    failed_assets = verification["failed_count"] if verification else 0
    if require_byte_verification:
        if verification is None:
            problems.append("byte verification was required but not performed")
        elif byte_verified != verification["expected_assets"]:
            problems.append(
                f"byte verification covered {byte_verified} of "
                f"{verification['expected_assets']} expected assets")

    if problems:
        status = "mismatch"
    elif verification is not None and verification["ok"]:
        status = "draft_byte_verified" if release.get("draft") else "published_byte_verified"
    elif metadata_only:
        status = "draft_metadata_only" if release.get("draft") else "published_metadata_only"
    else:
        status = "draft" if release.get("draft") else "published_metadata_only"

    record.update({
        "status": status,
        "html_url": release.get("html_url"),
        "draft": bool(release.get("draft")),
        "expected_assets": len(metadata["expected"]),
        "published_assets": len(metadata["assets"]),
        "assets": metadata["assets"],
        "problems": problems,
        "verification": {
            "metadata_only": bool(metadata_only or verification is None),
            "byte_verified": byte_verified,
            "metadata_verified_only": metadata_only_assets,
            "failed": failed_assets,
            "download_dir": (verification or {}).get("download_dir"),
            "assets": (verification or {}).get("assets") or [],
            "restoration": (verification or {}).get("restoration") or {},
        },
    })
    write_publication_record(record)
    print(json.dumps(record, indent=2))
    return 1 if problems else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    acq = sub.add_parser("acquire")
    acq.add_argument("--plan", default="dist/release-plan.json")
    acq.add_argument("--out", default="/tmp/acquire.json")
    idx = sub.add_parser("index")
    idx.add_argument("--plan", default="dist/release-plan.json")
    idx.add_argument("--out", default="dist/release-index.json")
    idx.add_argument("--packages", default="dist")
    chk = sub.add_parser("check-assets")
    chk.add_argument("--dist", default="dist")
    chk.add_argument("--limit", type=int, default=1_900_000_000)
    chk.add_argument("--plan", default="dist/release-plan.json")
    drf = sub.add_parser("draft")
    drf.add_argument("--plan", default="dist/release-plan.json")
    drf.add_argument("--dist", default="dist")
    pub = sub.add_parser("publish")
    pub.add_argument("--plan", default="dist/release-plan.json")
    ver = sub.add_parser("verify")
    ver.add_argument("--index", default="dist/release-index.json")
    ver.add_argument("--repo")
    ver.add_argument("--download-dir", help="where assets are downloaded for hashing")
    ver.add_argument("--fresh-store", help="empty store the packages are restored into")
    ver.add_argument("--metadata-only", action="store_true",
                     help="read the API only; recorded as metadata_verified, never as verified")
    ver.add_argument("--require-byte-verification", action="store_true",
                     help="fail unless every expected asset was downloaded, hashed and restored")
    args = parser.parse_args(argv)
    if args.command == "acquire":
        return acquire(args.plan, args.out)
    if args.command == "index":
        return index(args.plan, args.out, args.packages)
    if args.command == "check-assets":
        return check_assets(args.dist, args.limit, args.plan)
    if args.command == "draft":
        return draft(args.plan, args.dist)
    if args.command == "publish":
        return publish(args.plan)
    return verify(args.index, args.repo, download_dir=args.download_dir,
                  fresh_store=args.fresh_store, metadata_only=args.metadata_only,
                  require_byte_verification=args.require_byte_verification)


if __name__ == "__main__":
    raise SystemExit(main())
