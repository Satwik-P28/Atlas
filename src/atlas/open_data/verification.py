"""Independent byte-level verification of a published open-data release.

The GitHub API proves that an asset exists with a given name and byte count. It does
not prove that the bytes on the download path are the bytes that were packaged. This
module therefore re-downloads every expected asset over HTTPS, hashes it, compares it
with the committed release index and the API's own digest, reassembles multipart
datasets and restores every package into a *fresh* store.

Three outcomes are kept distinct on purpose:

``metadata_verified``
    The API listed the asset with the expected name and size. Nothing was downloaded.
``byte_verified``
    The bytes were streamed, hashed and matched the expected SHA-256 and size.
``failed``
    Missing, extra, oversized, truncated or corrupt.

A publication is only reported as verified when every expected asset is
``byte_verified`` and the fresh restore succeeds.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import multipart
from .durable import restore_package
from .release import fetch_github_release, published_assets
from .store import SnapshotStore, sha256_file

CHUNK = 4 << 20
METADATA_VERIFIED = "metadata_verified"
BYTE_VERIFIED = "byte_verified"
FAILED = "failed"


class _RedirectWithoutAuthorization(urllib.request.HTTPRedirectHandler):
    """Follow GitHub's redirect to its object store without leaking the token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        forwarded = super().redirect_request(req, fp, code, msg, headers, newurl)
        if forwarded is not None:
            if urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
                forwarded.remove_header("Authorization")
        return forwarded


def _download(url: str, destination: Path, *, token: str | None = None,
              timeout: float = 120.0) -> dict[str, Any]:
    """Stream one asset to disk, hashing exactly the bytes received."""
    headers = {"User-Agent": "Atlas-Data-Engine/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/octet-stream"
    request = urllib.request.Request(url, headers=headers)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    written = 0
    opener = urllib.request.build_opener(_RedirectWithoutAuthorization)
    try:
        with opener.open(request, timeout=timeout) as response:
            with partial.open("wb") as sink:
                while chunk := response.read(CHUNK):
                    sink.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
        partial.replace(destination)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    return {"path": str(destination), "bytes": written, "sha256": digest.hexdigest(),
            "url": url}


def expected_assets(index: Mapping[str, Any], *, index_path: str | Path | None = None,
                    notes_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Every asset the release must contain, from the committed index.

    Multipart datasets contribute their parts, not the dataset entry. A nested split
    contributes its sub-parts, because the container itself is never uploaded.
    """
    rows: list[dict[str, Any]] = []
    for asset in index.get("assets") or []:
        dataset_id = str(asset.get("dataset_id"))
        name = asset.get("asset")
        if name:
            rows.append({
                "asset": str(name),
                "bytes": asset.get("asset_bytes"),
                "sha256": asset.get("asset_sha256"),
                "dataset_id": dataset_id,
                "kind": "package",
                "period": None,
                "container": None,
            })
            continue
        detail = (index.get("multipart") or {}).get(dataset_id) or {}
        for part in detail.get("parts") or []:
            nested = part.get("split") or {}
            members = nested.get("parts") or [part]
            for member in members:
                rows.append({
                    "asset": str(member.get("name")),
                    "bytes": member.get("bytes"),
                    "sha256": member.get("sha256"),
                    "dataset_id": dataset_id,
                    "kind": detail.get("mode"),
                    "period": part.get("period"),
                    "container": part.get("name") if nested else None,
                })
    for path, kind in ((index_path, "index"), (notes_path, "notes")):
        if path is None:
            continue
        candidate = Path(path)
        if candidate.exists():
            rows.append({
                "asset": candidate.name,
                "bytes": candidate.stat().st_size,
                "sha256": sha256_file(candidate),
                "dataset_id": None,
                "kind": kind,
                "period": None,
                "container": None,
            })
    return rows


def _asset_urls(entry: Mapping[str, Any], api: Mapping[str, Any] | None,
                index: Mapping[str, Any]) -> list[str]:
    """Download candidates in order: API asset endpoint, then the browser URL.

    Draft release assets are only reachable through the authenticated API endpoint,
    so that URL is tried first whenever a token is available.
    """
    urls: list[str] = []
    if api:
        if api.get("api_url"):
            urls.append(str(api["api_url"]))
        if api.get("url"):
            urls.append(str(api["url"]))
    if entry.get("url"):
        urls.append(str(entry["url"]))
    base = index.get("asset_base_url")
    if base:
        urls.append(f"{str(base).rstrip('/')}/{entry['asset']}")
    seen: list[str] = []
    for url in urls:
        if url not in seen:
            seen.append(url)
    return seen


def _restore_packages(index: Mapping[str, Any], download_dir: Path,
                      fresh_store: Path) -> dict[str, Any]:
    """Restore every package into an empty store, then restore it again."""
    store = SnapshotStore(fresh_store)
    results: list[dict[str, Any]] = []
    problems: list[str] = []
    for asset in index.get("assets") or []:
        name = asset.get("asset")
        if not name:
            continue
        package = download_dir / str(name)
        if not package.exists():
            problems.append(f"{name} was not downloaded, so it cannot be restored")
            continue
        try:
            first = restore_package(store, package, expected_sha256=asset.get("asset_sha256"))
            items = list(first.get("items") or [])
            verified_all = True
            for item in items:
                snapshot = store.snapshot_path(item["dataset_id"], item["snapshot_id"])
                report = store.verify(snapshot, deep=True)
                verified_all = verified_all and bool(report.get("ok"))
                if not report.get("ok"):
                    problems.append(
                        f"{name} restored {item['snapshot_id']} but it failed verification: "
                        f"{report.get('errors')}")
            if asset.get("snapshot_id") and items \
                    and all(item["snapshot_id"] != asset["snapshot_id"] for item in items):
                problems.append(
                    f"{name} restored {[item['snapshot_id'] for item in items]}, "
                    f"index says {asset['snapshot_id']}")
            second = restore_package(store, package, expected_sha256=asset.get("asset_sha256"))
            second_items = list(second.get("items") or [])
            idempotent = bool(second_items) and all(
                item.get("status") == "already_present" for item in second_items)
            if not idempotent:
                problems.append(f"{name} was restored twice but the second restore was not idempotent")
            results.append({
                "asset": name,
                "dataset_id": asset.get("dataset_id"),
                "snapshots": [{"dataset_id": item["dataset_id"],
                               "snapshot_id": item["snapshot_id"],
                               "status": item["status"]} for item in items],
                "restored": int(first.get("restored") or 0),
                "snapshot_verified": verified_all,
                "idempotent": idempotent,
            })
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            problems.append(f"{name} could not be restored: {type(exc).__name__}: {exc}")
            results.append({"asset": name, "error": str(exc)})
    return {"store": str(fresh_store), "packages": results, "problems": problems}


def _reconstruct_multipart(index: Mapping[str, Any], download_dir: Path,
                           workdir: Path) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    problems: list[str] = []
    for dataset_id, detail in (index.get("multipart") or {}).items():
        payload = {
            "schema": "atlas.open_data.multipart.v1",
            "mode": detail.get("mode"),
            "dataset_id": dataset_id,
            "snapshot_id": detail.get("snapshot_id"),
            "source": detail.get("source") or {},
            "parts": detail.get("parts") or [],
        }
        try:
            if detail.get("mode") == "bytes":
                destination = workdir / f"{dataset_id}.zip"
                outcome = multipart.reconstruct(payload, download_dir, destination)
                source_sha = str((detail.get("source") or {}).get("sha256") or "")
                if source_sha and outcome.get("sha256") != source_sha:
                    problems.append(f"{dataset_id} reconstructed {outcome.get('sha256')} != {source_sha}")
                results.append({"dataset_id": dataset_id, "mode": "bytes", **outcome})
            else:
                outcome = multipart.restore_periods(
                    payload, download_dir, workdir / dataset_id)
                results.append({"dataset_id": dataset_id, "mode": "period",
                                "periods": outcome.get("periods"),
                                "files_installed": outcome.get("files_installed"),
                                "output": outcome.get("output")})
        except Exception as exc:  # noqa: BLE001 - reported
            problems.append(f"{dataset_id} could not be reconstructed: {type(exc).__name__}: {exc}")
            results.append({"dataset_id": dataset_id, "error": str(exc)})
    return {"datasets": results, "problems": problems}


def verify_release(
    *,
    repo: str,
    tag: str,
    index_path: str | Path,
    download_dir: str | Path,
    fresh_store: str | Path | None = None,
    token: str | None = None,
    release: Mapping[str, Any] | None = None,
    timeout: float = 120.0,
    restore: bool = True,
) -> dict[str, Any]:
    """Download, hash, reconcile and restore a published release.

    ``release`` may be supplied when the caller has just read the API, so a draft
    release is verified from the same API response that identified it.
    """
    index_file = Path(index_path)
    index = json.loads(index_file.read_text(encoding="utf-8"))
    if release is None:
        release = fetch_github_release(repo, tag, token=token)
    api_assets = published_assets(release)
    by_name = {str(item.get("asset")): item for item in api_assets}
    expected = expected_assets(index, index_path=index_file,
                               notes_path=index_file.with_name("RELEASE_NOTES.md"))
    expected_names = {item["asset"] for item in expected}
    published_names = set(by_name)
    missing = sorted(expected_names - published_names)
    unexpected = sorted(published_names - expected_names)
    problems: list[str] = []
    if missing:
        problems.append(f"assets in the index are not in the release: {missing}")
    if unexpected:
        problems.append(f"assets in the release are not in the index: {unexpected}")

    directory = Path(download_dir)
    directory.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for entry in sorted(expected, key=lambda item: item["asset"]):
        name = entry["asset"]
        api = by_name.get(name)
        record = {
            **entry,
            "verification": FAILED,
            "verified": False,
            "actual_bytes": None,
            "actual_sha256": None,
            "url": None,
            "metadata": api is not None,
        }
        if api is None:
            record["error"] = "not present in the published release"
            results.append(record)
            continue
        # Metadata reconciliation happens even if the download cannot.
        metadata_ok = True
        if entry["bytes"] is not None and api.get("bytes") != entry["bytes"]:
            metadata_ok = False
            problems.append(f"{name} is {api.get('bytes')} bytes, index says {entry['bytes']}")
        if api.get("sha256") and entry["sha256"] and api["sha256"] != entry["sha256"]:
            metadata_ok = False
            problems.append(f"{name} API digest {api['sha256']} != index {entry['sha256']}")
        record["verification"] = METADATA_VERIFIED if metadata_ok else FAILED
        urls = _asset_urls(entry, api, index)
        if not urls:
            record["error"] = "no download URL was available (metadata only)"
            results.append(record)
            continue
        downloaded = None
        errors: list[str] = []
        for url in urls:
            try:
                downloaded = _download(url, directory / name, token=token, timeout=timeout)
                break
            except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
                errors.append(f"{url}: {exc}")
        if downloaded is None:
            record["error"] = "; ".join(errors) or "download failed"
            problems.append(f"{name} could not be downloaded: {record['error']}")
            results.append(record)
            continue
        record["url"] = downloaded["url"]
        record["actual_bytes"] = downloaded["bytes"]
        record["actual_sha256"] = downloaded["sha256"]
        ok = True
        if entry["bytes"] is not None and downloaded["bytes"] != entry["bytes"]:
            ok = False
            problems.append(f"{name} downloaded {downloaded['bytes']} bytes, expected {entry['bytes']}")
        if entry["sha256"] and downloaded["sha256"] != entry["sha256"]:
            ok = False
            problems.append(f"{name} downloaded sha256 {downloaded['sha256']} != index {entry['sha256']}")
        record["verification"] = BYTE_VERIFIED if ok else FAILED
        record["verified"] = bool(ok)
        results.append(record)

    restoration: dict[str, Any] = {}
    if restore:
        store_dir = Path(fresh_store) if fresh_store else directory / "fresh_store"
        restoration = {
            "packages": _restore_packages(index, directory, store_dir),
            "multipart": _reconstruct_multipart(index, directory, directory / "reconstructed"),
        }
        problems.extend(restoration["packages"]["problems"])
        problems.extend(restoration["multipart"]["problems"])

    byte_verified = [item["asset"] for item in results if item["verification"] == BYTE_VERIFIED]
    metadata_only = [item["asset"] for item in results
                     if item["verification"] == METADATA_VERIFIED]
    failed = [item["asset"] for item in results if item["verification"] == FAILED]
    return {
        "schema": "atlas.open_data.release_verification.v1",
        "repository": repo,
        "tag": tag,
        "release": {
            "html_url": release.get("html_url"),
            "draft": bool(release.get("draft")),
            "published_at": release.get("published_at"),
        },
        "index": str(index_file),
        "download_dir": str(directory),
        "expected_assets": len(expected),
        "published_assets": len(api_assets),
        "missing": missing,
        "unexpected": unexpected,
        "byte_verified_count": len(byte_verified),
        "metadata_only_count": len(metadata_only),
        "failed_count": len(failed),
        "byte_verified": byte_verified,
        "metadata_only": metadata_only,
        "failed": failed,
        "assets": results,
        "restoration": restoration,
        "problems": problems,
        "ok": not problems and not failed and not metadata_only,
    }
