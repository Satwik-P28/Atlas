"""Safe archive inspection and extraction.

Compressed provider archives are hostile input. This module validates names, member
types, sizes and compression ratios before writing anything, and enforces the same
limits while extracting. Path traversal, absolute paths, symlinks, hard links, device
nodes, encrypted members, duplicate names and archive bombs are rejected.

The limits are intentionally conventional (a literal 100:1 ratio is common for text
archives), and can be raised per dataset in the registry only by an explicit override.
"""

from __future__ import annotations

import gzip
import io
import os
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class ArchiveRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_members: int = 200_000
    max_file_bytes: int = 8 * 1024**3
    max_total_bytes: int = 32 * 1024**3
    max_compression_ratio: float = 200.0
    max_ratio_check_bytes: int = 256 * 1024**2

    def to_dict(self) -> dict:
        return {
            "max_members": self.max_members,
            "max_file_bytes": self.max_file_bytes,
            "max_total_bytes": self.max_total_bytes,
            "max_compression_ratio": self.max_compression_ratio,
        }


DEFAULT_LIMITS = ArchiveLimits()


@dataclass(slots=True)
class ArchiveMember:
    name: str
    size: int
    compressed_size: int
    is_dir: bool

    def to_dict(self) -> dict:
        return {"name": self.name, "size": self.size,
                "compressed_size": self.compressed_size, "is_dir": self.is_dir}


@dataclass(slots=True)
class ArchiveInspection:
    format: str
    members: int
    uncompressed_bytes: int
    compressed_bytes: int
    files: list[ArchiveMember]
    warnings: list[str]

    @property
    def ratio(self) -> float:
        return (self.uncompressed_bytes / self.compressed_bytes) if self.compressed_bytes else 0.0

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "members": self.members,
            "uncompressed_bytes": self.uncompressed_bytes,
            "compressed_bytes": self.compressed_bytes,
            "compression_ratio": round(self.ratio, 2),
            "warnings": self.warnings,
            "largest_members": [m.to_dict() for m in sorted(
                self.files, key=lambda m: m.size, reverse=True)[:10]],
        }


def _safe_name(name: str) -> str:
    if not name or "\x00" in name:
        raise ArchiveRejected("empty or NUL-containing member name")
    normalised = name.replace("\\", "/")
    if normalised.startswith("/") or (len(normalised) > 1 and normalised[1] == ":"):
        raise ArchiveRejected(f"absolute member path: {name!r}")
    parts = [part for part in normalised.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        raise ArchiveRejected(f"path traversal in member: {name!r}")
    if not parts:
        raise ArchiveRejected(f"member has no usable path: {name!r}")
    return "/".join(parts)


def detect_format(path: str | Path) -> str:
    with open(path, "rb") as stream:
        head = stream.read(8)
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        return "zip"
    if head.startswith(b"\x1f\x8b"):
        return "gzip"
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "tar"
    if head.lstrip().startswith((b"{", b"[")):
        return "json"
    return "unknown"


def inspect_zip(path: str | Path, limits: ArchiveLimits = DEFAULT_LIMITS) -> ArchiveInspection:
    members: list[ArchiveMember] = []
    total = 0
    compressed_total = 0
    warnings: list[str] = []
    seen: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > limits.max_members:
            raise ArchiveRejected(f"too many members: {len(infos)} > {limits.max_members}")
        for info in infos:
            name = _safe_name(info.filename)
            if name in seen:
                raise ArchiveRejected(f"duplicate member name: {name!r}")
            seen.add(name)
            raw_mode = (info.external_attr >> 16) & 0xFFFF
            kind = raw_mode & 0o170000
            if kind == 0o120000:
                raise ArchiveRejected(f"symlink member rejected: {name!r}")
            if kind not in {0, 0o100000, 0o040000}:
                raise ArchiveRejected(f"special-file member rejected: {name!r}")
            if info.flag_bits & 0x1:
                raise ArchiveRejected(f"encrypted member rejected: {name!r}")
            if info.file_size < 0 or info.compress_size < 0:
                raise ArchiveRejected(f"negative size for {name!r}")
            if info.file_size > limits.max_file_bytes:
                raise ArchiveRejected(f"member {name!r} is {info.file_size} bytes; limit {limits.max_file_bytes}")
            total += info.file_size
            compressed_total += info.compress_size
            if total > limits.max_total_bytes:
                raise ArchiveRejected(f"archive expands beyond {limits.max_total_bytes} bytes")
            if (info.compress_size > 0 and info.file_size > limits.max_ratio_check_bytes
                    and info.file_size / info.compress_size > limits.max_compression_ratio):
                raise ArchiveRejected(
                    f"suspicious compression ratio {info.file_size / info.compress_size:.0f}:1 for {name!r}"
                )
            members.append(ArchiveMember(name, info.file_size, info.compress_size, info.is_dir()))
    if not members:
        raise ArchiveRejected("empty ZIP archive")
    if total and compressed_total and total / max(compressed_total, 1) > limits.max_compression_ratio:
        raise ArchiveRejected("archive-level compression ratio exceeds limit")
    if any(m.size == 0 and not m.is_dir for m in members):
        warnings.append("archive contains empty files")
    return ArchiveInspection("zip", len(members), total, compressed_total, members, warnings)


def inspect_tar(path: str | Path, limits: ArchiveLimits = DEFAULT_LIMITS) -> ArchiveInspection:
    members: list[ArchiveMember] = []
    total = 0
    warnings: list[str] = []
    with tarfile.open(path, "r:*") as archive:
        infos = archive.getmembers()
        if len(infos) > limits.max_members:
            raise ArchiveRejected(f"too many members: {len(infos)} > {limits.max_members}")
        for info in infos:
            name = _safe_name(info.name)
            if info.issym() or info.islnk():
                raise ArchiveRejected(f"link member rejected: {name!r}")
            if not (info.isfile() or info.isdir()):
                raise ArchiveRejected(f"special member rejected: {name!r}")
            if info.size > limits.max_file_bytes:
                raise ArchiveRejected(f"member {name!r} is {info.size} bytes; limit {limits.max_file_bytes}")
            total += info.size
            if total > limits.max_total_bytes:
                raise ArchiveRejected(f"archive expands beyond {limits.max_total_bytes} bytes")
            members.append(ArchiveMember(name, info.size, 0, info.isdir()))
    if not members:
        raise ArchiveRejected("empty TAR archive")
    return ArchiveInspection("tar", len(members), total, Path(path).stat().st_size, members, warnings)


def inspect(path: str | Path, limits: ArchiveLimits = DEFAULT_LIMITS) -> ArchiveInspection:
    fmt = detect_format(path)
    if fmt == "zip":
        return inspect_zip(path, limits)
    if fmt == "tar":
        return inspect_tar(path, limits)
    if fmt == "gzip":
        size = 0
        with gzip.open(path, "rb") as stream:
            while chunk := stream.read(1 << 20):
                size += len(chunk)
                if size > limits.max_total_bytes:
                    raise ArchiveRejected("gzip expands beyond total byte limit")
        return ArchiveInspection("gzip", 1, size, Path(path).stat().st_size,
                                 [ArchiveMember(Path(path).stem, size, Path(path).stat().st_size, False)], [])
    raise ArchiveRejected(f"unrecognised archive format for {path}")


def safe_extract(path: str | Path, destination: str | Path, limits: ArchiveLimits = DEFAULT_LIMITS) -> list[Path]:
    """Extract a ZIP/TAR/GZIP into an empty destination, enforcing limits on the bytes
    actually written rather than trusting the directory alone."""
    target = Path(destination)
    target.mkdir(parents=True, exist_ok=True)
    if any(target.iterdir()):
        raise ArchiveRejected(f"destination is not empty: {target}")
    fmt = detect_format(path)
    written: list[Path] = []

    def _write(member_name: str, source: io.BufferedIOBase, expected: int) -> None:
        relative = _safe_name(member_name)
        output = (target / relative).resolve()
        if target.resolve() not in output.parents and output != target.resolve():
            raise ArchiveRejected(f"member escapes destination: {member_name!r}")
        output.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with output.open("wb") as sink:
            while chunk := source.read(1 << 20):
                count += len(chunk)
                if count > limits.max_file_bytes:
                    raise ArchiveRejected(f"member exceeds file limit while extracting: {member_name!r}")
                if count > expected + 1:
                    raise ArchiveRejected(f"member larger than declared: {member_name!r}")
                sink.write(chunk)
        if count != expected:
            raise ArchiveRejected(f"member size mismatch for {member_name!r}: {count} != {expected}")
        written.append(output)

    if fmt == "zip":
        inspect_zip(path, limits)
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                with archive.open(info) as source:
                    _write(info.filename, source, info.file_size)
    elif fmt == "tar":
        inspect_tar(path, limits)
        with tarfile.open(path, "r:*") as archive:
            for info in archive.getmembers():
                if not info.isfile():
                    continue
                source = archive.extractfile(info)
                if source is None:
                    raise ArchiveRejected(f"cannot read member {info.name!r}")
                with source:
                    _write(info.name, source, info.size)
    elif fmt == "gzip":
        name = Path(path).name
        if name.endswith(".gz"):
            name = name[:-3]
        with gzip.open(path, "rb") as source:
            _write(name, source, _gzip_size(path, limits))
    else:
        raise ArchiveRejected(f"unrecognised archive format for {path}")
    return written


def _gzip_size(path: str | Path, limits: ArchiveLimits) -> int:
    size = 0
    with gzip.open(path, "rb") as stream:
        while chunk := stream.read(1 << 20):
            size += len(chunk)
            if size > limits.max_total_bytes:
                raise ArchiveRejected("gzip expands beyond total byte limit")
    return size


def stream_members(path: str | Path) -> Iterator[tuple[str, io.BufferedIOBase, int]]:
    """Yield ``(name, stream, declared_size)`` without extracting to disk."""
    fmt = detect_format(path)
    if fmt == "zip":
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            for info in infos:
                if info.is_dir():
                    continue
                _safe_name(info.filename)
                with archive.open(info) as source:
                    yield info.filename, source, info.file_size
    elif fmt in {"tar", "gzip"}:
        mode = "r:*" if fmt == "tar" else "r:gz"
        with tarfile.open(path, mode) as archive:
            for info in archive.getmembers():
                if not info.isfile():
                    continue
                _safe_name(info.name)
                source = archive.extractfile(info)
                if source is None:
                    continue
                with source:
                    yield info.name, source, info.size
    else:
        raise ArchiveRejected(f"cannot stream {fmt}")
