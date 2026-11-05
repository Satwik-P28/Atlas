"""CLI implementation for `atlas app` and `atlas app pack`."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..core.errors import ValidationError
from ..storage.db import Database
from .contracts import read_package
from .packs import DomainPackService
from .sdk import build_source, load_source, scaffold, test_source
from .service import ApplicationService


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def _load_json(path: str) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValidationError("file could not be read", path=path) from exc
    except json.JSONDecodeError as exc:
        raise ValidationError("file is not valid JSON", path=path) from exc


def run(db: Database, args: Any) -> int:
    action = getattr(args, "app_command", None)
    pack_action = getattr(args, "pack_command", None)
    if action == "init":
        _print(scaffold(args.directory, name=args.name, application_id=args.application_id,
                        version=args.version))
        return 0
    if action == "validate":
        source = _load_json(args.file)
        loaded = load_source(args.file)
        _print({"schema": "atlas.application.sdk.validate.v1", "status": "valid",
                "source_schema": source.get("schema"), "application": loaded["application"]})
        return 0
    if action == "test":
        _print(test_source(args.file))
        return 0
    if action == "build":
        _print(build_source(args.file, args.out))
        return 0
    if action == "inspect":
        loaded = read_package(Path(args.package).read_bytes())
        _print({
            "schema": "atlas.application.inspect.v1",
            "package_id": loaded["manifest"]["package_id"],
            "package_sha256": loaded["package_sha256"],
            "size_bytes": loaded["size_bytes"],
            "application": loaded["manifest"]["application"],
            "sources": loaded["manifest"]["sources"],
            "rights": loaded["manifest"]["rights"],
            "reproducibility": loaded["manifest"]["reproducibility"],
            "files": loaded["manifest"]["files"],
            "signature_status": loaded["manifest"]["signature_status"],
        })
        return 0
    if action == "verify":
        loaded = read_package(Path(args.package).read_bytes())
        _print({
            "schema": "atlas.application.verification.v1",
            "status": "verified_integrity",
            "package_id": loaded["manifest"]["package_id"],
            "package_sha256": loaded["package_sha256"],
            "files": len(loaded["manifest"]["files"]),
            "publisher_verified": False,
            "signature_status": loaded["manifest"]["signature_status"],
        })
        return 0
    if action == "install":
        _print(ApplicationService(db).install(Path(args.package).read_bytes()))
        return 0
    if action == "list" or action == "gallery":
        _print(ApplicationService(db).gallery())
        return 0
    if action == "open":
        _print(ApplicationService(db).open(args.install_id))
        return 0
    if action == "execute":
        _print(ApplicationService(db).execute(args.install_id,
                                              _load_json(args.inputs) if args.inputs else {}))
        return 0
    if action == "export":
        service = ApplicationService(db)
        if args.install_id:
            payload, filename = service.export_bytes(args.install_id)
            destination = Path(args.out or filename)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            _print({"status": "exported", "path": str(destination),
                    "package_sha256": hashlib.sha256(payload).hexdigest()})
            return 0
        if args.object_id:
            _print(service.export_object(args.object_id, args.out))
            return 0
        if args.run_id:
            _print(service.export_economic(args.run_id, args.out, scenario_id=args.scenario_id,
                                           version=args.version))
            return 0
        raise ValidationError("app export requires --install-id, --object-id or --run-id")
    if action == "fork":
        _print(ApplicationService(db).fork(args.install_id, name=args.name, version=args.version))
        return 0
    if action == "compare":
        _print(ApplicationService(db).compare(args.left, args.right))
        return 0
    if action == "uninstall":
        _print(ApplicationService(db).uninstall(args.install_id))
        return 0
    if action == "pack":
        packs = DomainPackService(db)
        if pack_action == "install":
            _print(packs.install(args.file))
            return 0
        if pack_action == "list":
            _print({"schema": "atlas.domain_pack.list.v1", "items": packs.list()})
            return 0
        if pack_action == "inspect":
            _print(packs.get(args.pack_id, args.version))
            return 0
        if pack_action == "uninstall":
            _print(packs.uninstall(args.pack_id, args.version))
            return 0
    raise ValidationError("unknown app command", command=action, pack_command=pack_action)


__all__ = ["run"]
