"""Content-addressed archives for source evidence.

Atlas can only claim independent verification of a historical result when it retains the
source bytes that produced the processed observation. This store is deliberately modest:
it links exact bytes to a source/resource, records rights and retention, and never
pretends a processed metric is a source archive.

Rights are not inferred from possession. ``restricted`` archives can be retained locally
but are never automatically redistributed by an export.
"""

from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from typing import Any

from ..core.errors import ValidationError
from ..core.temporal import iso, iso_date, utcnow
from ..storage.db import Database


def _bytes(content: str | bytes, media_type: str) -> bytes:
    if isinstance(content, str):
        return content.encode("utf-8")
    if isinstance(content, bytes):
        return content
    raise ValidationError("archive content must be text or bytes")
MAX_BYTES = 2 * 1024 * 1024


class SourceArchiveStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def archive(
        self,
        *,
        source_id: str,
        resource_id: str,
        content: str | bytes,
        media_type: str = "application/octet-stream",
        published_at: str | None = None,
        retrieved_at: str | None = None,
        rights: str | None = None,
        retention_policy: str = "local_only",
        schema_version: str | None = None,
        parser_version: str | None = None,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        source = self.db.query_one(
            "SELECT source_id, redistribution FROM source WHERE source_id = ?", (source_id,)
        )
        if source is None:
            raise ValidationError("unknown source for archive", source_id=source_id)
        if not isinstance(resource_id, str) or not resource_id.strip():
            raise ValidationError("archive resource_id is required")
        if not isinstance(media_type, str) or not media_type.strip():
            raise ValidationError("archive media_type is required")
        if not isinstance(retention_policy, str) or not retention_policy.strip():
            raise ValidationError("archive retention_policy is required")
        payload = _bytes(content, media_type)
        if not payload:
            raise ValidationError("archive content is empty")
        if len(payload) > MAX_BYTES:
            raise ValidationError("archive content exceeds the local limit", limit=MAX_BYTES,
                                  received=len(payload))
        digest = hashlib.sha256(payload).hexdigest()
        existing = self.db.query_one(
            "SELECT archive_id FROM source_archive WHERE sha256 = ?", (digest,)
        )
        archive_id = existing["archive_id"] if existing else f"ARC-{uuid.uuid4().hex[:16]}"
        now = iso(utcnow())
        if existing is None:
            self.db.execute(
                "INSERT INTO source_archive (archive_id, source_id, resource_id, sha256, content, "
                "media_type, retrieved_at, published_at, rights, retention_policy, schema_version, "
                "parser_version, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (archive_id, source_id, resource_id.strip(), digest, payload, media_type.strip(),
                 iso(retrieved_at) if retrieved_at else now,
                 iso(published_at) if published_at else None,
                 rights or source["redistribution"] or "restricted", retention_policy.strip(),
                 schema_version, parser_version, now),
            )
        linked = 0
        for evidence_id in sorted(set(evidence_ids or [])):
            if self.db.query_one("SELECT 1 FROM evidence WHERE evidence_id = ?", (evidence_id,)) is None:
                raise ValidationError("archive links unknown evidence", evidence_id=evidence_id)
            self.db.execute(
                "INSERT OR IGNORE INTO source_archive_link (archive_id, evidence_id) VALUES (?,?)",
                (archive_id, evidence_id),
            )
            linked += 1
        result = self.get(archive_id)
        result["linked_evidence"] = linked
        return result

    def get(self, archive_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM source_archive WHERE archive_id = ?", (archive_id,))
        if row is None:
            raise ValidationError("unknown source archive", archive_id=archive_id)
        links = self.db.query(
            "SELECT evidence_id FROM source_archive_link WHERE archive_id = ? ORDER BY evidence_id",
            (archive_id,),
        )
        return {
            "archive_id": row["archive_id"],
            "source_id": row["source_id"],
            "resource_id": row["resource_id"],
            "sha256": row["sha256"],
            "media_type": row["media_type"],
            "byte_size": len(row["content"]),
            "retrieved_at": row["retrieved_at"],
            "published_at": row["published_at"],
            "rights": row["rights"],
            "retention_policy": row["retention_policy"],
            "schema_version": row["schema_version"],
            "parser_version": row["parser_version"],
            "created_at": row["created_at"],
            "evidence_ids": [item["evidence_id"] for item in links],
            "content_available": True,
        }

    def content(self, archive_id: str) -> bytes:
        row = self.db.query_one("SELECT content, sha256 FROM source_archive WHERE archive_id = ?",
                                (archive_id,))
        if row is None:
            raise ValidationError("unknown source archive", archive_id=archive_id)
        payload = bytes(row["content"])
        if hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise ValidationError("source archive integrity check failed", archive_id=archive_id)
        return payload

    def status_for_sources(self, source_ids: list[str]) -> dict[str, Any]:
        rows = self.db.query(
            "SELECT source_id, COUNT(*) AS archives, MAX(sha256) AS latest_sha256 "
            "FROM source_archive GROUP BY source_id"
        ) if not source_ids else self.db.query(
            f"SELECT source_id, COUNT(*) AS archives, MAX(sha256) AS latest_sha256 "
            f"FROM source_archive WHERE source_id IN ({','.join('?' for _ in source_ids)}) "
            "GROUP BY source_id",
            source_ids,
        )
        by_source = {row["source_id"]: {"archives": int(row["archives"]),
                                         "latest_sha256": row["latest_sha256"]}
                     for row in rows}
        return {
            "source_ids": sorted(set(source_ids)),
            "archived_sources": sorted(by_source),
            "unarchived_sources": sorted(set(source_ids) - set(by_source)),
            "by_source": by_source,
            "status": "archived" if source_ids and not (set(source_ids) - set(by_source))
            else "partial" if by_source else "external_provider_only",
        }

    def status_for_evidence(self, evidence_ids: list[str]) -> dict[str, Any]:
        if not evidence_ids:
            return {"evidence_ids": [], "archived": [], "status": "no_evidence"}
        marks = ",".join("?" for _ in evidence_ids)
        rows = self.db.query(
            f"SELECT DISTINCT sal.evidence_id, sa.archive_id, sa.sha256, sa.rights "
            f"FROM source_archive_link sal JOIN source_archive sa ON sa.archive_id = sal.archive_id "
            f"WHERE sal.evidence_id IN ({marks}) ORDER BY sal.evidence_id, sa.archive_id",
            evidence_ids,
        )
        by_evidence: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_evidence.setdefault(row["evidence_id"], []).append(dict(row))
        return {
            "evidence_ids": evidence_ids,
            "archived": sorted(by_evidence),
            "unarchived": sorted(set(evidence_ids) - set(by_evidence)),
            "by_evidence": by_evidence,
            "status": "archived" if len(by_evidence) == len(set(evidence_ids))
            else "partial" if by_evidence else "not_archived",
        }


__all__ = ["MAX_BYTES", "SourceArchiveStore"]
