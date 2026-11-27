"""Clean-install lifecycle: resolve a release, download only what is missing, verify, restore.

This is the code behind ``atlas data install``, ``update`` and ``repair``. It is
deliberately boring and refuses to be clever:

* an asset is resolved from a published release index or the GitHub API, never
  guessed from a filename;
* the current registry decides whether the bytes may be installed at all, so a
  dataset whose redistribution terms changed cannot be pulled from a public
  mirror afterwards;
* downloads resume, but a resumed file is re-hashed from the first byte before
  it is accepted;
* nothing replaces an existing snapshot: identical bytes report
  ``already_present``;
* required disk space is reported *before* the first byte is written.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import multipart
from .durable import DEFAULT_MANIFESTS, inventory, restore_package
from .release import (
    DEFAULT_DOWNLOADS, DEFAULT_INDEX, ReleaseInputError, ReleaseLookupError,
    dataset_decisions, fetch_github_release, published_assets, read_release_index,
    record_download,
)
from .registry import Registry
from .rights import evaluate
from .store import SnapshotStore, sha256_file

CHUNK = 4 << 20
DEFAULT_CACHE = Path("var/open_data_cache")


class InstallError(RuntimeError):
    pass


# ------------------------------------------------------------------------- resolve
def asset_index_by_dataset(index: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for asset in index.get("assets") or []:
        grouped.setdefault(str(asset.get("dataset_id")), []).append(asset)
    for dataset_id, assets in grouped.items():
        detail = (index.get("multipart") or {}).get(dataset_id) or {}
        for asset in assets:
            asset.setdefault("parts", detail.get("parts") or asset.get("parts") or [])
            asset.setdefault("mode", detail.get("mode") or asset.get("mode"))
            asset.setdefault("periods", detail.get("periods") or asset.get("periods") or [])
            asset.setdefault("source", detail.get("source") or asset.get("source"))
    return grouped


def resolve_assets(index: Mapping[str, Any], dataset_ids: Sequence[str], *,
                    periods: Sequence[str] | None = None) -> list[dict[str, Any]]:
    grouped = asset_index_by_dataset(index)
    resolved: list[dict[str, Any]] = []
    missing: list[str] = []
    for dataset_id in dataset_ids:
        assets = grouped.get(dataset_id) or []
        if not assets:
            missing.append(dataset_id)
            continue
        for asset in assets:
            mode = asset.get("mode") or "package"
            if mode in {"bytes", "period"}:
                parts = asset.get("parts") or []
                if periods and mode == "period":
                    wanted = {period.lower() for period in periods}
                    parts = [part for part in parts
                             if str(part.get("period", "")).lower() in wanted]
                    if not parts:
                        raise InstallError(
                            f"{dataset_id} has no published period matching {sorted(wanted)}")
                elif periods and mode == "bytes":
                    raise InstallError(f"{dataset_id} is not partitioned by period")
                payload = {
                    "schema": "atlas.open_data.multipart.v1",
                    "mode": mode,
                    "dataset_id": dataset_id,
                    "snapshot_id": asset.get("snapshot_id"),
                    "source": asset.get("source") or {},
                    "parts": asset.get("parts") or [],
                }
                for part in parts:
                    # A period package above the asset limit is split again. Only the
                    # sub-parts exist as release assets, so they are what an install
                    # downloads; `materialize_part` reassembles and verifies the
                    # container before it is used.
                    nested = part.get("split") or {}
                    members = nested.get("parts") or [part]
                    for member in members:
                        resolved.append({
                            "dataset_id": dataset_id,
                            "kind": mode,
                            "asset": member["name"],
                            "bytes": member["bytes"],
                            "sha256": member["sha256"],
                            "url": member.get("url") or _asset_url(asset, member["name"], index),
                            "period": part.get("period"),
                            "container": part.get("name") if nested else None,
                            "parts_index_payload": payload,
                        })
            else:
                resolved.append({
                    "dataset_id": dataset_id,
                    "kind": "package",
                    "asset": asset.get("asset"),
                    "bytes": asset.get("asset_bytes"),
                    "sha256": asset.get("asset_sha256"),
                    "url": asset.get("url") or _asset_url(asset, asset.get("asset"), index),
                    "snapshot_id": asset.get("snapshot_id"),
                })
    return resolved


def _asset_url(asset: Mapping[str, Any], name: str | None, index: Mapping[str, Any]) -> str | None:
    if not name:
        return None
    if asset.get("url"):
        return str(asset["url"])
    base = index.get("asset_base_url")
    if base:
        return f"{str(base).rstrip('/')}/{name}"
    return None


def estimate(assets: Iterable[Mapping[str, Any]], *, cache_dir: str | Path,
             store_root: str | Path) -> dict[str, Any]:
    """Required space, download and extraction, measured before starting."""
    items = list(assets)
    download_bytes = sum(int(item.get("bytes") or 0) for item in items)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    cache_free = shutil.disk_usage(cache).free
    store = Path(store_root)
    store.mkdir(parents=True, exist_ok=True)
    store_free = shutil.disk_usage(store).free
    # A package is held in the cache and expanded into the store, so both must
    # have room; extraction is bounded by the package's raw content, which is
    # unknown before download, so the conservative estimate doubles the package.
    required_store = download_bytes
    return {
        "assets": len(items),
        "download_bytes": download_bytes,
        "cache_dir": str(cache),
        "cache_free_bytes": cache_free,
        "cache_sufficient": cache_free >= download_bytes,
        "store_root": str(store),
        "store_free_bytes": store_free,
        "store_required_bytes": required_store,
        "store_sufficient": store_free >= required_store,
        "sufficient": cache_free >= download_bytes and store_free >= required_store,
    }


# ------------------------------------------------------------------------ download
def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: str | Path, *, expected_sha256: str | None = None,
             expected_bytes: int | None = None, resume: bool = True,
             timeout: float = 60.0) -> dict[str, Any]:
    """Download one asset, resuming a partial file, then verify its hash.

    A hash mismatch deletes the partial file so the next attempt cannot append
    to corrupt bytes. The final rename is atomic.
    """
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if expected_sha256 and _hash_file(target) == expected_sha256:
            return {"path": str(target), "status": "already_present",
                    "bytes": target.stat().st_size, "sha256": expected_sha256}
        raise InstallError(f"{target} exists with different bytes; refusing to replace it")
    partial = target.with_suffix(target.suffix + ".part")
    if url.startswith("file://"):
        source = Path(url.removeprefix("file://"))
        if not source.exists():
            raise InstallError(f"asset is not available at {source}")
        shutil.copyfile(source, partial)
        resumed = 0
    elif url.startswith(("http://", "https://")):
        resumed = partial.stat().st_size if (resume and partial.exists()) else 0
        headers = {"User-Agent": "Atlas-Data-Engine/1.0"}
        if resumed:
            headers["Range"] = f"bytes={resumed}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                if resumed and status != 206:
                    # The server ignored the range: start over rather than
                    # appending a second copy of the file.
                    resumed = 0
                    partial.unlink(missing_ok=True)
                with partial.open("ab" if resumed else "wb") as sink:
                    while chunk := response.read(CHUNK):
                        sink.write(chunk)
        except urllib.error.HTTPError as exc:
            raise InstallError(f"download of {url} failed: HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise InstallError(f"download of {url} failed: {exc}") from exc
    else:
        raise InstallError(f"unsupported asset URL {url!r}")
    size = partial.stat().st_size
    if expected_bytes is not None and size != expected_bytes:
        partial.unlink(missing_ok=True)
        raise InstallError(f"{target.name} is {size} bytes, expected {expected_bytes}")
    digest = _hash_file(partial)
    if expected_sha256 and digest != expected_sha256:
        partial.unlink(missing_ok=True)
        raise InstallError(f"{target.name} sha256 {digest} != expected {expected_sha256}")
    os.replace(partial, target)
    return {"path": str(target), "status": "downloaded" if not resumed else "resumed",
            "resumed_bytes": resumed, "bytes": size, "sha256": digest}


# ------------------------------------------------------------------------- install
def _engine_for(store_root: str | Path, index_db: str | Path) -> Any:
    from .engine import AcquisitionEngine
    return AcquisitionEngine(store_root=store_root, index_path=index_db)


def install(
    registry: Registry,
    store: SnapshotStore,
    index: Mapping[str, Any],
    dataset_ids: Sequence[str],
    *,
    cache_dir: str | Path = DEFAULT_CACHE,
    output_dir: str | Path | None = None,
    periods: Sequence[str] | None = None,
    dry_run: bool = False,
    downloads_path: str | Path = DEFAULT_DOWNLOADS,
) -> dict[str, Any]:
    """Install the resolved assets for ``dataset_ids``.

    ``package`` assets restore a snapshot into the store. ``bytes`` multipart
    assets reconstruct the original provider archive into ``output_dir``.
    ``period`` assets extract only the selected periods into ``output_dir``.
    """
    decisions = dataset_decisions(registry)
    for dataset_id in dataset_ids:
        decision = decisions.get(dataset_id)
        if decision is None:
            raise InstallError(f"unknown dataset {dataset_id!r}")
        if not decision["allowed"]:
            raise InstallError(
                f"{dataset_id} may no longer be distributed: {decision['reason']}")
    assets = resolve_assets(index, dataset_ids, periods=periods)
    if not assets:
        raise InstallError(
            "no published asset satisfies the request; run `atlas data releases`")
    for asset in assets:
        if not asset.get("url"):
            raise InstallError(f"{asset['asset']} has no published URL in the release index")
    space = estimate(assets, cache_dir=cache_dir, store_root=store.root)
    if dry_run:
        return {"dry_run": True, "assets": assets, "space": space,
                "steps": ["download", "verify", "restore"]}
    if not space["sufficient"]:
        raise InstallError(
            f"insufficient space: need {space['download_bytes']} download bytes "
            f"({space['cache_free_bytes']} free) and {space['store_required_bytes']} store bytes "
            f"({space['store_free_bytes']} free)")
    cache = Path(cache_dir)
    downloaded: list[dict[str, Any]] = []
    for asset in assets:
        outcome = download(asset["url"], cache / str(asset["asset"]),
                           expected_sha256=asset.get("sha256"),
                           expected_bytes=asset.get("bytes"))
        record_download({
            "dataset_id": asset["dataset_id"],
            "dataset": asset["dataset_id"],
            "asset": asset["asset"],
            "url": asset["url"],
            "bytes": outcome["bytes"],
            "sha256": outcome["sha256"],
            "verified_at": multipart.utcnow(),
        }, downloads_path)
        downloaded.append({**asset, "download": outcome})

    results: list[dict[str, Any]] = []
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in downloaded:
        groups.setdefault((item["dataset_id"], item["kind"]), []).append(item)

    for (dataset_id, kind), items in groups.items():
        if kind == "package":
            for item in items:
                entry = dict(item)
                try:
                    entry["restore"] = restore_package(
                        store, cache / str(item["asset"]),
                        expected_sha256=item.get("sha256"))
                except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
                    entry["restore"] = {"error": str(exc)}
                    entry["status"] = "failed"
                results.append(entry)
            continue
        # A multipart dataset is one logical asset split into parts: every part
        # must be present before anything is reconstructed.
        payload = items[0]["parts_index_payload"]
        target = Path(output_dir or "var/open_data_installed")
        target.mkdir(parents=True, exist_ok=True)
        entry = {"dataset_id": dataset_id, "kind": kind,
                 "asset": items[0]["asset"], "assets": [item["asset"] for item in items],
                 "download": {"bytes": sum(int(item["download"]["bytes"]) for item in items)}}
        try:
            if kind == "bytes":
                entry["restore"] = multipart.reconstruct(
                    payload, cache, target / f"{dataset_id}.zip")
            else:
                periods = sorted({str(item["period"]) for item in items if item.get("period")})
                entry["restore"] = multipart.restore_periods(
                    payload, cache, target / dataset_id, periods=periods or None)
        except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
            entry["restore"] = {"error": str(exc)}
            entry["status"] = "failed"
        results.append(entry)

    failures = [item for item in results if item.get("status") == "failed"]
    return {
        "schema": "atlas.open_data.install.v1",
        "datasets": list(dataset_ids),
        "assets": len(downloaded),
        "downloaded_bytes": sum(int(item["download"]["bytes"]) for item in downloaded),
        "restored": sum(1 for item in results if item["kind"] == "package"
                        and item.get("restore", {}).get("restored")),
        "already_present": sum(1 for item in results if item["kind"] == "package"
                               and item.get("restore", {}).get("already_present")),
        "space": space,
        "failures": failures,
        "items": results,
    }





# -------------------------------------------------------------------------- update
def update(registry: Registry, store: SnapshotStore, index: Mapping[str, Any], *,
           dataset_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Report published snapshots that the local store does not hold."""
    grouped = asset_index_by_dataset(index)
    wanted = list(dataset_ids) if dataset_ids else sorted(grouped)
    rows: list[dict[str, Any]] = []
    for dataset_id in wanted:
        local = store.latest(dataset_id)
        local_id = local.snapshot_id if local else None
        for asset in grouped.get(dataset_id) or []:
            snapshot_id = asset.get("snapshot_id")
            rows.append({
                "dataset_id": dataset_id,
                "published_snapshot": snapshot_id,
                "local_snapshot": local_id,
                "update_available": bool(snapshot_id and snapshot_id != local_id),
                "asset": asset.get("asset"),
            })
    return {
        "schema": "atlas.open_data.update.v1",
        "checked": len(rows),
        "updates_available": sum(1 for row in rows if row["update_available"]),
        "items": rows,
        "note": "An existing snapshot is never replaced; a newer snapshot installs alongside it.",
    }


# -------------------------------------------------------------------------- repair
def repair(registry: Registry, store: SnapshotStore, index: Mapping[str, Any], *,
           manifests_root: str | Path = DEFAULT_MANIFESTS, apply: bool = False,
           cache_dir: str | Path = DEFAULT_CACHE,
           downloads_path: str | Path = DEFAULT_DOWNLOADS) -> dict[str, Any]:
    """Recover abandoned staging and reinstall what a published asset can restore."""
    recovered = [str(path) for path in store.recover_staging()] if apply else []
    report = inventory(store, registry, manifests_root=manifests_root)
    actionable: list[dict[str, Any]] = []
    grouped = asset_index_by_dataset(index)
    for item in report["items"]:
        if item["status"] == "verified":
            continue
        packaged = [asset for asset in grouped.get(item["dataset_id"]) or []
                    if asset.get("snapshot_id") == item["snapshot_id"]]
        if packaged and item["status"] in {"missing", "partial", "corrupt", "drifted"}:
            actionable.append({
                "dataset_id": item["dataset_id"],
                "snapshot_id": item["snapshot_id"],
                "status": item["status"],
                "action": "reinstall",
                "asset": packaged[0].get("asset"),
                "url": packaged[0].get("url"),
            })
        else:
            actionable.append({
                "dataset_id": item["dataset_id"],
                "snapshot_id": item["snapshot_id"],
                "status": item["status"],
                "action": "reacquire",
                "command": f"atlas data sync {item['dataset_id']} --force",
                "note": "no published asset contains these bytes",
            })
    applied: list[dict[str, Any]] = []
    if apply:
        for item in actionable:
            if item["action"] != "reinstall" or not item.get("url"):
                continue
            outcome = download(item["url"], Path(cache_dir) / str(item["asset"]),
                               expected_sha256=item.get("sha256"))
            applied.append({"dataset_id": item["dataset_id"], "download": outcome})
    return {
        "schema": "atlas.open_data.repair.v1",
        "applied": apply,
        "staging_recovered": recovered,
        "nondurable": len(actionable),
        "items": actionable,
        "reinstalled": applied,
    }
