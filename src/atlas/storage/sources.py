"""Source registry.

Every evidence record names its source. The registry states, in machine-readable
form, what each source is and **what may be done with it**. Redistribution status is
part of the contract because Atlas must never treat a licensed or restricted feed as
freely redistributable, and because licensed vendors require explicit attribution.

Phase 1 sources:

``sec-edgar``
    U.S. SEC EDGAR (public domain filings, XBRL company facts). Fair-access policy:
    contact User-Agent, ≤10 requests/second. ``redistribution=public_domain``.
``atlas-synthetic``
    Deterministic fixtures used by tests. Never presented as observed market data.
``csv-import``
    User-supplied CSV/Parquet files. Their licence is unknown to Atlas and therefore
    recorded as ``user_responsibility``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.errors import ValidationError
from ..core.ids import source_slug
from ..core.temporal import iso, utcnow
from .db import Database

REDISTRIBUTION_PUBLIC_DOMAIN = "public_domain"
REDISTRIBUTION_RESTRICTED = "restricted"
REDISTRIBUTION_USER_RESPONSIBILITY = "user_responsibility"


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    name: str
    kind: str
    homepage: str | None
    licence: str | None
    redistribution: str
    notes: str | None


SEC_EDGAR = SourceDefinition(
    source_id="sec-edgar",
    name="U.S. SEC EDGAR",
    kind="sec_edgar",
    homepage="https://www.sec.gov/edgar/sec-api-documentation",
    licence="U.S. federal government work - public domain",
    redistribution=REDISTRIBUTION_PUBLIC_DOMAIN,
    notes=(
        "Access requires a descriptive User-Agent with contact details and at most 10 "
        "requests per second. XBRL company facts are authoritative for reported values; "
        "public availability is evidenced by filing acceptance timestamps."
    ),
)

ATLAS_SYNTHETIC = SourceDefinition(
    source_id="atlas-synthetic",
    name="Atlas deterministic fixtures",
    kind="synthetic",
    homepage=None,
    licence="Apache-2.0 (Atlas project)",
    redistribution=REDISTRIBUTION_PUBLIC_DOMAIN,
    notes="Synthetic data for tests and offline demonstrations. Not real market data.",
)

CSV_IMPORT = SourceDefinition(
    source_id="csv-import",
    name="User CSV/Parquet import",
    kind="csv_import",
    homepage=None,
    licence=None,
    redistribution=REDISTRIBUTION_USER_RESPONSIBILITY,
    notes="Licence of imported files is the user's responsibility; Atlas records only provenance.",
)

KNOWN_SOURCES: tuple[SourceDefinition, ...] = (SEC_EDGAR, ATLAS_SYNTHETIC, CSV_IMPORT)


class SourceRegistry:
    """Persisted registry of data sources and their usage rights."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def ensure(self, definition: SourceDefinition) -> str:
        now = iso(utcnow())
        self.db.execute(
            "INSERT INTO source (source_id, name, kind, homepage, licence, redistribution, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
            "name=excluded.name, kind=excluded.kind, homepage=excluded.homepage, licence=excluded.licence, "
            "redistribution=excluded.redistribution, notes=excluded.notes",
            (
                definition.source_id,
                definition.name,
                definition.kind,
                definition.homepage,
                definition.licence,
                definition.redistribution,
                definition.notes,
                now,
            ),
        )
        return definition.source_id

    def ensure_custom(
        self,
        name: str,
        *,
        kind: str,
        licence: str | None = None,
        redistribution: str = REDISTRIBUTION_USER_RESPONSIBILITY,
        homepage: str | None = None,
        notes: str | None = None,
        source_id: str | None = None,
    ) -> str:
        if not name.strip():
            raise ValidationError("source name is required")
        slug = source_id or source_slug(name)
        return self.ensure(
            SourceDefinition(
                source_id=slug,
                name=name,
                kind=kind,
                homepage=homepage,
                licence=licence,
                redistribution=redistribution,
                notes=notes,
            )
        )

    def get(self, source_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM source WHERE source_id = ?", (source_id,))
        return {key: row[key] for key in row.keys()} if row is not None else None

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM source ORDER BY source_id")
        return [{key: row[key] for key in row.keys()} for row in rows]

    def require(self, source_id: str) -> dict[str, Any]:
        found = self.get(source_id)
        if found is None:
            raise ValidationError("source is not registered", source_id=source_id)
        return found


def ensure_default_sources(db: Database) -> None:
    registry = SourceRegistry(db)
    for definition in KNOWN_SOURCES:
        registry.ensure(definition)


def store_raw_document(
    db: Database,
    *,
    source_id: str,
    url: str,
    body: bytes,
    media_type: str = "application/json",
    http_status: int = 200,
    retrieved_at: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> str:
    """Persist a source document and return its id.

    Bodies are stored verbatim so an evidence record always points at the exact bytes
    Atlas interpreted. Deduplication is by content hash per source.
    """
    import hashlib

    from ..core.ids import raw_document_id

    content_hash = hashlib.sha256(body).hexdigest()
    doc_id = raw_document_id(source_id, content_hash)
    db.execute(
        "INSERT INTO raw_document (doc_id, source_id, url, content_hash, media_type, http_status, byte_size, "
        "retrieved_at, etag, last_modified, body) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(source_id, content_hash) DO UPDATE SET url=excluded.url, "
        "retrieved_at=excluded.retrieved_at",
        (
            doc_id,
            source_id,
            url,
            content_hash,
            media_type,
            http_status,
            len(body),
            retrieved_at or iso(utcnow()),
            etag,
            last_modified,
            body,
        ),
    )
    return doc_id
