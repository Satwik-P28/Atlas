"""Declarative domain packs.

A pack contributes metadata, model templates, data-adapter declarations and packaged
applications. It cannot execute code or alter canonical operator semantics. Installation
is transactional and fails closed; uninstall never deletes user research.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.errors import UnknownEntity, ValidationError
from ..core.temporal import iso, utcnow
from ..storage.db import Database
from .contracts import (
    CAPABILITIES,
    PACK_SCHEMA,
    RUNTIME_VERSION,
    canonical,
    digest,
    read_package,
    validate_application,
)
from .service import ApplicationService


def _pack_path(value: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise ValidationError("pack application path must be relative", path=value)
    if ".." in Path(value).parts or ":" in value:
        raise ValidationError("pack application path traversal is forbidden", path=value)
    if Path(value).suffix.lower() != ".atlas":
        raise ValidationError("domain packs may only reference .atlas packages", path=value)
    return value


def validate_pack(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict) or document.get("schema") != PACK_SCHEMA:
        raise ValidationError("unsupported domain-pack schema", found=(document or {}).get("schema"))
    required = (
        "schema", "pack_id", "name", "version", "publisher", "license", "compatibility",
        "kind", "dependencies", "capabilities", "sources", "resources", "object_types",
        "validation", "test_vectors", "limitations", "applications", "created_at",
    )
    missing = [key for key in required if key not in document]
    if missing:
        raise ValidationError("domain pack metadata is incomplete", fields=missing)
    if document["kind"] != "declarative":
        raise ValidationError("only declarative domain packs are supported", kind=document["kind"])
    if not str(document["pack_id"]).strip() or not str(document["name"]).strip():
        raise ValidationError("pack identity and name are required")
    if not isinstance(document["publisher"], dict) or not document["publisher"].get("id"):
        raise ValidationError("pack publisher identity is required")
    caps = document.get("capabilities", [])
    if not isinstance(caps, list) or set(caps) - CAPABILITIES:
        raise ValidationError("domain pack requests an unsupported capability",
                              capabilities=sorted(set(caps) - CAPABILITIES))
    apps = document.get("applications", [])
    if not isinstance(apps, list):
        raise ValidationError("pack applications must be a list")
    for item in apps:
        if not isinstance(item, dict):
            raise ValidationError("each pack application must be an object")
        _pack_path(item.get("path"))
        if item.get("sha256") and len(str(item["sha256"])) != 64:
            raise ValidationError("pack application hash must be SHA-256", path=item["path"])
    if not isinstance(document.get("test_vectors"), list) or not document["test_vectors"]:
        raise ValidationError("a domain pack must declare validation test vectors")
    if not isinstance(document.get("limitations"), list) or not document["limitations"]:
        raise ValidationError("a domain pack must publish limitations")
    if document.get("compatibility", {}).get("minimum", RUNTIME_VERSION) > RUNTIME_VERSION:
        raise ValidationError("pack requires a newer Atlas runtime",
                              required=document["compatibility"]["minimum"],
                              current=RUNTIME_VERSION)
    # The pack is data-only; reject executable keys anywhere in its manifest.
    forbidden = {"code", "python", "javascript", "executable", "shell", "command", "entrypoint"}
    def walk(value: Any, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in forbidden:
                    raise ValidationError("domain pack may not contain executable content",
                                          path=f"{path}.{key}")
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
    walk(document)
    return document


class DomainPackService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.apps = ApplicationService(db)

    def load(self, path: str | Path) -> tuple[dict[str, Any], Path]:
        source = Path(path)
        document = json.loads(source.read_text(encoding="utf-8"))
        return validate_pack(document), source.parent

    def install(self, document: dict[str, Any] | str | Path, *,
                base_dir: str | Path | None = None,
                package_bytes: dict[str, bytes] | None = None) -> dict[str, Any]:
        if isinstance(document, (str, Path)):
            document, base_dir = self.load(document)
        else:
            document = validate_pack(document)
        root = Path(base_dir) if base_dir else Path.cwd()
        manifest_digest = digest(document)
        existing = self.db.query_one(
            "SELECT pack_id, version, publisher_id, manifest_digest FROM domain_pack_installation "
            "WHERE pack_id = ? AND version = ? AND publisher_id = ?",
            (document["pack_id"], document["version"], document["publisher"]["id"]),
        )
        if existing:
            if existing["manifest_digest"] == manifest_digest:
                return self.get(document["pack_id"], document["version"]) | {"already_installed": True}
            raise ValidationError("domain-pack version is already installed with different content",
                                  pack_id=document["pack_id"], version=document["version"])
        # Verify all embedded packages before writing anything.
        loaded_packages: list[tuple[dict[str, Any], bytes]] = []
        for item in document["applications"]:
            relative = _pack_path(item["path"])
            path = root / relative
            if package_bytes is not None:
                payload = package_bytes.get(relative)
                if payload is None:
                    raise ValidationError("pack application bytes are missing", path=relative)
            else:
                try:
                    payload = path.read_bytes()
                except OSError as exc:
                    raise ValidationError("pack application package is missing", path=str(path)) from exc
            if item.get("sha256") and __import__("hashlib").sha256(payload).hexdigest() != item["sha256"]:
                raise ValidationError("pack application package hash mismatch", path=item["path"])
            read_package(payload)
            loaded_packages.append((item, payload))
        now = iso(utcnow())
        installed = []
        with self.db.transaction():
            for item, payload in loaded_packages:
                installed.append(self.apps.install(payload))
            self.db.execute(
                "INSERT INTO domain_pack_installation (pack_id, version, publisher_id, manifest_json, "
                "manifest_digest, applications_json, installed_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (document["pack_id"], document["version"], document["publisher"]["id"],
                 json.dumps(document, sort_keys=True), manifest_digest,
                 json.dumps([item["install_id"] for item in installed], sort_keys=True),
                 now, now),
            )
        return self.get(document["pack_id"], document["version"])

    def get(self, pack_id: str, version: str) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT * FROM domain_pack_installation WHERE pack_id = ? AND version = ?",
            (pack_id, version),
        )
        if row is None:
            raise UnknownEntity("unknown domain pack", pack_id=pack_id, version=version)
        manifest = json.loads(row["manifest_json"])
        application_ids = json.loads(row["applications_json"])
        return {
            "schema": "atlas.domain_pack.installation.v1",
            "pack_id": row["pack_id"],
            "version": row["version"],
            "publisher_id": row["publisher_id"],
            "manifest_digest": row["manifest_digest"],
            "applications": application_ids,
            "manifest": manifest,
            "installed_at": row["installed_at"],
            "updated_at": row["updated_at"],
            "executable_code": False,
            "note": "Declarative pack; contributions are metadata and packaged applications.",
        }

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT pack_id, version FROM domain_pack_installation ORDER BY installed_at DESC, pack_id LIMIT ?",
            (max(1, min(int(limit), 500)),),
        )
        return [self.get(row["pack_id"], row["version"]) for row in rows]

    def uninstall(self, pack_id: str, version: str) -> dict[str, Any]:
        record = self.get(pack_id, version)
        with self.db.transaction():
            self.db.execute(
                "DELETE FROM domain_pack_installation WHERE pack_id = ? AND version = ?",
                (pack_id, version),
            )
        return {
            "schema": "atlas.domain_pack.uninstall.v1",
            "pack_id": pack_id,
            "version": version,
            "status": "uninstalled",
            "applications_retained": record["applications"],
            "research_objects_retained": True,
            "note": "Installed applications are retained so uninstall cannot destroy unrelated research; remove them explicitly.",
        }


__all__ = ["DomainPackService", "validate_pack"]
