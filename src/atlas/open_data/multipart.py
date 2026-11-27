"""Multipart dataset packages: deterministic parts, exact reconstruction, selective install.

The SEC financial statement archive is ~5.7 GB and cannot be one GitHub Release
asset. Two packaging modes cover that, and they answer different questions:

``bytes``
    Split the exact source file at fixed offsets. Reassembly concatenates the
    parts and must reproduce the original SHA-256 byte for byte. Use this when
    the original provider archive has to be recoverable verbatim.

``period``
    Package the members of an archive by reporting period (``2024q1``). A user
    can install one quarter without downloading the rest. Each member's bytes
    are preserved exactly and hashed individually; the zip *container* is not
    reconstructed, because compression metadata is not part of the data.

Every part is hashed, listed in one index and rejected when missing. Nothing is
written to its final location until every byte it depends on has been verified,
so an interrupted restore cannot leave a half-installed dataset behind.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .store import sha256_file

PART_LIMIT_BYTES = 1_900_000_000
CHUNK = 4 << 20
PERIOD_RE = re.compile(r"^(?P<period>\d{4}[qQ][1-4])")


class MultipartError(RuntimeError):
    pass


class MissingPartError(MultipartError):
    """One or more parts are absent. Nothing was written."""


class CorruptPartError(MultipartError):
    """A part is present but does not match its recorded size or hash."""


class InsufficientSpaceError(MultipartError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- planning
def plan_byte_parts(total_bytes: int, part_limit: int = PART_LIMIT_BYTES) -> list[dict[str, int]]:
    """Deterministic fixed-size ranges. The partition depends only on the size."""
    if part_limit <= 0:
        raise MultipartError("part limit must be positive")
    if total_bytes < 0:
        raise MultipartError("total bytes must not be negative")
    parts: list[dict[str, int]] = []
    offset = 0
    number = 1
    while offset < total_bytes:
        size = min(part_limit, total_bytes - offset)
        parts.append({"part": number, "offset": offset, "bytes": size})
        offset += size
        number += 1
    return parts


def period_of(member: str) -> str:
    match = PERIOD_RE.match(Path(member).name)
    return match.group("period").lower() if match else "unpartitioned"


def period_partitions(archive: str | Path) -> dict[str, list[str]]:
    """Group zip members by reporting period, deterministically ordered."""
    grouped: dict[str, list[str]] = {}
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            grouped.setdefault(period_of(info.filename), []).append(info.filename)
    return {period: sorted(members) for period, members in sorted(grouped.items())}


# ------------------------------------------------------------------------- byte split
def split_source(source: str | Path, out_dir: str | Path, *, dataset_id: str, snapshot_id: str,
                 part_limit: int = PART_LIMIT_BYTES, prefix: str | None = None,
                 index_name: str | None = None) -> dict[str, Any]:
    """Split one file into hashed parts plus an index. Never loads a whole part."""
    path = Path(source)
    if not path.is_file():
        raise MultipartError(f"source does not exist: {path}")
    total = path.stat().st_size
    base = prefix or f"{dataset_id}-{snapshot_id}"
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    whole = hashlib.sha256()
    parts: list[dict[str, Any]] = []
    with path.open("rb") as stream:
        for plan in plan_byte_parts(total, part_limit):
            name = f"{base}.part-{plan['part']:04d}"
            digest = hashlib.sha256()
            written = 0
            target = directory / name
            with target.open("wb") as sink:
                remaining = plan["bytes"]
                while remaining:
                    chunk = stream.read(min(CHUNK, remaining))
                    if not chunk:
                        raise MultipartError(f"source ended early at {plan['offset'] + written}")
                    sink.write(chunk)
                    digest.update(chunk)
                    whole.update(chunk)
                    written += len(chunk)
                    remaining -= len(chunk)
            if written != plan["bytes"]:
                raise MultipartError(f"part {plan['part']} wrote {written} of {plan['bytes']} bytes")
            parts.append({**plan, "name": name, "sha256": digest.hexdigest(),
                          "asset_kind": "part"})
    index = {
        "schema": "atlas.open_data.multipart.v1",
        "mode": "bytes",
        "dataset_id": dataset_id,
        "snapshot_id": snapshot_id,
        "generated_at": utcnow(),
        "part_limit_bytes": part_limit,
        "source": {"path": path.name, "bytes": total, "sha256": whole.hexdigest()},
        "parts": parts,
        "periods": [],
        "reconstruct": "concatenate parts in ascending order and verify source.sha256",
    }
    target_index = directory / (index_name or f"{dataset_id}.parts.json")
    target_index.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    index["index"] = str(target_index)
    return index


# ---------------------------------------------------------------------- period parts
class _HashingReader:
    """A bounded reader that hashes exactly the bytes handed to tarfile."""

    def __init__(self, stream, size: int) -> None:
        self._stream = stream
        self._remaining = size
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        if self._remaining <= 0:
            return b""
        want = self._remaining if size is None or size < 0 else min(size, self._remaining)
        chunk = self._stream.read(want)
        self._remaining -= len(chunk)
        self.digest.update(chunk)
        return chunk


def build_period_parts(archive: str | Path, out_dir: str | Path, *, dataset_id: str,
                       snapshot_id: str, part_limit: int = PART_LIMIT_BYTES,
                       index_name: str | None = None) -> dict[str, Any]:
    """One package per reporting period, each independently installable."""
    try:
        import zstandard as zstd
    except ImportError as exc:  # pragma: no cover - depends on the install extra
        raise MultipartError("zstandard is required to build period packages") from exc
    source = Path(archive)
    if not source.is_file():
        raise MultipartError(f"archive does not exist: {source}")
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    grouped = period_partitions(source)
    parts: list[dict[str, Any]] = []
    periods: list[dict[str, Any]] = []
    with zipfile.ZipFile(source) as bundle:
        for period, members in grouped.items():
            name = f"{dataset_id}-period-{period}.tar.zst"
            target = directory / name
            catalog: list[dict[str, Any]] = []
            with target.open("wb") as raw:
                with zstd.ZstdCompressor(level=3, threads=2).stream_writer(raw) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w|") as tar:
                        for member in members:
                            info = bundle.getinfo(member)
                            reader = _HashingReader(bundle.open(member), info.file_size)
                            header = tarfile.TarInfo(name=f"members/{Path(member).name}")
                            header.size = info.file_size
                            header.mtime = 0
                            tar.addfile(header, reader)
                            if reader._remaining:  # pragma: no cover - defensive
                                raise MultipartError(f"{member} did not stream completely")
                            catalog.append({
                                "name": Path(member).name,
                                "source_member": member,
                                "bytes": info.file_size,
                                "sha256": reader.digest.hexdigest(),
                            })
                        # The member catalogue travels inside the same package, after
                        # the members, so a restore can verify every byte without
                        # trusting an index that shipped beside it.
                        manifest = {
                            "schema": "atlas.open_data.period_part.v1",
                            "dataset_id": dataset_id,
                            "snapshot_id": snapshot_id,
                            "period": period,
                            "source": {"path": source.name,
                                       "bytes": source.stat().st_size},
                            "members": catalog,
                        }
                        payload = json.dumps(manifest, indent=2,
                                             sort_keys=True).encode()
                        trailer = tarfile.TarInfo(name="PERIOD_MANIFEST.json")
                        trailer.size = len(payload)
                        trailer.mtime = 0
                        tar.addfile(trailer, io.BytesIO(payload))
            part = {"name": name, "period": period, "bytes": target.stat().st_size,
                    "sha256": sha256_file(target), "asset_kind": "period",
                    "members": len(catalog),
                    "source_bytes": sum(item["bytes"] for item in catalog)}
            if part["bytes"] > part_limit:
                nested = split_source(target, directory, dataset_id=dataset_id,
                                      snapshot_id=snapshot_id, part_limit=part_limit,
                                      prefix=f"{dataset_id}-period-{period}",
                                      index_name=f"{dataset_id}-period-{period}.parts.json")
                target.unlink()
                part["split"] = nested
                part["bytes"] = sum(item["bytes"] for item in nested["parts"])
                part["sha256"] = nested["source"]["sha256"]
            parts.append(part)
            periods.append({"period": period, "members": len(catalog),
                            "source_bytes": part["source_bytes"], "asset": name})
    index = {
        "schema": "atlas.open_data.multipart.v1",
        "mode": "period",
        "dataset_id": dataset_id,
        "snapshot_id": snapshot_id,
        "generated_at": utcnow(),
        "part_limit_bytes": part_limit,
        "source": {"path": source.name, "bytes": source.stat().st_size,
                   "sha256": sha256_file(source)},
        "parts": parts,
        "periods": periods,
        "reconstruct": (
            "each period package restores its members exactly; the original container is "
            "recoverable only from a bytes-mode split of the source archive"
        ),
    }
    target_index = directory / (index_name or f"{dataset_id}.parts.json")
    target_index.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    index["index"] = str(target_index)
    return index


# --------------------------------------------------------------------------- checking
def load_index(index: str | Path | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(index, Mapping):
        return dict(index)
    return json.loads(Path(index).read_text(encoding="utf-8"))


def _part_files(index: Mapping[str, Any], directory: str | Path) -> list[Path]:
    base = Path(directory)
    files: list[Path] = []
    for part in index.get("parts") or []:
        if part.get("split"):
            files.extend(base / item["name"] for item in part["split"]["parts"])
        else:
            files.append(base / str(part["name"]))
    return files


def verify_parts(index: str | Path | Mapping[str, Any], directory: str | Path, *,
                 deep: bool = True) -> dict[str, Any]:
    """Report missing, truncated and corrupt parts without writing anything."""
    payload = load_index(index)
    base = Path(directory)
    missing: list[str] = []
    corrupt: list[str] = []
    checked: list[dict[str, Any]] = []
    for part in payload.get("parts") or []:
        if part.get("split"):
            nested = part["split"]
            for sub in nested["parts"]:
                path = base / sub["name"]
                if not path.exists():
                    missing.append(sub["name"])
                    continue
                if path.stat().st_size != sub["bytes"]:
                    corrupt.append(f"{sub['name']}: size")
                    continue
                if deep and sha256_file(path) != sub["sha256"]:
                    corrupt.append(f"{sub['name']}: sha256")
                    continue
                checked.append({"name": sub["name"], "bytes": sub["bytes"], "ok": True})
            continue
        path = base / str(part["name"])
        if not path.exists():
            missing.append(str(part["name"]))
            continue
        size = path.stat().st_size
        if size != part["bytes"]:
            corrupt.append(f"{part['name']}: {size} != {part['bytes']} bytes")
            continue
        if deep and sha256_file(path) != part["sha256"]:
            corrupt.append(f"{part['name']}: sha256")
            continue
        checked.append({"name": part["name"], "bytes": size, "ok": True})
    return {
        "schema": "atlas.open_data.multipart_verify.v1",
        "dataset_id": payload.get("dataset_id"),
        "snapshot_id": payload.get("snapshot_id"),
        "parts_expected": len(_part_files(payload, base)),
        "parts_checked": len(checked),
        "missing": missing,
        "corrupt": corrupt,
        "ok": not missing and not corrupt,
        "required_bytes": sum(item["bytes"] for item in checked),
    }


def disk_estimate(index: str | Path | Mapping[str, Any], directory: str | Path, *,
                  periods: Sequence[str] | None = None,
                  staging: str | Path | None = None) -> dict[str, Any]:
    """Bytes that must be on disk before a restore starts."""
    payload = load_index(index)
    base = Path(directory)
    if payload.get("mode") == "period":
        wanted = {period.lower() for period in periods} if periods else None
        required = sum(
            part["bytes"] for part in payload.get("parts") or []
            if wanted is None or str(part.get("period", "")).lower() in wanted
        )
        extracted = sum(
            part.get("source_bytes", 0) for part in payload.get("parts") or []
            if wanted is None or str(part.get("period", "")).lower() in wanted
        )
    else:
        required = sum(part["bytes"] for part in payload.get("parts") or [])
        extracted = required
    target = Path(staging or base)
    free = shutil.disk_usage(target).free
    # A restore writes the extracted bytes first and publishes them afterwards.
    needed = extracted + max(0, required - extracted)
    return {
        "required_bytes": needed,
        "download_bytes": required,
        "extracted_bytes": extracted,
        "free_bytes": free,
        "sufficient": free >= needed,
        "target": str(target),
    }


# ------------------------------------------------------------------------- restoring
def materialize_part(part: Mapping[str, Any], directory: str | Path,
                     workdir: str | Path) -> Path:
    """Return the part's own file, rebuilding a nested split into ``workdir`` first.

    A period package larger than the asset limit is split again. The release index
    records the nested split, and the installer downloads only the sub-parts; the
    container itself exists only after they are verified and reassembled here, so a
    truncated or missing sub-part can never be mistaken for a valid package.
    """
    base = Path(directory)
    if not part.get("split"):
        return base / str(part["name"])
    nested = dict(part["split"])
    target = Path(workdir) / str(part["name"])
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = str((nested.get("source") or {}).get("sha256") or part.get("sha256") or "")
    if target.exists() and expected and sha256_file(target) == expected:
        return target
    target.unlink(missing_ok=True)
    reconstruct(nested, base, target)
    return target


def reconstruct(index: str | Path | Mapping[str, Any], directory: str | Path,
                destination: str | Path, *, verify: bool = True) -> dict[str, Any]:
    """Rebuild the exact original file from byte-mode parts.

    Missing or corrupt parts are rejected before a single byte is written. The
    output is staged next to the destination and renamed only after its SHA-256
    matches the recorded whole-file digest, so an interrupted run cannot publish
    a truncated archive.
    """
    payload = load_index(index)
    if payload.get("mode") != "bytes":
        raise MultipartError("reconstruct requires a bytes-mode multipart index")
    report = verify_parts(payload, directory, deep=True)
    if report["missing"]:
        raise MissingPartError(f"missing parts: {report['missing']}")
    if report["corrupt"]:
        raise CorruptPartError(f"corrupt parts: {report['corrupt']}")
    target = Path(destination)
    expected = str((payload.get("source") or {}).get("sha256"))
    if target.exists():
        if target.stat().st_size == (payload["source"]["bytes"]) and sha256_file(target) == expected:
            return {"destination": str(target), "status": "already_present",
                    "bytes": target.stat().st_size, "sha256": expected}
        raise MultipartError(f"destination exists with different bytes: {target}")
    space = disk_estimate(payload, directory, staging=target.parent)
    if not space["sufficient"]:
        raise InsufficientSpaceError(
            f"need {space['required_bytes']} bytes, {space['free_bytes']} free at {space['target']}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.partial-{uuid.uuid4().hex[:8]}"
    digest = hashlib.sha256()
    written = 0
    try:
        with staging.open("wb") as sink:
            for part in sorted(payload.get("parts") or [], key=lambda item: item["part"]):
                source = materialize_part(part, directory, staging.parent)
                with source.open("rb") as stream:
                    while chunk := stream.read(CHUNK):
                        sink.write(chunk)
                        digest.update(chunk)
                        written += len(chunk)
        actual = digest.hexdigest()
        if verify and actual != expected:
            raise CorruptPartError(f"reconstructed sha256 {actual} != {expected}")
        os.replace(staging, target)
    except BaseException:
        if staging.exists():
            staging.unlink()
        raise
    return {"destination": str(target), "status": "reconstructed", "bytes": written,
            "sha256": expected, "parts": len(payload.get("parts") or [])}


def _extract_period_package(package: Path, staging: Path) -> dict[str, Any]:
    """Extract one period package, verifying every member as it streams."""
    import zstandard as zstd

    written: list[dict[str, Any]] = []
    manifest: dict[str, Any] | None = None
    with package.open("rb") as raw:
        with zstd.ZstdDecompressor().stream_reader(raw) as decompressed:
            with tarfile.open(fileobj=decompressed, mode="r|") as tar:
                for member in tar:
                    if not member.isfile():
                        continue
                    name = Path(member.name).name
                    if member.name.startswith("members/"):
                        source = tar.extractfile(member)
                        if source is None:
                            raise MultipartError(f"cannot read {member.name}")
                        digest = hashlib.sha256()
                        target = staging / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with target.open("wb") as sink:
                            while chunk := source.read(CHUNK):
                                sink.write(chunk)
                                digest.update(chunk)
                        written.append({"name": name, "bytes": target.stat().st_size,
                                        "sha256": digest.hexdigest()})
                    elif name == "PERIOD_MANIFEST.json":
                        source = tar.extractfile(member)
                        manifest = json.loads(source.read().decode("utf-8")) if source else None
    if manifest is None:
        raise MultipartError(f"period package {package.name} has no member catalogue")
    expected = {item["name"]: item for item in manifest.get("members") or []}
    for item in written:
        reference = expected.get(item["name"])
        if reference is None:
            raise MultipartError(f"unexpected member {item['name']} in {package.name}")
        if item["bytes"] != reference["bytes"] or item["sha256"] != reference["sha256"]:
            raise CorruptPartError(f"member {item['name']} does not match {package.name}'s catalogue")
    missing = sorted(set(expected) - {item["name"] for item in written})
    if missing:
        raise MultipartError(f"{package.name} is missing members: {missing}")
    return {"members": written, "period": manifest.get("period"),
            "snapshot_id": manifest.get("snapshot_id")}


def restore_periods(index: str | Path | Mapping[str, Any], directory: str | Path,
                    out_dir: str | Path, *, periods: Sequence[str] | None = None) -> dict[str, Any]:
    """Install selected periods only, verifying before publishing each file."""
    payload = load_index(index)
    if payload.get("mode") != "period":
        raise MultipartError("restore_periods requires a period-mode multipart index")
    wanted = {str(period).lower() for period in periods} if periods else None
    known = {str(part.get("period", "")).lower() for part in payload.get("parts") or []}
    unknown = sorted((wanted or set()) - known)
    if unknown:
        raise MultipartError(f"unknown periods {unknown}; available: {sorted(known)}")
    selected = [part for part in payload.get("parts") or []
                if wanted is None or str(part.get("period", "")).lower() in wanted]
    def _available(part: Mapping[str, Any]) -> bool:
        nested = part.get("split") or {}
        if nested.get("parts"):
            return all((Path(directory) / sub["name"]).exists()
                       for sub in nested["parts"])
        return (Path(directory) / str(part["name"])).exists()

    missing = [part["name"] for part in selected if not _available(part)]
    if missing:
        raise MissingPartError(f"missing period packages: {missing}")
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    staging = target / f".atlas-restore-{uuid.uuid4().hex[:8]}"
    staging.mkdir()
    restored: list[dict[str, Any]] = []
    try:
        for part in selected:
            package = materialize_part(part, directory, staging)
            actual = sha256_file(package)
            if actual != part["sha256"]:
                raise CorruptPartError(f"{part['name']} sha256 {actual} != {part['sha256']}")
            extracted = _extract_period_package(package, staging)
            installed = []
            for item in extracted["members"]:
                final = target / item["name"]
                if final.exists() and sha256_file(final) == item["sha256"]:
                    installed.append({"name": item["name"], "status": "already_present"})
                    continue
                os.replace(staging / item["name"], final)
                installed.append({"name": item["name"], "status": "installed",
                                  "bytes": item["bytes"]})
            restored.append({"period": extracted["period"], "asset": part["name"],
                             "snapshot_id": extracted["snapshot_id"], "files": installed})
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {
        "schema": "atlas.open_data.period_restore.v1",
        "dataset_id": payload.get("dataset_id"),
        "snapshot_id": payload.get("snapshot_id"),
        "periods": len(restored),
        "files_installed": sum(1 for item in restored for f in item["files"]
                               if f["status"] == "installed"),
        "files_already_present": sum(1 for item in restored for f in item["files"]
                                     if f["status"] == "already_present"),
        "items": restored,
        "output": str(target),
    }


def describe(index: str | Path | Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compact part listing for CLI tables."""
    payload = load_index(index)
    if payload.get("mode") == "period":
        return [{"asset": part["name"], "bytes": part["bytes"], "sha256": part["sha256"],
                 "period": part.get("period"), "members": part.get("members")}
                for part in payload.get("parts") or []]
    return [{"asset": part["name"], "bytes": part["bytes"], "sha256": part["sha256"],
             "offset": part.get("offset")} for part in payload.get("parts") or []]
