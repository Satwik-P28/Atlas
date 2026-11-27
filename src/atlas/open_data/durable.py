"""Durability inventory: what is actually preserved, and what is only claimed.

The acquisition engine stores raw bytes outside Git and exports a small manifest per
snapshot into ``data/open_data/manifests``. Those exported manifests are the recovery
contract: they name the exact source URL, retrieval time, provider validators and the
SHA-256 of every byte that was acquired.

This module answers a narrower question than ``atlas data verify``:

* is a committed manifest present for the dataset,
* is the referenced snapshot still in the local store,
* do the stored bytes still hash to the committed SHA-256,
* was the acquisition complete or capped/sampled,
* and may the snapshot be publicly redistributed?

A dataset is never reported as durable merely because a registry connector exists. The
status is derived from files and hashes, and every non-durable state carries a reason
and the exact recovery command.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .registry import Registry
from .rights import evaluate
from .store import Snapshot, SnapshotStore, sha256_file

DEFAULT_MANIFESTS = Path(__file__).resolve().parents[3] / "data/open_data/manifests"

#: Ordering is deliberate: the worst state wins when a dataset has several snapshots.
STATUS_ORDER = {
    "corrupt": 0,
    "partial": 1,
    "missing": 2,
    "drifted": 3,
    "sampled": 4,
    "unapproved": 5,
    "verified": 6,
}

#: Acquisition scope is a separate axis from file integrity. A complete provider archive
#: whose derived observation table is deliberately capped is still durably preserved;
#: conflating the two would either hide the cap or falsely call the bytes corrupt.
SCOPE_ORDER = {"sampled": 0, "capped": 1, "partial_scope": 2, "complete": 3}

CAP_MARKERS = ("entity_limit_applied", "row_limit", "page_limit", "max_rows", "max_observations")


@dataclass(slots=True)
class SnapshotInventory:
    dataset_id: str
    snapshot_id: str
    committed: bool
    present: bool
    status: str
    reason: str
    source_bytes: int
    stored_bytes: int
    files_expected: int
    files_present: int
    hash_mismatches: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    sampled: bool = False
    sample_markers: list[str] = field(default_factory=list)
    acquisition_scope: str = "complete"
    redistributable: bool = False
    rights_reason: str = ""
    source_url: str | None = None
    retrieved_at: str | None = None
    completed_at: str | None = None
    latest: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "snapshot_id": self.snapshot_id,
            "committed": self.committed,
            "present": self.present,
            "status": self.status,
            "reason": self.reason,
            "source_bytes": self.source_bytes,
            "stored_bytes": self.stored_bytes,
            "files_expected": self.files_expected,
            "files_present": self.files_present,
            "hash_mismatches": self.hash_mismatches,
            "missing_files": self.missing_files,
            "sampled": self.sampled,
            "sample_markers": self.sample_markers,
            "acquisition_scope": self.acquisition_scope,
            "redistributable": self.redistributable,
            "rights_reason": self.rights_reason,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "completed_at": self.completed_at,
            "latest": self.latest,
        }


def committed_manifests(root: str | Path = DEFAULT_MANIFESTS) -> dict[str, dict[str, dict[str, Any]]]:
    """Read every exported manifest keyed by dataset and snapshot id."""
    base = Path(root)
    found: dict[str, dict[str, dict[str, Any]]] = {}
    if not base.exists():
        return found
    for path in sorted(base.glob("*/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        dataset_id = str(payload.get("dataset_id") or path.parent.name)
        snapshot_id = str(payload.get("snapshot_id") or path.stem)
        payload["_manifest_path"] = str(path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path)
        found.setdefault(dataset_id, {})[snapshot_id] = payload
    return found


def _cap_markers(manifest: Mapping[str, Any]) -> list[str]:
    stats = manifest.get("stats") or {}
    extras = stats.get("extra") if isinstance(stats.get("extra"), dict) else {}
    markers: list[str] = []
    for source in (stats, extras):
        if not isinstance(source, Mapping):
            continue
        for key in CAP_MARKERS:
            value = source.get(key)
            if value not in (None, 0, False, "", []):
                markers.append(f"{key}={value}")
        if source.get("sampled") is True:
            markers.append("sampled=true")
        if source.get("capped") is True:
            markers.append("capped=true")
    for issue in stats.get("issues") or []:
        code = str((issue or {}).get("code") or "")
        if code in {"entity_limit_applied", "row_limit", "page_limit", "observation_limit"}:
            markers.append(f"issue:{code}")
        if code == "archive_series_gap":
            markers.append("partial_scope:archive_series_gap")
    if extras.get("partial_scope") is True:
        markers.append("partial_scope=true")
    return sorted(set(markers))


def _compare(committed: Mapping[str, Any], stored: Snapshot) -> tuple[str, str, list[str], list[str], int]:
    """Compare a committed manifest with the stored snapshot, byte for byte."""
    committed_files = {str(item.get("path")): item for item in committed.get("files") or []}
    stored_files = {str(item.get("path")): item for item in stored.files}
    missing = sorted(set(committed_files) - set(stored_files))
    unexpected = sorted(set(stored_files) - set(committed_files))
    mismatches: list[str] = []
    stored_bytes = 0
    for path, expected in committed_files.items():
        actual = stored_files.get(path)
        if actual is None:
            continue
        stored_bytes += int(actual.get("bytes") or 0)
        if int(actual.get("bytes") or -1) != int(expected.get("bytes") or -2):
            mismatches.append(f"{path}: size {actual.get('bytes')} != {expected.get('bytes')}")
        elif str(actual.get("sha256")) != str(expected.get("sha256")):
            # A hash mismatch on the stored manifest is only drift if the bytes themselves
            # also disagree; verify() checks the bytes and is called by the inventory.
            mismatches.append(f"{path}: sha256 {actual.get('sha256')} != {expected.get('sha256')}")
    if missing:
        return "partial", f"{len(missing)} committed file(s) absent from the store", mismatches, missing, stored_bytes
    if mismatches:
        return "drifted", f"{len(mismatches)} file(s) differ from the committed manifest", mismatches, missing, stored_bytes
    if unexpected:
        # Derived files added later are not corruption, but they are not part of the
        # committed recovery contract either. Report them without failing verification.
        return "verified", f"{len(unexpected)} additional derived file(s) present", mismatches, missing, stored_bytes
    return "verified", "stored bytes match the committed manifest", mismatches, missing, stored_bytes


def inventory(
    store: SnapshotStore,
    registry: Registry,
    *,
    manifests_root: str | Path = DEFAULT_MANIFESTS,
    dataset_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return a measured durability inventory for every registered dataset."""
    if isinstance(dataset_ids, str):
        dataset_ids = [dataset_ids]
    wanted = set(dataset_ids) if dataset_ids else None
    latest_ids: set[str] = set()
    for dataset_id in {snapshot.dataset_id for snapshot in store.list_snapshots()}:
        if wanted is not None and dataset_id not in wanted:
            continue
        latest = store.latest(dataset_id)
        if latest is not None:
            latest_ids.add(latest.snapshot_id)
    committed = committed_manifests(manifests_root)
    rows: list[SnapshotInventory] = []
    for dataset in registry:
        if wanted is not None and dataset.id not in wanted:
            continue
        decision = evaluate(dataset.raw, "publish", public_distribution=True)
        dataset_manifests = committed.get(dataset.id, {})
        stored = {snapshot.snapshot_id: snapshot for snapshot in store.list_snapshots(dataset.id)}
        if not dataset_manifests and not stored:
            rows.append(SnapshotInventory(
                dataset_id=dataset.id, snapshot_id="-", committed=False, present=False,
                status="missing", reason="no committed manifest and no stored snapshot",
                source_bytes=0, stored_bytes=0, files_expected=0, files_present=0,
                redistributable=decision.allowed, rights_reason=decision.reason,
                source_url=dataset.download_endpoint,
            ))
            continue
        for snapshot_id in sorted(set(dataset_manifests) | set(stored)):
            manifest = dataset_manifests.get(snapshot_id)
            snapshot = stored.get(snapshot_id)
            expected_files = len((manifest or {}).get("files") or (snapshot.files if snapshot else []))
            source_bytes = sum(int(item.get("bytes") or 0) for item in (manifest or {}).get("files") or [])
            if manifest is None:
                status, reason = "unapproved", "stored snapshot has no committed manifest; it is not part of the recovery contract"
                rows.append(SnapshotInventory(
                    dataset_id=dataset.id, snapshot_id=snapshot_id, committed=False, present=True,
                    status=status, reason=reason, source_bytes=source_bytes,
                    stored_bytes=sum(int(item.get("bytes") or 0) for item in snapshot.files),
                    files_expected=expected_files, files_present=len(snapshot.files),
                    redistributable=decision.allowed, rights_reason=decision.reason,
                    source_url=dataset.download_endpoint,
                ))
                continue
            if snapshot is None:
                rows.append(SnapshotInventory(
                    dataset_id=dataset.id, snapshot_id=snapshot_id, committed=True, present=False,
                    status="missing", reason="committed manifest has no matching snapshot in this store",
                    source_bytes=source_bytes, stored_bytes=0, files_expected=expected_files,
                    files_present=0, redistributable=decision.allowed,
                    rights_reason=decision.reason,
                    source_url=(manifest.get("source") or {}).get("download_endpoint") or dataset.download_endpoint,
                    retrieved_at=(manifest.get("retrieval") or {}).get("completed_at"),
                    completed_at=manifest.get("completed_at"),
                ))
                continue
            status, reason, mismatches, missing, stored_bytes = _compare(manifest, snapshot)
            verification = store.verify(snapshot, deep=True)
            if not verification["ok"]:
                missing = sorted(set(missing) | {
                    error.split(": ", 1)[1] for error in verification["errors"]
                    if error.startswith("missing file: ")
                })
                status = "partial" if missing else "corrupt"
                reason = "; ".join(verification["errors"][:4])
            markers = _cap_markers({**(manifest or {}), **(snapshot.manifest or {})})
            scope = "complete"
            if markers:
                if any("partial_scope" in marker for marker in markers):
                    scope = "partial_scope"
                elif any("sampl" in marker for marker in markers):
                    scope = "sampled"
                else:
                    scope = "capped"
                if status == "verified":
                    reason = (reason + "; derived/indexed scope is capped: " + ", ".join(markers)).strip("; ")
            rows.append(SnapshotInventory(
                dataset_id=dataset.id, snapshot_id=snapshot_id, committed=True, present=True,
                status=status, reason=reason, source_bytes=source_bytes, stored_bytes=stored_bytes,
                latest=snapshot_id in latest_ids,
                files_expected=expected_files, files_present=len(snapshot.files),
                hash_mismatches=mismatches, missing_files=missing, sampled=bool(markers),
                sample_markers=markers, acquisition_scope=scope,
                redistributable=decision.allowed,
                rights_reason=decision.reason,
                source_url=(manifest.get("source") or {}).get("download_endpoint") or dataset.download_endpoint,
                retrieved_at=(manifest.get("retrieval") or {}).get("completed_at"),
                completed_at=manifest.get("completed_at"),
            ))

    by_status: dict[str, int] = {}
    by_scope: dict[str, int] = {}
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
        if row.status == "verified":
            by_scope[row.acquisition_scope] = by_scope.get(row.acquisition_scope, 0) + 1
    datasets = {row.dataset_id for row in rows}
    durable_datasets = {row.dataset_id for row in rows if row.status == "verified"}
    publishable = {row.dataset_id for row in rows if row.redistributable and row.status == "verified"}
    latest_rows = [row for row in rows if row.latest]
    latest_by_status: dict[str, int] = {}
    for row in latest_rows:
        latest_by_status[row.status] = latest_by_status.get(row.status, 0) + 1
    return {
        "schema": "atlas.open_data.durability.v1",
        "store_root": str(store.root),
        "manifests_root": str(manifests_root),
        "datasets": len(datasets),
        "snapshots": len(rows),
        "verified_snapshots": by_status.get("verified", 0),
        "durable_datasets": len(durable_datasets),
        "publishable_datasets": len(publishable),
        "source_bytes_committed": sum(row.source_bytes for row in rows if row.committed),
        "stored_bytes_present": sum(row.stored_bytes for row in rows if row.present),
        "by_status": dict(sorted(by_status.items())),
        "by_acquisition_scope": dict(sorted(by_scope.items())),
        "latest_datasets": len(latest_rows),
        "latest_by_status": dict(sorted(latest_by_status.items())),
        "latest_verified_datasets": sum(1 for row in latest_rows if row.status == "verified"),
        "items": [row.to_dict() for row in rows],
        "recovery": recovery_plan(rows),
        "note": (
            "verified means the stored bytes hash to the committed manifest. It does not mean the "
            "provider still serves those bytes; providers revise archives. A fresh installation can "
            "reconstruct an exact snapshot only from a package or mirror that contains those bytes."
        ),
    }


def recovery_plan(rows: Iterable[SnapshotInventory]) -> list[dict[str, Any]]:
    """Commands that rebuild each non-durable dataset from its official source."""
    plan: list[dict[str, Any]] = []
    for dataset_id in sorted({row.dataset_id for row in rows if row.status != "verified"}):
        failed = sorted({row.status for row in rows if row.dataset_id == dataset_id and row.status != "verified"})
        plan.append({
            "dataset_id": dataset_id,
            "states": failed,
            "action": "reacquire",
            "command": f"atlas data sync {dataset_id} --force",
            "note": "Provider bytes may have changed since the committed snapshot; a rebuild is not a byte-identical restore.",
        })
    return plan


def release_candidates(
    store: SnapshotStore,
    registry: Registry,
    *,
    manifests_root: str | Path = DEFAULT_MANIFESTS,
    max_bytes: int = 2_000_000_000,
) -> dict[str, Any]:
    """Snapshots that are verified, approved and small enough for a release asset.

    Nothing is packaged here. The result is the exact input to
    ``scripts/build_open_data_package.py`` and to a release workflow, so a rights
    decision cannot be silently skipped at upload time.
    """
    report = inventory(store, registry, manifests_root=manifests_root)
    items = [
        item for item in report["items"]
        if item["status"] == "verified" and item["redistributable"] and item["present"]
    ]
    by_dataset: dict[str, dict[str, Any]] = {}
    for item in items:
        current = by_dataset.get(item["dataset_id"])
        if current is None or item["source_bytes"] > current["source_bytes"]:
            by_dataset[item["dataset_id"]] = item
    oversized = []
    selected = []
    for dataset_id, item in sorted(by_dataset.items()):
        if item["source_bytes"] > max_bytes:
            oversized.append({"dataset_id": dataset_id, "source_bytes": item["source_bytes"]})
        else:
            selected.append(item)
    return {
        "schema": "atlas.open_data.release_plan.v1",
        "max_asset_bytes": max_bytes,
        "datasets": len(selected),
        "source_bytes": sum(item["source_bytes"] for item in selected),
        "selected": selected,
        "oversized": oversized,
        "excluded_unverified_rights": [
            item for item in report["items"]
            if item["status"] == "verified" and not item["redistributable"]
        ],
        "note": "Only verified and rights-approved snapshots are listed. Oversized datasets need per-dataset packaging.",
    }


def package_manifest(
    snapshot: Snapshot,
    dataset: Mapping[str, Any],
    *,
    package_path: str | None = None,
) -> dict[str, Any]:
    """The small, committable record that proves what a release asset contains."""
    return {
        "dataset_id": snapshot.dataset_id,
        "snapshot_id": snapshot.snapshot_id,
        "completed_at": snapshot.manifest.get("completed_at"),
        "retrieved_at": (snapshot.manifest.get("retrieval") or {}).get("completed_at"),
        "provider": dataset.get("provider"),
        "title": dataset.get("title"),
        "source": snapshot.manifest.get("source"),
        "rights": snapshot.manifest.get("rights"),
        "files": [
            {"path": entry["path"], "bytes": entry["bytes"], "sha256": entry["sha256"]}
            for entry in snapshot.files
        ],
        "manifest_sha256": snapshot.manifest_sha256,
        "package": package_path,
        "restore": (
            "atlas data restore <package> --expect-sha256 <manifest_sha256>"
        ),
    }


def write_release_index(
    store: SnapshotStore,
    registry: Registry,
    destination: str | Path,
    *,
    manifests_root: str | Path = DEFAULT_MANIFESTS,
    max_bytes: int = 2_000_000_000,
) -> Path:
    """Write the committable release index (no bulk bytes)."""
    plan = release_candidates(store, registry, manifests_root=manifests_root, max_bytes=max_bytes)
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def restore_package(
    store: SnapshotStore,
    package: str | Path,
    *,
    expected_sha256: str | None = None,
    verify_package_hash: bool = True,
) -> dict[str, Any]:
    """Restore a distribution archive into a store, verifying every byte first.

    The package is untrusted input. Nothing is published into the store until the
    archive checksum, the embedded manifest and every file hash have been checked. An
    existing snapshot id is never overwritten: restoring the same package twice is
    idempotent and reports ``already_present``.
    """
    import tarfile
    import tempfile

    path = Path(package)
    if not path.exists():
        raise FileNotFoundError(f"package does not exist: {path}")
    actual = sha256_file(path)
    if expected_sha256 and actual != expected_sha256:
        raise ValueError(f"package sha256 {actual} does not match expected {expected_sha256}")
    if verify_package_hash:
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if sidecar.exists():
            declared = sidecar.read_text(encoding="utf-8").split()[0]
            if declared != actual:
                raise ValueError(f"package sha256 {actual} does not match sidecar {declared}")
    try:
        import zstandard as zstd
    except ImportError as exc:  # pragma: no cover - depends on the install extra
        raise RuntimeError("zstandard is required to restore a .tar.zst package") from exc

    restored: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="atlas-restore-") as directory:
        staging_root = Path(directory)
        with path.open("rb") as stream:
            with zstd.ZstdDecompressor().stream_reader(stream) as decompressed:
                with tarfile.open(fileobj=decompressed, mode="r|") as archive:
                    for member in archive:
                        name = member.name
                        if name.startswith("/") or ".." in Path(name).parts:
                            raise ValueError(f"unsafe archive member: {name}")
                        if not member.isfile():
                            continue
                        target = staging_root / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        source = archive.extractfile(member)
                        if source is None:
                            raise ValueError(f"cannot read archive member: {name}")
                        target.write_bytes(source.read())
        manifest_path = staging_root / "PACKAGE_MANIFEST.json"
        if not manifest_path.exists():
            raise ValueError("package has no PACKAGE_MANIFEST.json")
        catalogue = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in catalogue.get("datasets") or []:
            dataset_id = str(item["dataset_id"])
            snapshot_id = str(item["snapshot_id"])
            if store.snapshot_path(dataset_id, snapshot_id).exists():
                restored.append({"dataset_id": dataset_id, "snapshot_id": snapshot_id,
                                 "status": "already_present"})
                continue
            source_dir = staging_root / "datasets" / dataset_id / snapshot_id
            embedded = source_dir / "manifest.json"
            if not embedded.exists():
                raise ValueError(f"package is missing the manifest for {dataset_id}/{snapshot_id}")
            manifest = json.loads(embedded.read_text(encoding="utf-8"))
            if manifest.get("snapshot_id") != snapshot_id:
                raise ValueError(f"manifest snapshot id mismatch for {dataset_id}")
            staging = store.new_staging(dataset_id)
            # The store derives the snapshot id from the staging directory name. A restore
            # must reproduce the original id exactly, so the directory is renamed before
            # commit instead of minting a new identity for identical bytes.
            exact = staging.parent / f".staging-{snapshot_id}"
            if exact.exists():
                raise ValueError(f"staging path already exists: {exact}")
            staging.rename(exact)
            staging = exact
            try:
                for entry in manifest.get("files") or []:
                    source_file = source_dir / "files" / entry["path"]
                    if not source_file.exists():
                        raise ValueError(f"package is missing {dataset_id}/{entry['path']}")
                    if sha256_file(source_file) != entry["sha256"]:
                        raise ValueError(f"package file hash mismatch: {dataset_id}/{entry['path']}")
                    store.add_file(staging, source_file, name=entry["name"],
                                   content_type=entry.get("content_type"),
                                   uncompressed_bytes=entry.get("uncompressed_bytes"),
                                   records=entry.get("record_count"), notes=entry.get("notes"))
                # Preserve the original snapshot id rather than minting a new one.
                final = store.snapshot_path(dataset_id, snapshot_id)
                staged_manifest = dict(manifest)
                staged_manifest["restored_from"] = path.name
                snapshot = store.commit(staging, staged_manifest)
                if snapshot.snapshot_id != snapshot_id:  # pragma: no cover - defensive
                    raise ValueError("restored snapshot id changed")
                verification = store.verify(snapshot, deep=True)
                if not verification["ok"]:
                    raise ValueError(f"restored snapshot failed verification: {verification['errors']}")
                restored.append({"dataset_id": dataset_id, "snapshot_id": snapshot_id,
                                 "status": "restored", "bytes": sum(
                                     int(f.get("bytes") or 0) for f in snapshot.files)})
            except Exception:
                store.quarantine(staging, dataset_id, "restore failed verification")
                raise
    return {
        "package": str(path),
        "sha256": actual,
        "datasets": len(restored),
        "restored": sum(1 for item in restored if item["status"] == "restored"),
        "already_present": sum(1 for item in restored if item["status"] == "already_present"),
        "items": restored,
    }


def copy_to_durable(source: str | Path, destination: str | Path) -> dict[str, Any]:
    """Copy a verified store to an explicitly chosen durable location.

    Copying is refused when the destination is inside the source. The destination's free
    space is checked before the copy starts so a partial mirror is not left behind.
    """
    src = Path(source).resolve()
    dst = Path(destination).resolve()
    if not src.exists():
        raise FileNotFoundError(f"store does not exist: {src}")
    if dst == src or src in dst.parents:
        raise ValueError("durable destination must be outside the source store")
    required = sum(path.stat().st_size for path in src.rglob("*") if path.is_file())
    dst.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(dst).free
    if free < required:
        raise OSError(f"destination needs {required} bytes but only {free} are free")
    staged = dst / ".atlas-copy-staging"
    staged.mkdir(exist_ok=True)
    shutil.copytree(src, staged, dirs_exist_ok=True, copy_function=shutil.copy2)
    return {
        "source": str(src),
        "destination": str(dst),
        "bytes": required,
        "staged": str(staged),
        "note": "Verify the staged copy, then replace the destination atomically.",
    }
