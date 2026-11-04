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
KINDS = ("dataset", "model", "experiment", "strategy", "application")
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
