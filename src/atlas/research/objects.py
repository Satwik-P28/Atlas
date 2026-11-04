"""Versioned Universal Research Object contracts.

A research object is a *declaration*, not an execution. It describes a dataset, model,
experiment, strategy or application precisely enough to review and reproduce, and it
cites the evidence it depends on. Atlas validates the document, stores it immutably
(content hash + version), and links every cited evidence id. It never runs code from a
document, never accepts SQL/expressions, and never creates evidence.

The contract is versioned by ``schema_version``. Adding a field is a new schema version;
the validator rejects unknown top-level keys so a typo cannot silently change meaning.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Any, Sequence

from ..core.errors import ValidationError
from ..core.temporal import iso, parse_iso, utcnow
from ..dependencies import DependencyIndex
from ..storage.db import Database

SCHEMA_VERSION = "atlas.research_object.v1"
KINDS = ("dataset", "financial_metric", "model", "experiment", "strategy", "application")
STATUSES = ("draft", "validated", "deprecated")
REQUIRED_FIELDS = (
    "schema_version",
    "kind",
    "name",
    "version",
    "status",
    "description",
    "as_of",
    "mode",
    "evidence_ids",
    "spec",
)
OPTIONAL_FIELDS = ("source_ids", "object_ids", "assumptions", "limitations", "owner")
ALLOWED_FIELDS = set(REQUIRED_FIELDS) | set(OPTIONAL_FIELDS)
SPEC_FIELDS = {
    "dataset": ("universe", "fields", "frequency", "adjustment"),
    "financial_metric": ("formula", "period", "unit", "inputs"),
    "model": ("inputs", "outputs", "method", "assumptions", "validation"),
    "experiment": ("hypothesis", "method", "metrics"),
    "strategy": ("signal", "universe", "rebalance", "constraints"),
    "application": ("purpose", "views"),
}
FORBIDDEN_KEYS = {"code", "sql", "python", "javascript", "executable", "script", "lambda"}
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def canonical(document: dict[str, Any]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(document).encode("utf-8")).hexdigest()


def _walk_for_code(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ValidationError(
                    "research objects may not contain executable code", path=f"{path}.{key}"
                )
            _walk_for_code(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_for_code(child, f"{path}[{index}]")


def validate_document(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ValidationError("research object document must be an object")
    unknown = set(document) - ALLOWED_FIELDS
    if unknown:
        raise ValidationError(
            "unknown research object fields", fields=sorted(unknown), schema=SCHEMA_VERSION
        )
    missing = [field for field in REQUIRED_FIELDS if field not in document]
    if missing:
        raise ValidationError("research object is missing required fields", fields=missing)
    if document["schema_version"] != SCHEMA_VERSION:
        raise ValidationError(
            "unsupported research object schema",
            found=document["schema_version"],
            supported=[SCHEMA_VERSION],
        )
    if document["kind"] not in KINDS:
        raise ValidationError("unknown research object kind", kind=document["kind"], supported=list(KINDS))
    if document["status"] not in STATUSES:
        raise ValidationError("unknown research object status", status=document["status"], supported=list(STATUSES))
    if not isinstance(document["name"], str) or not document["name"].strip():
        raise ValidationError("research object name must be non-empty")
    if not SEMVER.match(str(document["version"])):
        raise ValidationError("research object version must be semver", version=document["version"])
    if not str(document["description"]).strip():
        raise ValidationError("research object description must be non-empty")
    try:
        parse_iso(document["as_of"])
    except Exception as exc:  # noqa: BLE001 - temporal errors are validation errors here
        raise ValidationError("as_of must be an ISO timestamp", value=document["as_of"]) from exc
    if document["mode"] not in {"public_available", "atlas_ingested"}:
        raise ValidationError("mode must be public_available or atlas_ingested", mode=document["mode"])
    for field in ("evidence_ids", "source_ids", "object_ids"):
        value = document.get(field, [])
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise ValidationError(f"{field} must be a list of ids", field=field)
    if document["kind"] != "application" and not document["evidence_ids"]:
        raise ValidationError(
            "research objects must cite at least one evidence id; applications may instead cite object_ids",
            kind=document["kind"],
        )
    spec = document.get("spec")
    if not isinstance(spec, dict):
        raise ValidationError("spec must be an object")
    missing_spec = [field for field in SPEC_FIELDS[document["kind"]] if field not in spec]
    if missing_spec:
        raise ValidationError(
            "research object spec is incomplete", kind=document["kind"], fields=missing_spec
        )
    _walk_for_code(document)
    return document


class ResearchObjectStore:
    def __init__(self, db: Database):
        self.db = db

    def create(self, document: dict[str, Any], *, owner_id: str = "local") -> dict[str, Any]:
        validate_document(document)
        evidence_ids = list(dict.fromkeys(document["evidence_ids"]))
        object_ids = list(dict.fromkeys(document.get("object_ids", [])))
        source_ids = list(dict.fromkeys(document.get("source_ids", [])))
        if evidence_ids:
            marks = ",".join("?" for _ in evidence_ids)
            found = {
                row["evidence_id"]
                for row in self.db.query(
                    f"SELECT evidence_id FROM evidence WHERE evidence_id IN ({marks})", evidence_ids
                )
            }
            missing = [item for item in evidence_ids if item not in found]
            if missing:
                raise ValidationError("research object cites unknown evidence", evidence_ids=missing)
        if object_ids:
            marks = ",".join("?" for _ in object_ids)
            found = {
                row["object_id"]
                for row in self.db.query(
                    f"SELECT object_id FROM research_object WHERE object_id IN ({marks})", object_ids
                )
            }
            missing = [item for item in object_ids if item not in found]
            if missing:
                raise ValidationError("research object cites unknown objects", object_ids=missing)
        if source_ids:
            marks = ",".join("?" for _ in source_ids)
            found = {
                row["source_id"]
                for row in self.db.query(
                    f"SELECT source_id FROM source WHERE source_id IN ({marks})", source_ids
                )
            }
            missing = [item for item in source_ids if item not in found]
            if missing:
                raise ValidationError("research object cites unknown sources", source_ids=missing)
        existing = self.db.query_one(
            "SELECT object_id FROM research_object WHERE owner_id = ? AND kind = ? AND name = ? AND version = ?",
            (owner_id, document["kind"], document["name"], document["version"]),
        )
        if existing:
            raise ValidationError(
                "this research object version already exists; create a new version instead",
                object_id=existing["object_id"],
            )
        now = iso(utcnow())
        object_id = f"URO-{document['kind'][:3].upper()}-{uuid.uuid4().hex[:12]}"
        digest = content_hash(document)
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO research_object (object_id, owner_id, kind, name, version, status, "
                "schema_version, content_hash, document_json, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    object_id,
                    owner_id,
                    document["kind"],
                    document["name"],
                    document["version"],
                    document["status"],
                    document["schema_version"],
                    digest,
                    canonical(document),
                    now,
                    now,
                ),
            )
            for evidence_id in evidence_ids:
                self.db.execute(
                    "INSERT INTO research_object_evidence (object_id, evidence_id, role) VALUES (?,?,?)",
                    (object_id, evidence_id, "input"),
                )
        return self.get(object_id)

    def get(self, object_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM research_object WHERE object_id = ?", (object_id,))
        if row is None:
            raise ValidationError("unknown research object", object_id=object_id)
        document = json.loads(row["document_json"])
        evidence = [
            dict(item)
            for item in self.db.query(
                "SELECT e.evidence_id, e.concept, e.period_end, e.revision_kind, e.availability_time, "
                "e.value_numeric, e.value_text, e.unit, e.supersedes "
                "FROM research_object_evidence roe JOIN evidence e ON e.evidence_id = roe.evidence_id "
                "WHERE roe.object_id = ? ORDER BY e.availability_time, e.evidence_id",
                (object_id,),
            )
        ]
        index = DependencyIndex(self.db)
        dependents = []
        for item in evidence:
            for computation in index.dependents(item["evidence_id"]):
                dependents.append(
                    {"evidence_id": item["evidence_id"], "computation_id": computation.computation_id,
                     "rule_id": computation.rule_id, "output_evidence_id": computation.output_evidence_id}
                )
        return {
            "object_id": row["object_id"],
            "kind": row["kind"],
            "name": row["name"],
            "version": row["version"],
            "status": row["status"],
            "schema_version": row["schema_version"],
            "content_hash": row["content_hash"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "document": document,
            "evidence": evidence,
            "dependent_computations": dependents,
        }

    def list(
        self, *, kind: str | None = None, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        if kind is not None and kind not in KINDS:
            raise ValidationError("unknown research object kind", kind=kind, supported=list(KINDS))
        if status is not None and status not in STATUSES:
            raise ValidationError("unknown research object status", status=status, supported=list(STATUSES))
        clauses, params = [], []
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        rows = self.db.query(
            "SELECT object_id, kind, name, version, status, schema_version, content_hash, created_at, updated_at "
            f"FROM research_object{where} ORDER BY created_at DESC, object_id LIMIT ?",
            params,
        )
        return [dict(row) for row in rows]

    def fork(self, object_id: str, *, name: str, version: str) -> dict[str, Any]:
        """Create a new immutable version; the source object is never modified."""
        source = self.get(object_id)
        document = copy.deepcopy(source["document"])
        document["name"] = name
        document["version"] = version
        document["status"] = "draft"
        spec = document.get("spec")
        if isinstance(spec, dict):
            spec["forked_from"] = object_id
        return self.create(document)

    def compare(self, left_id: str, right_id: str) -> dict[str, Any]:
        left, right = self.get(left_id), self.get(right_id)
        changes: list[dict[str, Any]] = []

        def walk(a: Any, b: Any, path: str) -> None:
            if isinstance(a, dict) and isinstance(b, dict):
                for key in sorted(set(a) | set(b)):
                    walk(a.get(key), b.get(key), f"{path}.{key}" if path else key)
            elif isinstance(a, list) and isinstance(b, list):
                if a != b:
                    changes.append({"path": path, "left": a, "right": b})
            elif a != b:
                changes.append({"path": path, "left": a, "right": b})

        walk(left["document"], right["document"], "")
        return {
            "left": {"object_id": left_id, "name": left["name"], "version": left["version"],
                     "content_hash": left["content_hash"]},
            "right": {"object_id": right_id, "name": right["name"], "version": right["version"],
                      "content_hash": right["content_hash"]},
            "equal": left["content_hash"] == right["content_hash"],
            "changes": changes,
            "schema": SCHEMA_VERSION,
        }

    def export_manifest(self, object_id: str) -> dict[str, Any]:
        stored = self.get(object_id)
        document = stored["document"]
        from ..fec.compiler import COMPILER_VERSION
        from ..fec.operators import operator_versions

        run = None
        run_id = (document.get("spec") or {}).get("run_id")
        if isinstance(run_id, str) and run_id:
            row = self.db.query_one(
                "SELECT run_id, model_name, model_version, fingerprint, as_of, mode, "
                "inputs_json, result_json, trace_json, status, duration_ms, created_at "
                "FROM model_run WHERE run_id = ?",
                (run_id,),
            )
            if row:
                result = json.loads(row["result_json"])
                run = {
                    "run_id": row["run_id"],
                    "model_name": row["model_name"],
                    "model_version": row["model_version"],
                    "fingerprint": row["fingerprint"],
                    "as_of": row["as_of"],
                    "mode": row["mode"],
                    "status": row["status"],
                    "duration_ms": row["duration_ms"],
                    "created_at": row["created_at"],
                    "inputs": json.loads(row["inputs_json"]),
                    "outputs": result.get("outputs"),
                    "trace": json.loads(row["trace_json"]),
                }
        dependencies = []
        for dependency in document.get("object_ids", []):
            row = self.db.query_one(
                "SELECT object_id, name, version, content_hash FROM research_object WHERE object_id = ?",
                (dependency,),
            )
            if row:
                dependencies.append(dict(row))
        return {
            "schema": "atlas.reproducibility.v1",
            "exported_at": iso(utcnow()),
            "object": {
                "object_id": stored["object_id"], "kind": stored["kind"],
                "name": stored["name"], "version": stored["version"],
                "status": stored["status"], "content_hash": stored["content_hash"],
                "schema_version": stored["schema_version"],
            },
            "document": document,
            "evidence": stored["evidence"],
            "dependency_objects": dependencies,
            "run": run,
            "compiler_version": COMPILER_VERSION,
            "operator_versions": operator_versions(),
            "reproduction": {
                "command": f"atlas model export {stored['object_id']}",
                "note": "Archive the document and cited evidence snapshots before relying on future reproduction.",
            },
        }

    def evidence_impact(self, evidence_id: str) -> dict[str, Any]:
        rows = self.db.query(
            "SELECT ro.object_id, ro.kind, ro.name, ro.version, ro.status "
            "FROM research_object ro JOIN research_object_evidence roe ON roe.object_id = ro.object_id "
            "WHERE roe.evidence_id = ? ORDER BY ro.name, ro.version",
            (evidence_id,),
        )
        return {
            "evidence_id": evidence_id,
            "research_objects": [dict(row) for row in rows],
            "computations": [
                {
                    "computation_id": item.computation_id,
                    "rule_id": item.rule_id,
                    "output_evidence_id": item.output_evidence_id,
                }
                for item in DependencyIndex(self.db).dependents(evidence_id)
            ],
        }
