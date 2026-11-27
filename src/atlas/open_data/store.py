"""Content-addressed immutable snapshot store.

Layout under the store root::

    blobs/sha256/<aa>/<full-sha256>          exact source bytes, immutable
    datasets/<dataset_id>/<snapshot_id>/      hard links + manifest.json + manifest.sha256
    quarantine/<dataset_id>/<stamp>/           rejected staging, kept for evidence
    checkpoints/<dataset_id>.json              ETag / Last-Modified / cursor

Snapshots are published with a single directory rename. A crash leaves a ``.staging-*``
directory that is never read by queries, and recovery moves it to quarantine rather
than guessing whether it is complete. A blob that already exists is reused: identical
bytes are never copied twice and never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


class StoreError(RuntimeError):
    pass


class SnapshotExists(StoreError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: str | Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(slots=True)
class Snapshot:
    dataset_id: str
    snapshot_id: str
    path: Path
    manifest: dict[str, Any]
    manifest_sha256: str

    @property
    def files(self) -> list[dict[str, Any]]:
        return list(self.manifest.get("files") or [])

    def file(self, name: str) -> Path:
        for entry in self.files:
            if entry.get("name") == name:
                return self.path / "files" / entry["path"]
        raise KeyError(f"{self.dataset_id}/{self.snapshot_id} has no file {name!r}")


class SnapshotStore:
    def __init__(self, root: str | Path = "var/open_data") -> None:
        self.root = Path(root)
        self.blobs = self.root / "blobs" / "sha256"
        self.datasets = self.root / "datasets"
        self.quarantine_root = self.root / "quarantine"
        self.checkpoint_root = self.root / "checkpoints"
        for directory in (self.blobs, self.datasets, self.quarantine_root, self.checkpoint_root):
            directory.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ staging
    def new_staging(self, dataset_id: str) -> Path:
        parent = self.datasets / dataset_id
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / f".staging-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        path.mkdir()
        (path / "files").mkdir()
        return path

    def blob_path(self, digest: str) -> Path:
        return self.blobs / digest[:2] / digest

    def _store_blob(self, path: Path) -> tuple[Path, str]:
        digest = sha256_file(path)
        target = self.blob_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.stat().st_size != path.stat().st_size:
                raise StoreError(f"blob collision for {digest}")
            path.unlink()
        else:
            os.replace(path, target)
            os.chmod(target, 0o444)
        return target, digest

    def add_file(self, staging: Path, source: str | Path, *, name: str, content_type: str | None = None,
                 uncompressed_bytes: int | None = None, records: int | None = None,
                 notes: str | None = None) -> dict[str, Any]:
        source_path = Path(source)
        blob, digest = self._store_blob(source_path)
        relative = name.lstrip("/").replace("..", "_")
        destination = staging / "files" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise StoreError(f"duplicate file name in snapshot: {name}")
        os.link(blob, destination)
        entry: dict[str, Any] = {
            "name": name,
            "path": relative,
            "bytes": destination.stat().st_size,
            "sha256": digest,
            "content_type": content_type,
        }
        if uncompressed_bytes is not None:
            entry["uncompressed_bytes"] = uncompressed_bytes
        if records is not None:
            entry["record_count"] = records
        if notes:
            entry["notes"] = notes
        return entry

    def commit(self, staging: Path, manifest: Mapping[str, Any]) -> Snapshot:
        dataset_id = str(manifest["dataset_id"])
        files = list(manifest.get("files") or [])
        staging = Path(staging)
        parent = self.datasets / dataset_id
        parent.mkdir(parents=True, exist_ok=True)
        snapshot_id = staging.name.removeprefix(".staging-")
        final = parent / snapshot_id
        if final.exists():
            raise SnapshotExists(f"snapshot already exists: {final}")
        payload = dict(manifest)
        payload["manifest_version"] = 1
        payload["snapshot_id"] = snapshot_id
        payload["completed_at"] = payload.get("completed_at") or utcnow()
        payload["files"] = files
        serialised = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        manifest_sha = hashlib.sha256(serialised.encode()).hexdigest()
        (staging / "manifest.json").write_text(serialised, encoding="utf-8")
        (staging / "manifest.sha256").write_text(manifest_sha + "  manifest.json\n", encoding="utf-8")
        os.replace(staging, final)
        return Snapshot(dataset_id, final.name, final, payload, manifest_sha)

    def quarantine(self, staging: str | Path, dataset_id: str, reason: str,
                   details: Mapping[str, Any] | None = None) -> Path:
        staging = Path(staging)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        target = self.quarantine_root / dataset_id / f"{stamp}-{uuid.uuid4().hex[:8]}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            os.replace(staging, target)
        else:
            target.mkdir(parents=True)
        (target / "quarantine.json").write_text(json.dumps({
            "dataset_id": dataset_id,
            "reason": reason,
            "details": dict(details or {}),
            "at": utcnow(),
        }, indent=2) + "\n", encoding="utf-8")
        return target

    # ------------------------------------------------------------------- reading
    def snapshot_path(self, dataset_id: str, snapshot_id: str) -> Path:
        return self.datasets / dataset_id / snapshot_id

    def list_snapshots(self, dataset_id: str | None = None) -> list[Snapshot]:
        roots = [self.datasets / dataset_id] if dataset_id else sorted(
            path for path in self.datasets.iterdir() if path.is_dir()
        )
        snapshots: list[Snapshot] = []
        for root in roots:
            if not root.is_dir():
                continue
            for entry in sorted(root.iterdir()):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                manifest_path = entry / "manifest.json"
                if not manifest_path.exists():
                    continue
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest_sha = sha256_file(manifest_path)
                snapshots.append(Snapshot(root.name, entry.name, entry, manifest, manifest_sha))
        return sorted(snapshots, key=lambda s: s.snapshot_id)

    def latest(self, dataset_id: str) -> Snapshot | None:
        snapshots = self.list_snapshots(dataset_id)
        return snapshots[-1] if snapshots else None

    def verify(self, snapshot: Snapshot | str | Path, *, deep: bool = True) -> dict[str, Any]:
        if not isinstance(snapshot, Snapshot):
            path = Path(snapshot)
            manifest_path = path / "manifest.json"
            if not manifest_path.exists():
                raise StoreError(f"not a snapshot: {path}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            snapshot = Snapshot(path.parent.name, path.name, path, manifest, sha256_file(manifest_path))
        errors: list[str] = []
        checked: list[dict[str, Any]] = []
        manifest_actual = sha256_file(snapshot.path / "manifest.json")
        if manifest_actual != snapshot.manifest_sha256:
            errors.append(f"manifest hash mismatch: {manifest_actual} != {snapshot.manifest_sha256}")
        expected_names = set()
        for entry in snapshot.files:
            file_path = snapshot.path / "files" / entry["path"]
            expected_names.add(entry["path"])
            if not file_path.exists():
                errors.append(f"missing file: {entry['path']}")
                continue
            size = file_path.stat().st_size
            if size != entry["bytes"]:
                errors.append(f"size mismatch for {entry['path']}: {size} != {entry['bytes']}")
            digest = sha256_file(file_path) if deep else None
            if deep and digest != entry["sha256"]:
                errors.append(f"sha256 mismatch for {entry['path']}")
            checked.append({"path": entry["path"], "bytes": size, "sha256": digest or entry["sha256"],
                            "ok": not any(entry["path"] in error for error in errors)})
        actual_names = {p.relative_to(snapshot.path / "files").as_posix()
                        for p in (snapshot.path / "files").rglob("*") if p.is_file()}
        extra = actual_names - expected_names
        if extra:
            errors.append(f"unexpected files in snapshot: {sorted(extra)[:10]}")
        return {
            "dataset_id": snapshot.dataset_id,
            "snapshot_id": snapshot.snapshot_id,
            "ok": not errors,
            "errors": errors,
            "files": checked,
            "manifest_sha256": snapshot.manifest_sha256,
        }

    def verify_all(self, *, deep: bool = True) -> dict[str, Any]:
        reports = [self.verify(snapshot, deep=deep) for snapshot in self.list_snapshots()]
        return {
            "snapshots": len(reports),
            "ok": all(report["ok"] for report in reports),
            "failures": [report for report in reports if not report["ok"]],
            "reports": reports,
        }

    # --------------------------------------------------------------- checkpoints
    def checkpoint_path(self, dataset_id: str) -> Path:
        return self.checkpoint_root / f"{dataset_id}.json"

    def read_checkpoint(self, dataset_id: str) -> dict[str, Any]:
        path = self.checkpoint_path(dataset_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def write_checkpoint(self, dataset_id: str, payload: Mapping[str, Any]) -> None:
        path = self.checkpoint_path(dataset_id)
        temporary = path.with_suffix(".tmp")
        data = dict(payload)
        data["updated_at"] = utcnow()
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    # -------------------------------------------------------------- maintenance
    def storage_report(self) -> dict[str, Any]:
        snapshots = self.list_snapshots()
        stored_files: dict[str, int] = {}
        for snapshot in snapshots:
            for entry in snapshot.files:
                stored_files[entry["sha256"]] = entry["bytes"]
        blob_bytes = sum(path.stat().st_size for path in self.blobs.rglob("*") if path.is_file())
        quarantine = [path for path in self.quarantine_root.rglob("quarantine.json")]
        return {
            "root": str(self.root),
            "snapshots": len(snapshots),
            "datasets_with_snapshots": len({s.dataset_id for s in snapshots}),
            "logical_bytes": sum(stored_files.values()),
            "deduplicated_blob_bytes": blob_bytes,
            "unique_blobs": len(stored_files),
            "quarantined_staging": len(quarantine),
            "checkpoints": len(list(self.checkpoint_root.glob("*.json"))),
        }

    def recover_staging(self) -> list[Path]:
        """Move abandoned staging directories to quarantine, never publish them."""
        moved = []
        for path in list(self.datasets.glob("*/.staging-*")):
            if path.is_dir():
                moved.append(self.quarantine(path, path.parent.name, "abandoned staging directory at recovery"))
        return moved
