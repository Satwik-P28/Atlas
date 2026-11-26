"""Versioned, deterministic application package contracts.

The package is a ZIP with a canonical manifest, a declarative application document and
approved data/model artifacts. ZIP metadata is fixed so building the same content twice
produces the same bytes. A package hash proves integrity only; without a verified external
signature it does not establish publisher identity.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import zipfile
import zlib
from pathlib import Path
from typing import Any, Iterable

from ..core.errors import ValidationError
from ..fec.compiler import COMPILER_VERSION
from ..fec.operators import REGISTRY

PACKAGE_SCHEMA = "atlas.application_package.v1"
APPLICATION_SCHEMA = "atlas.application.v1"
PACK_SCHEMA = "atlas.domain_pack.v1"
SOURCE_SCHEMA = "atlas.application_source.v1"
RUNTIME_VERSION = "0.3.0"
PACKAGE_TOOL = "atlas.app.package.v1"

MAX_FILES = 64
MAX_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
MAX_PACKAGE_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_MANIFEST_BYTES = 512 * 1024
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{2,96}$")
SAFE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
ALLOWED_SUFFIXES = {".json", ".csv", ".md", ".txt"}
FORBIDDEN_KEYS = {
    "code", "sql", "python", "javascript", "executable", "script", "lambda",
    "shell", "command", "entrypoint_module", "import_hook",
}
RUNTIMES = {
    "fec_model": "atlas.fec.model.v1",
    "economic_weather_demand": "atlas.economic.weather_demand.v1",
    # A deterministic research bundle whose analysis is recomputed from the packaged
    # snapshot and model assumptions on replay. Used for equity methods that are not
    # expressed as an FEC operator graph (bank residual income, insurer earnings).
    "report_bundle": "atlas.report_bundle.v1",
}
CAPABILITIES = {
    "read_approved_snapshot",
    "register_models",
    "execute_fec_operator",
    "render_declarative_ui",
    "write_application_state",
}
SENSITIVE_CAPABILITIES = {
    "filesystem", "network", "credentials", "execute_code", "spawn_process",
    "read_all_datasets", "write_other_users",
}
REPRODUCIBILITY_LEVELS = {
    "fully_reproducible",
    "computationally_reproducible",
    "externally_dependent",
    "inspect_only",
    "unsupported",
}
REDISTRIBUTION_ALLOWED = {"permitted", "public_domain"}
VIEW_TYPES = {
    "evidence", "graph", "table", "chart", "geographic", "report", "scenario",
    "uncertainty", "experiment_history", "monitoring", "limitations",
}
SOURCE_ACTIONS = (
    "ingest",
    "local_storage",
    "analysis",
    "model_training",
    "derived_outputs",
    "packaging",
    "export",
    "sharing",
    "hosting",
    "redistribution",
)


class PackageValidationError(ValidationError):
    code = "package_validation_error"


class PackageIntegrityError(PackageValidationError):
    code = "package_integrity_error"


class MissingDependencyError(PackageValidationError):
    code = "missing_dependency"


class RightsViolation(PackageValidationError):
    code = "rights_violation"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def pretty(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, default=str) + "\n").encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(value))
    if not match:
        raise PackageValidationError("invalid semantic version", version=value)
    return tuple(int(item) for item in match.groups())  # type: ignore[return-value]


def compatibility_errors(compatibility: dict[str, Any]) -> list[dict[str, Any]]:
    current = _version_tuple(RUNTIME_VERSION)
    minimum = compatibility.get("minimum", RUNTIME_VERSION)
    maximum = compatibility.get("maximum_exclusive")
    try:
        minimum_t = _version_tuple(str(minimum))
        maximum_t = _version_tuple(str(maximum)) if maximum else None
    except PackageValidationError:
        return [{"code": "invalid_compatibility", "minimum": minimum, "maximum": maximum}]
    errors = []
    if current < minimum_t:
        errors.append({"code": "atlas_too_old", "required": str(minimum), "current": RUNTIME_VERSION})
    if maximum_t is not None and current >= maximum_t:
        errors.append({"code": "atlas_too_new", "required_max_exclusive": str(maximum),
                       "current": RUNTIME_VERSION})
    return errors


def _walk_for_code(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise PackageValidationError("executable content is not allowed in declarative packages",
                                             path=f"{path}.{key}")
            _walk_for_code(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_for_code(child, f"{path}[{index}]")


def validate_relative_path(path: str) -> str:
    if not isinstance(path, str) or not SAFE_PATH.match(path):
        raise PackageValidationError("package path is unsafe", path=path)
    if "\\" in path or path.startswith("/") or "//" in path or ":" in path:
        raise PackageValidationError("package path must be a relative POSIX path", path=path)
    components = path.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise PackageValidationError("package path traversal is forbidden", path=path)
    if Path(path).suffix.lower() not in ALLOWED_SUFFIXES:
        raise PackageValidationError("package file type is not declarative", path=path,
                                     allowed=sorted(ALLOWED_SUFFIXES))
    if path == "manifest.json":
        raise PackageValidationError("manifest.json is reserved", path=path)
    return path


def validate_application(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise PackageValidationError("application document must be an object")
    required = (
        "schema", "application_id", "name", "version", "publisher", "description",
        "compatibility", "runtime", "dependencies", "inputs", "outputs", "views",
        "sources", "capabilities", "resources", "license", "limitations", "created_at",
    )
    missing = [key for key in required if key not in document]
    if missing:
        raise PackageValidationError("application metadata is incomplete", fields=missing)
    if document["schema"] != APPLICATION_SCHEMA:
        raise PackageValidationError("unsupported application schema", found=document["schema"],
                                     supported=[APPLICATION_SCHEMA])
    if not IDENTIFIER.match(str(document["application_id"])):
        raise PackageValidationError("application_id is invalid", application_id=document["application_id"])
    if not SEMVER.match(str(document["version"])):
        raise PackageValidationError("application version must be semantic", version=document["version"])
    if not str(document["name"]).strip() or not str(document["description"]).strip():
        raise PackageValidationError("application name and description are required")
    publisher = document["publisher"]
    if isinstance(publisher, str):
        publisher = {"id": publisher}
    if not isinstance(publisher, dict) or not str(publisher.get("id", "")).strip():
        raise PackageValidationError("publisher identity is required")
    document["publisher"] = {**publisher, "id": str(publisher["id"])}
    if not isinstance(document["compatibility"], dict):
        raise PackageValidationError("compatibility must be an object")
    runtime = document["runtime"]
    if not isinstance(runtime, dict) or runtime.get("kind") not in RUNTIMES:
        raise PackageValidationError("unsupported application runtime", runtime=runtime,
                                     supported=sorted(RUNTIMES))
    if runtime.get("model_runtime") != RUNTIMES[runtime["kind"]]:
        raise PackageValidationError("runtime and model_runtime do not match",
                                     runtime=runtime.get("kind"), model_runtime=runtime.get("model_runtime"))
    dependencies = document["dependencies"]
    if not isinstance(dependencies, dict):
        raise PackageValidationError("dependencies must be an object")
    if not isinstance(dependencies.get("compiler", COMPILER_VERSION), str):
        raise PackageValidationError("compiler dependency must be a string")
    if not isinstance(dependencies.get("operators", []), list):
        raise PackageValidationError("operator dependencies must be a list")
    for item in dependencies.get("operators", []):
        if not isinstance(item, dict) or not item.get("name") or not item.get("version"):
            raise PackageValidationError("operator dependencies need name and version", item=item)
    inputs = document["inputs"]
    outputs = document["outputs"]
    if not isinstance(inputs, list) or not isinstance(outputs, list):
        raise PackageValidationError("inputs and outputs must be lists")
    for item in inputs:
        if not isinstance(item, dict) or not item.get("key") or "type" not in item:
            raise PackageValidationError("input declarations need key and type", item=item)
    for item in outputs:
        if not isinstance(item, dict) or not item.get("key"):
            raise PackageValidationError("output declarations need a key", item=item)
    views = document["views"]
    if not isinstance(views, list) or not views:
        raise PackageValidationError("at least one declarative view is required")
    for view in views:
        if not isinstance(view, dict) or view.get("type") not in VIEW_TYPES or not view.get("id"):
            raise PackageValidationError("view is not declarative", view=view)
    if not isinstance(document["sources"], list):
        raise PackageValidationError("sources must be a list")
    for source in document["sources"]:
        if not isinstance(source, dict) or not source.get("source_id"):
            raise PackageValidationError("source metadata needs source_id")
        if not source.get("license") or not source.get("redistribution"):
            raise PackageValidationError("source rights metadata is incomplete", source=source)
    capabilities = document["capabilities"]
    if not isinstance(capabilities, list):
        raise PackageValidationError("capabilities must be a list")
    unknown = set(capabilities) - CAPABILITIES
    if unknown & SENSITIVE_CAPABILITIES or unknown:
        raise PackageValidationError("requested capability is not supported",
                                     capabilities=sorted(unknown), supported=sorted(CAPABILITIES))
    resources = document["resources"]
    if not isinstance(resources, dict):
        raise PackageValidationError("resources must be an object")
    package_limit = resources.get("max_package_bytes", MAX_PACKAGE_BYTES)
    if not isinstance(package_limit, int) or package_limit < 1 or package_limit > MAX_PACKAGE_BYTES:
        raise PackageValidationError("resource limit is out of range", max_package_bytes=package_limit)
    if not isinstance(document["limitations"], list) or not document["limitations"]:
        raise PackageValidationError("an application must publish its known limitations")
    if not str(document["license"]).strip():
        raise PackageValidationError("license is required")
    _walk_for_code(document)
    return document


def dependency_diagnostics(application: dict[str, Any]) -> list[dict[str, Any]]:
    errors = compatibility_errors(application.get("compatibility", {}))
    dependencies = application.get("dependencies", {})
    compiler = dependencies.get("compiler", COMPILER_VERSION)
    if compiler != COMPILER_VERSION:
        errors.append({
            "code": "compiler_version_mismatch", "required": compiler,
            "available": COMPILER_VERSION,
            "message": "the package requires a different Financial-Economic Compiler version",
        })
    runtime = application.get("runtime", {}).get("kind")
    if runtime not in RUNTIMES:
        errors.append({"code": "missing_runtime", "runtime": runtime})
    # Operator resolution is owned by :mod:`atlas.fec.compatibility`; the package
    # diagnostics map its verdict onto the codes saved applications already carry.
    operator_versions_declared = {
        str(item.get("name")): str(item.get("version"))
        for item in dependencies.get("operators", [])
    }
    for name, expected in operator_versions_declared.items():
        operator = REGISTRY.get(name)
        if operator is None:
            errors.append({"code": "missing_operator", "operator": name, "required": expected})
        elif str(operator.version) != expected:
            errors.append({
                "code": "operator_version_conflict", "operator": name,
                "required": expected, "available": str(operator.version),
            })
    return errors


def _assess_reproducibility(application: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    if dependency_diagnostics(application):
        return {"level": "inspect_only",
                "reasons": ["required runtime/compiler/operator dependencies are not satisfied"]}
    snapshot_roles = {"approved_source_snapshot", "raw_source_snapshot", "model_artifact"}
    snapshots = [record for record in records if record["role"] in snapshot_roles]
    raw = any(record["role"] == "raw_source_snapshot" for record in records)
    if application["runtime"]["kind"] == "economic_weather_demand":
        return {
            "level": "computationally_reproducible",
            "reasons": [
                "canonical processed public panel is included",
                "raw EIA-930 and NOAA source payloads are not archived in this package",
            ],
        }
    if raw:
        return {"level": "fully_reproducible",
                "reasons": ["raw approved source bytes and execution dependencies are included"]}
    if snapshots:
        return {"level": "computationally_reproducible",
                "reasons": ["canonical inputs are included; original source bytes are not"]}
    return {"level": "fully_reproducible",
            "reasons": ["the declarative FEC model has no external dataset dependency"]}


def _file_record(path: str, payload: bytes, *, role: str, rights: str,
                 source_ids: list[str], media_type: str) -> dict[str, Any]:
    validate_relative_path(path)
    if len(payload) > MAX_FILE_BYTES:
        raise PackageValidationError("package file exceeds the size limit", path=path,
                                     limit=MAX_FILE_BYTES)
    return {
        "path": path, "sha256": sha256_bytes(payload), "bytes": len(payload),
        "media_type": media_type, "role": role, "rights": rights,
        "source_ids": sorted(set(source_ids)),
    }


def _source_rights_summary(application: dict[str, Any]) -> dict[str, Any]:
    from .rights import DataRightsEngine

    decisions = DataRightsEngine.decisions_for_metadata(application.get("sources", []))
    allowed = all(
        item["actions"]["packaging"]["allowed"]
        and item["actions"]["export"]["allowed"]
        and item["actions"]["redistribution"]["allowed"]
        for item in decisions
    )
    return {
        "schema": "atlas.application.rights.v1",
        "packaging_allowed": allowed,
        "redistribution_allowed": allowed,
        "policy": "Fail closed: only public-domain or explicitly redistribution-permitted sources may be packaged.",
        "decisions": decisions,
    }


def build_package(
    application: dict[str, Any],
    files: dict[str, bytes],
    *,
    file_metadata: Iterable[dict[str, Any]] | None = None,
    built_at: str | None = None,
    source_revision: str | None = None,
    reproducibility: str | None = None,
) -> bytes:
    """Build a deterministic .atlas package from declarative content."""
    validate_application(application)
    diagnostics = dependency_diagnostics(application)
    if diagnostics:
        raise MissingDependencyError("application dependencies are not satisfied", diagnostics=diagnostics)
    if "application.json" not in files:
        files = {**files, "application.json": pretty(application)}
    else:
        embedded = json.loads(files["application.json"].decode("utf-8"))
        if embedded != application:
            raise PackageValidationError("embedded application.json differs from the application document")

    supplied = {item["path"]: item for item in (file_metadata or [])}
    records: list[dict[str, Any]] = []
    for path in sorted(files):
        payload = files[path]
        if not isinstance(payload, bytes):
            raise PackageValidationError("package file payload must be bytes", path=path)
        meta = supplied.get(path, {})
        role = str(meta.get("role", "application_metadata"))
        rights = str(meta.get("rights", "public_domain"))
        source_ids = list(meta.get("source_ids", []))
        media_type = str(meta.get("media_type") or (
            "application/json" if path.endswith(".json")
            else "text/csv" if path.endswith(".csv")
            else "text/markdown" if path.endswith(".md")
            else "text/plain"
        ))
        if role in {"approved_source_snapshot", "raw_source_snapshot", "model_artifact", "analysis_result",
                    "scenario_result"} and not source_ids:
            source_ids = [item["source_id"] for item in application["sources"]]
        records.append(_file_record(path, payload, role=role, rights=rights,
                                    source_ids=source_ids, media_type=media_type))
    if len(records) > MAX_FILES:
        raise PackageValidationError("package contains too many files", limit=MAX_FILES,
                                     received=len(records))
    if sum(item["bytes"] for item in records) > MAX_UNCOMPRESSED_BYTES:
        raise PackageValidationError("package uncompressed size exceeds the limit", limit=MAX_UNCOMPRESSED_BYTES)
    if not any(item["path"] == "application.json" for item in records):
        raise PackageValidationError("application.json is required")

    rights = _source_rights_summary(application)
    if not rights["packaging_allowed"]:
        raise RightsViolation("one or more sources do not permit packaging or redistribution",
                              decisions=rights["decisions"])
    if reproducibility is None:
        reproducibility = _assess_reproducibility(application, records)["level"]
    if reproducibility not in REPRODUCIBILITY_LEVELS:
        raise PackageValidationError("unknown reproducibility level", level=reproducibility)
    limitations = list(application.get("limitations", []))
    reproducibility_detail = _assess_reproducibility(application, records)
    reproducibility_detail["level"] = reproducibility
    reproducibility_detail["limitations"] = limitations
    built = built_at or application.get("created_at") or "1970-01-01T00:00:00Z"
    content_root = digest({
        "format": PACKAGE_SCHEMA,
        "application": application,
        "application_sha256": sha256_bytes(pretty(application)),
        "files": records,
        "sources": application["sources"],
        "rights": rights,
        "dependencies": application["dependencies"],
        "capabilities": application["capabilities"],
        "reproducibility": reproducibility_detail,
    })
    manifest = {
        "schema": PACKAGE_SCHEMA,
        "format_version": 1,
        "package_id": f"APKG-{content_root[:20]}",
        "content_root": content_root,
        "created_at": built,
        "application": application,
        "application_sha256": sha256_bytes(pretty(application)),
        "sources": application["sources"],
        "rights": rights,
        "dependencies": application["dependencies"],
        "capabilities": application["capabilities"],
        "reproducibility": reproducibility_detail,
        "files": records,
        "signature": None,
        "signature_status": "unsigned",
        "trust": {
            "publisher_verified": False,
            "note": "Integrity is checked. Publisher identity is a declaration until a reviewed signature verifier is installed.",
        },
        "build": {
            "tool": PACKAGE_TOOL,
            "atlas_version": RUNTIME_VERSION,
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "source_revision": source_revision or os.environ.get("ATLAS_SOURCE_REVISION") or "unknown",
            "deterministic_zip": True,
        },
    }
    manifest_payload = pretty(manifest)
    if len(manifest_payload) > MAX_MANIFEST_BYTES:
        raise PackageValidationError("manifest exceeds the size limit", limit=MAX_MANIFEST_BYTES)
    entries = {"manifest.json": manifest_payload, **{item["path"]: files[item["path"]] for item in records}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, entries[name])
    payload = buffer.getvalue()
    if len(payload) > MAX_PACKAGE_BYTES:
        raise PackageValidationError("package compressed size exceeds the limit", limit=MAX_PACKAGE_BYTES,
                                     received=len(payload))
    return payload


def validate_manifest(manifest: dict[str, Any], files: dict[str, bytes]) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("schema") != PACKAGE_SCHEMA:
        raise PackageValidationError("unsupported package manifest schema",
                                     found=(manifest or {}).get("schema") if isinstance(manifest, dict) else None)
    required = ("format_version", "package_id", "content_root", "created_at", "application",
                "application_sha256", "sources", "rights", "dependencies", "capabilities",
                "reproducibility", "files", "signature", "signature_status", "trust", "build")
    missing = [key for key in required if key not in manifest]
    if missing:
        raise PackageValidationError("package manifest is incomplete", fields=missing)
    if manifest["format_version"] != 1:
        raise PackageValidationError("unsupported package format", format_version=manifest["format_version"])
    if manifest.get("signature") is not None:
        raise PackageValidationError("signature verification is not implemented; signed packages are not accepted")
    if manifest.get("signature_status") != "unsigned":
        raise PackageValidationError("unsupported signature status", status=manifest.get("signature_status"))
    application = validate_application(manifest["application"])
    if manifest["application_sha256"] != sha256_bytes(pretty(application)):
        raise PackageIntegrityError("application digest mismatch")
    records = manifest["files"]
    if not isinstance(records, list) or len(records) > MAX_FILES:
        raise PackageValidationError("invalid package file list")
    declared = {}
    for item in records:
        if not isinstance(item, dict):
            raise PackageValidationError("package file record must be an object")
        path = validate_relative_path(item.get("path"))
        if path in declared:
            raise PackageValidationError("duplicate package path", path=path)
        payload = files.get(path)
        if payload is None:
            raise PackageIntegrityError("declared package file is missing", path=path)
        if len(payload) != int(item.get("bytes", -1)):
            raise PackageIntegrityError("package file size mismatch", path=path)
        if sha256_bytes(payload) != item.get("sha256"):
            raise PackageIntegrityError("package file hash mismatch", path=path)
        if item.get("role") not in {
            "application_metadata", "approved_source_snapshot", "raw_source_snapshot",
            "model_artifact", "analysis_result", "scenario_result", "rights_manifest",
            "validation_vector", "documentation",
        }:
            raise PackageValidationError("unknown package file role", path=path, role=item.get("role"))
        declared[path] = item
    if set(files) != set(declared) | {"application.json"}:
        extras = sorted(set(files) - set(declared) - {"application.json"})
        if extras:
            raise PackageIntegrityError("undeclared package files", paths=extras)
    if "application.json" not in files:
        raise PackageIntegrityError("application.json is missing")
    embedded = json.loads(files["application.json"].decode("utf-8"))
    if embedded != application:
        raise PackageIntegrityError("application.json does not match the manifest")
    if "application.json" not in declared:
        raise PackageIntegrityError("application.json is not declared in the manifest")
    rights = manifest["rights"]
    if not isinstance(rights, dict) or rights.get("packaging_allowed") is not True:
        raise RightsViolation("package rights do not permit packaging")
    for record in records:
        if record["role"] in {"approved_source_snapshot", "raw_source_snapshot"}:
            if record.get("rights") not in REDISTRIBUTION_ALLOWED:
                raise RightsViolation("source snapshot is not redistributable", path=record["path"],
                                      rights=record.get("rights"))
    if manifest["reproducibility"].get("level") not in REPRODUCIBILITY_LEVELS:
        raise PackageValidationError("unknown reproducibility level")
    content_root = digest({
        "format": PACKAGE_SCHEMA,
        "application": application,
        "application_sha256": sha256_bytes(pretty(application)),
        "files": records,
        "sources": application["sources"],
        "rights": rights,
        "dependencies": application["dependencies"],
        "capabilities": application["capabilities"],
        "reproducibility": manifest["reproducibility"],
    })
    if content_root != manifest["content_root"]:
        raise PackageIntegrityError("package content root mismatch")
    if manifest["package_id"] != f"APKG-{content_root[:20]}":
        raise PackageIntegrityError("package identity does not match its content")
    _walk_for_code(manifest)
    return manifest


def read_package(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise PackageValidationError("package payload is empty")
    if len(payload) > MAX_PACKAGE_BYTES:
        raise PackageValidationError("package exceeds the size limit", limit=MAX_PACKAGE_BYTES,
                                     received=len(payload))
    try:
        with zipfile.ZipFile(io.BytesIO(bytes(payload))) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES + 1:
                raise PackageValidationError("package contains too many entries", limit=MAX_FILES + 1)
            names: set[str] = set()
            total = 0
            files: dict[str, bytes] = {}
            for info in infos:
                if info.is_dir():
                    raise PackageValidationError("directory entries are not allowed", path=info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise PackageValidationError("symlink entries are forbidden", path=info.filename)
                if info.flag_bits & 0x1:
                    raise PackageValidationError("encrypted package entries are unsupported", path=info.filename)
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    # Refusing unsupported methods explicitly avoids relying on zipfile to
                    # raise `NotImplementedError` while reading a member.
                    raise PackageValidationError("unsupported ZIP compression method",
                                                 path=info.filename, method=info.compress_type)
                if info.filename != "manifest.json":
                    validate_relative_path(info.filename)
                if "\x00" in info.filename:
                    raise PackageValidationError("package path contains a NUL byte",
                                                 path=repr(info.filename))
                if info.filename in names:
                    raise PackageIntegrityError("duplicate ZIP entry", path=info.filename)
                names.add(info.filename)
                if int(info.file_size) < 0:
                    raise PackageIntegrityError("invalid ZIP entry size", path=info.filename)
                total += int(info.file_size)
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise PackageValidationError("uncompressed package size exceeds the limit",
                                                 limit=MAX_UNCOMPRESSED_BYTES)
                data = archive.read(info)
                if len(data) != int(info.file_size):
                    raise PackageIntegrityError("short ZIP entry", path=info.filename)
                files[info.filename] = data
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError,
            OSError, KeyError) as exc:
        # A malformed archive must be reported as an integrity failure, never surface as
        # an unhandled exception. `RuntimeError` covers an encrypted member reached without
        # the header flag, and `zlib.error`/`EOFError` cover a corrupt deflate stream or a
        # body truncated after its central directory.
        raise PackageIntegrityError("package is not a valid ZIP archive") from exc
    if "manifest.json" not in files:
        raise PackageIntegrityError("manifest.json is missing")
    if len(files["manifest.json"]) > MAX_MANIFEST_BYTES:
        raise PackageValidationError("manifest exceeds the size limit")
    try:
        manifest = json.loads(files.pop("manifest.json").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageValidationError("manifest is not valid UTF-8 JSON") from exc
    manifest = validate_manifest(manifest, files)
    return {
        "manifest": manifest,
        "files": files,
        "package_sha256": sha256_bytes(bytes(payload)),
        "manifest_sha256": digest(manifest),
        "size_bytes": len(payload),
    }


def unpack_to_directory(payload: bytes, destination: str | Path) -> list[str]:
    """Inspect helper used by tests and CLI; writes only after validation."""
    loaded = read_package(payload)
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    written = []
    for path, data in sorted(loaded["files"].items()):
        safe = root / path
        if root.resolve() not in safe.resolve().parents:
            raise PackageValidationError("path escapes destination", path=path)
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_bytes(data)
        written.append(path)
    return written
