"""Atlas Financial Knowledge Engine (FKE).

Retrieval over primary source documents, with the Temporal Evidence Kernel's rules
intact: a document is content-addressed, every passage keeps an exact character span
into a deterministic normalised text, and every result is filtered by an explicit
information cutoff before ranking.

The engine deliberately starts with the strongest deterministic baseline — SQLite
FTS5/BM25 over section-aware units — rather than embeddings. A dense or hybrid
retriever must beat this baseline on the benchmark in
``docs/PHASE9_5_RETRIEVAL_BENCHMARK.md`` before it is allowed to become a default.

Design boundaries:

* No second evidence store. Documents and units reference ``issuer`` and ``source``
  and are exported through the existing rights classifier.
* No generated text is ever stored as a passage. Only bytes retrieved from the source,
  deterministically normalised, are indexed.
* Availability time, acceptance time, filing date, period end and ingestion time are
  five different columns; none of them may stand in for another.
"""

from __future__ import annotations

import gzip
import hashlib
import html as html_module
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urljoin
from urllib.request import Request, urlopen
from html.parser import HTMLParser
from typing import Any, Iterable

from ..core.errors import ValidationError
from ..core.temporal import iso, iso_date, utcnow
from ..storage.db import Database
from .rights import classify

ENGINE_SCHEMA = "atlas.knowledge.engine.v1"
PARSER_VERSION = "atlas.knowledge.parser.v1"
DEFAULT_SOURCE_ID = "sec-edgar"
SEC_USER_AGENT = "Atlas Quant research (research@atlas.local)"
MAX_DOCUMENT_BYTES = 24 * 1024 * 1024
POLICIES = ("public_available", "atlas_ingested")
POLICY_NOTE = (
    "public_available answers from documents whose proven public availability precedes the "
    "cutoff; atlas_ingested answers from what this database had ingested by then. They are "
    "different claims and are never interchangeable."
)
BLOCK_TAGS = {
    "p", "div", "li", "ul", "ol", "section", "article", "br", "tr", "blockquote",
    "dd", "dt", "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tfoot",
}
SKIP_TAGS = {"script", "style", "noscript", "head", "title", "meta", "link", "ix:header"}
# Void elements never emit an end tag; incrementing skip depth for them would silently
# discard the rest of the document, so they are handled separately.
VOID_TAGS = {"meta", "link", "br", "img", "hr", "input", "col", "area", "base", "source"}
HEADING_LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

_WS = re.compile(r"[ \t\r\f\v\u00a0]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_ITEM = re.compile(r"^\s*item\s+(\d{1,2}[a-c]?)\s*[.:]\s*(.{0,120})", re.IGNORECASE)
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'&./-]{0,48}")


# --------------------------------------------------------------------------- extraction
@dataclass(slots=True)
class Block:
    kind: str = "paragraph"
    heading: str | None = None
    text_parts: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    row: list[str] = field(default_factory=list)
    caption: str | None = None

    @property
    def text(self) -> str:
        return _clean(" ".join(self.text_parts))


def _clean(value: str) -> str:
    value = html_module.unescape(value)
    value = value.replace("\u00a0", " ")
    value = _WS.sub(" ", value)
    return value.strip()


class _Parser(HTMLParser):
    """Deterministic HTML → blocks. Same bytes always produce the same blocks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.sections: list[str] = []
        self.skip_depth = 0
        self.table_depth = 0
        self.heading_level = 0
        self.buffer: list[str] = []
        self.current_table: Block | None = None
        self.pending_caption: str | None = None
        self.last_heading: str | None = None

    # -- helpers
    def _flush(self, kind: str = "paragraph") -> None:
        text = _clean(" ".join(self.buffer))
        self.buffer = []
        if not text:
            return
        item = _ITEM.match(text)
        if item:
            kind = "heading"
            self.last_heading = text[:200]
        block = Block(kind=kind, heading=self.last_heading, text_parts=[text])
        if kind == "heading":
            block.heading = text[:200]
            if text[:200] not in self.sections:
                self.sections.append(text[:200])
        self.blocks.append(block)

    # -- parser API
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            if tag not in VOID_TAGS:
                self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "table":
            self.table_depth += 1
            if self.table_depth == 1:
                self._flush()
                self.current_table = Block(kind="table", heading=self.last_heading)
            return
        if self.table_depth:
            if tag == "tr":
                if self.current_table is not None:
                    self.current_table.row = []
            elif tag in {"td", "th"}:
                self.buffer = []
            return
        if tag in BLOCK_TAGS and tag not in HEADING_LEVELS and self.buffer:
            self._flush()
        if tag in HEADING_LEVELS:
            self._flush()
            self.heading_level = HEADING_LEVELS[tag]
            self.buffer = []
        elif tag == "caption":
            self.buffer = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            if tag not in VOID_TAGS:
                self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag == "table":
            self.table_depth = max(0, self.table_depth - 1)
            if self.table_depth == 0 and self.current_table is not None:
                self.current_table.caption = self.pending_caption
                self.pending_caption = None
                if self.current_table.rows:
                    self.blocks.append(self.current_table)
                self.current_table = None
            return
        if self.table_depth:
            if tag in {"td", "th"} and self.current_table is not None:
                cell = _clean(" ".join(self.buffer))
                self.buffer = []
                if cell:
                    self.current_table.row.append(cell)
                elif self.current_table.row:
                    self.current_table.row.append("")
            elif tag == "tr" and self.current_table is not None:
                if any(cell for cell in self.current_table.row):
                    self.current_table.rows.append(list(self.current_table.row))
                self.current_table.row = []
            return
        if tag in HEADING_LEVELS:
            text = _clean(" ".join(self.buffer))
            self.buffer = []
            if text:
                self.last_heading = text[:200]
                if text[:200] not in self.sections:
                    self.sections.append(text[:200])
                self.blocks.append(Block(kind="heading", heading=text[:200], text_parts=[text]))
            self.heading_level = 0
        elif tag == "caption":
            self.pending_caption = _clean(" ".join(self.buffer))
            self.buffer = []
        elif tag in BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        self.buffer.append(data)

    def close(self) -> None:  # noqa: D401 - HTMLParser API
        super().close()
        self._flush()


def _table_text(block: Block) -> str:
    lines: list[str] = []
    if block.caption:
        lines.append(f"Table: {block.caption}")
    for row in block.rows:
        lines.append(" | ".join(cell for cell in row))
    return "\n".join(lines)


def extract_units(html: str) -> list[dict[str, Any]]:
    """Deterministically split a filing into heading / paragraph / table units."""
    parser = _Parser()
    parser.feed(html)
    parser.close()
    units: list[dict[str, Any]] = []
    section = ""
    for block in parser.blocks:
        body = block.text if block.kind != "table" else _table_text(block)
        if not body or len(body) < 2:
            continue
        if block.kind == "heading":
            section = block.heading or section
        payload: dict[str, Any] = {
            "kind": block.kind,
            "section_path": section[:240] or "Document",
            "heading": block.heading,
            "body": body,
        }
        if block.kind == "table":
            payload["rows"] = block.rows
            payload["caption"] = block.caption
        units.append(payload)
    return units


def normalise_document(units: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Join units into one text and stamp exact character spans onto each unit."""
    text_parts: list[str] = []
    offset = 0
    stamped: list[dict[str, Any]] = []
    for unit in units:
        body = unit["body"]
        start = offset
        text_parts.append(body)
        offset += len(body)
        end = offset
        text_parts.append("\n\n")
        offset += 2
        stamped.append({**unit, "char_start": start, "char_end": end})
    return "".join(text_parts), stamped


# --------------------------------------------------------------------------- engine
def _tokens(query: str) -> list[str]:
    return [match.group(0) for match in _TOKEN.finditer(query)]


def _fts_query(query: str) -> str:
    tokens = _tokens(query)
    if not tokens:
        raise ValidationError("query has no indexable terms", query=query[:120])
    return " OR ".join(f'"{token}"' for token in tokens[:32])


def _iso_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return iso(value) if hasattr(value, "tzinfo") else str(value)


class KnowledgeEngine:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ ingestion
    def ingest_document(
        self,
        *,
        issuer_id: str,
        accession: str,
        form_type: str,
        html: str | bytes,
        filed_date: str,
        primary_document_url: str,
        source_id: str = DEFAULT_SOURCE_ID,
        acceptance_time: str | None = None,
        period_of_report: str | None = None,
        retrieved_at: str | None = None,
        rights: str = "public_domain",
        media_type: str = "text/html",
        amends_accession: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        payload = html.encode("utf-8") if isinstance(html, str) else html
        if not payload:
            raise ValidationError("document bytes are empty")
        if len(payload) > MAX_DOCUMENT_BYTES:
            raise ValidationError("document exceeds the ingestion limit", limit=MAX_DOCUMENT_BYTES,
                                  received=len(payload))
        issuer = self.db.query_one("SELECT issuer_id FROM issuer WHERE issuer_id = ?", (issuer_id,))
        if issuer is None:
            raise ValidationError("unknown issuer for document", issuer_id=issuer_id)
        source = self.db.query_one("SELECT redistribution FROM source WHERE source_id = ?", (source_id,))
        if source is None:
            raise ValidationError("unknown source for document", source_id=source_id)
        rights_decision = classify(rights, copyright_holder="SEC registrant public filing")
        if not rights_decision["trusted"]:
            raise ValidationError("document rights are not trustworthy",
                                  warnings=rights_decision["warnings"])
        digest = hashlib.sha256(payload).hexdigest()
        existing = self.db.query_one(
            "SELECT document_id, sha256 FROM knowledge_document WHERE accession = ?", (accession,)
        )
        if existing:
            if existing["sha256"] == digest:
                return self.document(existing["document_id"])
            raise ValidationError(
                "this accession is already ingested with different bytes; documents are immutable",
                accession=accession, existing_sha256=existing["sha256"], incoming_sha256=digest,
            )
        units = extract_units(payload.decode("utf-8", errors="replace"))
        if not units:
            raise ValidationError("document produced no extractable text", accession=accession)
        text, stamped = normalise_document(units)
        form = form_type.strip().upper()
        is_amendment = form.endswith("/A")
        precision = "exact" if acceptance_time else "date"
        availability = _iso_or_none(acceptance_time) or iso_date(filed_date)
        basis = "sec_acceptance_datetime" if acceptance_time else "sec_filing_date"
        now = iso(utcnow())
        document_id = f"DOC-{uuid.uuid4().hex[:16]}"
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO knowledge_document (document_id, issuer_id, source_id, accession, form_type, "
                "is_amendment, amends_accession, period_of_report, filed_date, acceptance_time, "
                "availability_time, availability_precision, availability_basis, primary_document_url, "
                "media_type, sha256, byte_size, rights, retention_policy, parser_version, ingested_at, "
                "section_count, unit_count, table_count, status, notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (document_id, issuer_id, source_id, accession, form, 1 if is_amendment else 0,
                 amends_accession, period_of_report, iso_date(filed_date), _iso_or_none(acceptance_time),
                 availability, precision, basis, primary_document_url, media_type, digest, len(payload),
                 rights_decision["redistribution"], "local_only", PARSER_VERSION, now,
                 len({unit["section_path"] for unit in stamped}), len(stamped),
                 sum(1 for unit in stamped if unit["kind"] == "table"), "indexed", notes),
            )
            for ordinal, unit in enumerate(stamped):
                unit_id = f"UNI-{hashlib.sha256(f'{document_id}:{ordinal}'.encode()).hexdigest()[:16]}"
                unit["unit_id"] = unit_id
                self.db.execute(
                    "INSERT INTO knowledge_unit (unit_id, document_id, ordinal, unit_kind, section_path, "
                    "heading, body, char_start, char_end, sha256) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (unit_id, document_id, ordinal, unit["kind"], unit["section_path"],
                     unit.get("heading"), unit["body"], unit["char_start"], unit["char_end"],
                     hashlib.sha256(unit["body"].encode("utf-8")).hexdigest()),
                )
                self.db.execute(
                    "INSERT INTO knowledge_fts (body, heading, section_path, unit_id, document_id) "
                    "VALUES (?,?,?,?,?)",
                    (unit["body"], unit.get("heading") or "", unit["section_path"], unit_id, document_id),
                )
                if unit["kind"] == "table":
                    rows = unit.get("rows") or []
                    periods = _periods_from_rows(rows)
                    self.db.execute(
                        "INSERT INTO knowledge_table (table_id, document_id, unit_id, section_path, caption, "
                        "periods_json, units, footnotes, rows_json, cell_locator, sha256) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (f"TAB-{hashlib.sha256(f'{document_id}:{ordinal}'.encode()).hexdigest()[:16]}",
                         document_id, unit_id, unit["section_path"], unit.get("caption"),
                         json.dumps(periods), None, _footnotes(rows), json.dumps(rows, ensure_ascii=False),
                         f"paragraph {ordinal}", hashlib.sha256(unit["body"].encode()).hexdigest()),
                    )
        stored = self.document(document_id)
        stored["text_length"] = len(text)
        return stored

    # ------------------------------------------------------------------- reading
    def document(self, document_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM knowledge_document WHERE document_id = ?", (document_id,))
        if row is None:
            raise ValidationError("unknown knowledge document", document_id=document_id)
        return self._document_payload(row)

    def document_by_accession(self, accession: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM knowledge_document WHERE accession = ?", (accession,))
        if row is None:
            raise ValidationError("unknown accession", accession=accession)
        return self._document_payload(row)

    def _document_payload(self, row: Any) -> dict[str, Any]:
        rights = classify(row["rights"])
        return {
            "document_id": row["document_id"],
            "issuer_id": row["issuer_id"],
            "accession": row["accession"],
            "form_type": row["form_type"],
            "is_amendment": bool(row["is_amendment"]),
            "amends_accession": row["amends_accession"],
            "period_of_report": row["period_of_report"],
            "filed_date": row["filed_date"],
            "acceptance_time": row["acceptance_time"],
            "availability_time": row["availability_time"],
            "availability_precision": row["availability_precision"],
            "availability_basis": row["availability_basis"],
            "primary_document_url": row["primary_document_url"],
            "source_id": row["source_id"],
            "sha256": row["sha256"],
            "byte_size": row["byte_size"],
            "parser_version": row["parser_version"],
            "ingested_at": row["ingested_at"],
            "section_count": row["section_count"],
            "unit_count": row["unit_count"],
            "table_count": row["table_count"],
            "status": row["status"],
            "notes": row["notes"],
            "rights": rights,
            "resolve_original": {
                "url": row["primary_document_url"],
                "accession": row["accession"],
                "content_sha256": row["sha256"],
                "must_reverify": True,
            },
            "timing": {
                "filed_date": row["filed_date"],
                "acceptance_time": row["acceptance_time"],
                "period_of_report": row["period_of_report"],
                "availability_time": row["availability_time"],
                "availability_precision": row["availability_precision"],
                "availability_basis": row["availability_basis"],
                "ingested_at": row["ingested_at"],
                "note": (
                    "Availability is proven from the SEC acceptance timestamp when present; a filing "
                    "date alone cannot establish intraday public availability."
                ),
            },
        }

    def unit(self, unit_id: str) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT u.*, d.issuer_id, d.accession, d.form_type, d.availability_time, "
            "d.availability_precision, d.rights, d.primary_document_url "
            "FROM knowledge_unit u JOIN knowledge_document d ON d.document_id = u.document_id "
            "WHERE u.unit_id = ?", (unit_id,),
        )
        if row is None:
            raise ValidationError("unknown passage", unit_id=unit_id)
        return {
            "unit_id": row["unit_id"],
            "document_id": row["document_id"],
            "issuer_id": row["issuer_id"],
            "accession": row["accession"],
            "form_type": row["form_type"],
            "ordinal": row["ordinal"],
            "unit_kind": row["unit_kind"],
            "section_path": row["section_path"],
            "heading": row["heading"],
            "body": row["body"],
            "char_start": row["char_start"],
            "char_end": row["char_end"],
            "sha256": row["sha256"],
            "availability_time": row["availability_time"],
            "availability_precision": row["availability_precision"],
            "rights": row["rights"],
            "resolve_original": row["primary_document_url"],
        }

    def list_documents(self, *, issuer_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses, params = ["status = 'indexed'"], []
        if issuer_id:
            clauses.append("issuer_id = ?")
            params.append(issuer_id)
        params.append(max(1, min(int(limit), 500)))
        rows = self.db.query(
            "SELECT document_id, issuer_id, accession, form_type, is_amendment, amends_accession, "
            "filed_date, acceptance_time, availability_time, availability_precision, period_of_report, "
            "unit_count, table_count, sha256, rights, primary_document_url "
            f"FROM knowledge_document WHERE {' AND '.join(clauses)} "
            "ORDER BY availability_time DESC, accession LIMIT ?", params,
        )
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ retrieval
    def search(
        self,
        query: str,
        *,
        issuer_id: str | None = None,
        cutoff: str | None = None,
        policy: str = "public_available",
        limit: int = 10,
        forms: Iterable[str] | None = None,
        section: str | None = None,
        include_amendments: bool = True,
        min_relevance: float = 0.0,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        if policy not in POLICIES:
            raise ValidationError("unknown retrieval policy", policy=policy, supported=list(POLICIES))
        match = _fts_query(query)
        clauses = ["d.status = 'indexed'"]
        params: list[Any] = [match]
        if issuer_id:
            clauses.append("d.issuer_id = ?")
            params.append(issuer_id)
        if cutoff:
            column = "d.availability_time" if policy == "public_available" else "d.ingested_at"
            clauses.append(f"{column} <= ?")
            params.append(cutoff)
        if forms:
            selected = [form.strip().upper() for form in forms if form.strip()]
            if selected:
                clauses.append(f"d.form_type IN ({','.join('?' for _ in selected)})")
                params.extend(selected)
        if not include_amendments:
            clauses.append("d.is_amendment = 0")
        if section:
            clauses.append("u.section_path LIKE ?")
            params.append(f"%{section}%")
        params.append(max(1, min(int(limit), 50)))
        sql = (
            "SELECT u.unit_id, u.document_id, u.unit_kind, u.section_path, u.heading, u.body, "
            "u.char_start, u.char_end, u.sha256 AS unit_sha256, d.issuer_id, d.accession, d.form_type, "
            "d.is_amendment, d.filed_date, d.acceptance_time, d.availability_time, "
            "d.availability_precision, d.rights, d.primary_document_url, "
            "bm25(knowledge_fts, 1.0, 4.0, 2.0) AS rank, "
            "snippet(knowledge_fts, 0, '⟦', '⟧', '…', 28) AS matched"
            "\nFROM knowledge_fts JOIN knowledge_unit u ON u.unit_id = knowledge_fts.unit_id "
            "JOIN knowledge_document d ON d.document_id = u.document_id "
            f"WHERE knowledge_fts MATCH ? AND {' AND '.join(clauses)} "
            "ORDER BY rank, d.availability_time DESC, u.ordinal LIMIT ?"
        )
        rows = self.db.query(sql, params)
        future_excluded = self._future_count(query, issuer_id, cutoff, policy)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows:
            if row["unit_sha256"] in seen:
                continue
            seen.add(row["unit_sha256"])
            relevance = round(-float(row["rank"]), 6)
            results.append({
                "unit_id": row["unit_id"],
                "document_id": row["document_id"],
                "issuer_id": row["issuer_id"],
                "accession": row["accession"],
                "form_type": row["form_type"],
                "is_amendment": bool(row["is_amendment"]),
                "section_path": row["section_path"],
                "heading": row["heading"],
                "unit_kind": row["unit_kind"],
                "excerpt": row["matched"],
                "body_sha256": row["unit_sha256"],
                "char_start": row["char_start"],
                "char_end": row["char_end"],
                "availability_time": row["availability_time"],
                "availability_precision": row["availability_precision"],
                "filed_date": row["filed_date"],
                "acceptance_time": row["acceptance_time"],
                "rights": row["rights"],
                "relevance": relevance,
                "ranking": {
                    "method": "bm25",
                    "weights": {"body": 1.0, "heading": 4.0, "section_path": 2.0},
                    "raw_score": float(row["rank"]),
                    "why": "FTS5 BM25 over the passage body with heading and section weighting",
                },
                "resolve_original": row["primary_document_url"],
                "localization": "exact-span" if row["unit_kind"] != "table" else "table-block",
            })
        absent = self._absent_terms(match)
        abstained, reason = False, None
        if not results:
            abstained = True
            reason = ("query_term_absent_from_corpus" if absent
                      else "no_passage_satisfies_query_at_cutoff")
        elif absent:
            # BM25 with OR semantics always returns something, so a query containing a
            # term that appears nowhere in the corpus would otherwise be "answered"
            # from an incidental common word. Abstain and name the absent term.
            abstained = True
            reason = "query_term_absent_from_corpus"
        elif results[0]["relevance"] < min_relevance:
            abstained = True
            reason = "best_match_below_relevance_floor"
        latency_ms = (time.perf_counter() - started) * 1000
        payload = {
            "schema": ENGINE_SCHEMA,
            "query": query,
            "plan": {
                "retriever": "sqlite-fts5-bm25",
                "policy": policy,
                "cutoff": cutoff,
                "issuer_id": issuer_id,
                "forms": sorted({form.upper() for form in (forms or [])}),
                "include_amendments": include_amendments,
                "section_filter": section,
                "limit": limit,
                "steps": ["bind-issuer", "apply-cutoff", "lexical-match", "rank", "dedupe"],
            },
            "timing": {
                "policy": policy,
                "cutoff": cutoff,
                "note": (
                    "public_available uses SEC acceptance time; atlas_ingested uses local ingestion time. "
                    "A date-precision availability cannot prove intraday historical availability."
                ),
            },
            "count": len(results),
            "results": results,
            "abstained": abstained,
            "abstention_reason": reason,
            "excluded": {"later_than_cutoff": future_excluded},
            "latency_ms": round(latency_ms, 3),
        }
        self._log_query(payload, abstained)
        return payload

    def _absent_terms(self, match: str) -> list[str]:
        """Query terms that appear in no indexed passage.

        A term absent from the corpus makes the query unanswerable from these documents,
        regardless of how many common words overlap.
        """
        terms = [part.strip('"') for part in match.split(" OR ")]
        absent: list[str] = []
        for term in terms:
            row = self.db.query_one(
                "SELECT COUNT(*) AS n FROM knowledge_fts WHERE knowledge_fts MATCH ?",
                (f'"{term}"',),
            )
            if int(row["n"]) == 0 if row else True:
                absent.append(term.lower())
        return absent

    def _future_count(self, query: str, issuer_id: str | None, cutoff: str | None,
                      policy: str) -> int:
        if not cutoff:
            return 0
        column = "d.availability_time" if policy == "public_available" else "d.ingested_at"
        clauses = [f"{column} > ?", "d.status = 'indexed'"]
        params: list[Any] = [_fts_query(query), cutoff]
        if issuer_id:
            clauses.append("d.issuer_id = ?")
            params.append(issuer_id)
        row = self.db.query_one(
            "SELECT COUNT(DISTINCT u.unit_id) AS n FROM knowledge_fts "
            "JOIN knowledge_unit u ON u.unit_id = knowledge_fts.unit_id "
            "JOIN knowledge_document d ON d.document_id = u.document_id "
            f"WHERE knowledge_fts MATCH ? AND {' AND '.join(clauses)}", params,
        )
        return int(row["n"]) if row else 0

    def _log_query(self, payload: dict[str, Any], abstained: bool) -> None:
        self.db.execute(
            "INSERT INTO knowledge_query_log (query_id, query_text, issuer_id, cutoff, policy, "
            "plan_json, result_count, abstained, latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"QRY-{uuid.uuid4().hex[:16]}", payload["query"][:400], payload["plan"]["issuer_id"],
             payload["plan"]["cutoff"], payload["plan"]["policy"],
             json.dumps(payload["plan"], sort_keys=True), payload["count"], 1 if abstained else 0,
             payload["latency_ms"], iso(utcnow())),
        )

    # -------------------------------------------------------------------- tables
    def tables(
        self, *, document_id: str, section: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        clauses, params = ["t.document_id = ?"], [document_id]
        if section:
            clauses.append("t.section_path LIKE ?")
            params.append(f"%{section}%")
        params.append(max(1, min(int(limit), 50)))
        rows = self.db.query(
            "SELECT t.*, u.char_start, u.char_end, d.accession, d.availability_time, d.rights "
            "FROM knowledge_table t JOIN knowledge_unit u ON u.unit_id = t.unit_id "
            "JOIN knowledge_document d ON d.document_id = t.document_id "
            f"WHERE {' AND '.join(clauses)} ORDER BY u.ordinal LIMIT ?", params,
        )
        return [
            {
                "table_id": row["table_id"],
                "document_id": row["document_id"],
                "unit_id": row["unit_id"],
                "section_path": row["section_path"],
                "caption": row["caption"],
                "periods": json.loads(row["periods_json"]),
                "units": row["units"],
                "footnotes": row["footnotes"],
                "rows": json.loads(row["rows_json"]),
                "cell_locator": row["cell_locator"],
                "char_start": row["char_start"],
                "char_end": row["char_end"],
                "accession": row["accession"],
                "availability_time": row["availability_time"],
                "rights": row["rights"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------ versions
    def compare(self, left_document_id: str, right_document_id: str) -> dict[str, Any]:
        left, right = self.document(left_document_id), self.document(right_document_id)
        if left["issuer_id"] != right["issuer_id"]:
            raise ValidationError("cannot compare documents from different issuers")
        left_sections = self._section_digests(left_document_id)
        right_sections = self._section_digests(right_document_id)
        added = sorted(set(right_sections) - set(left_sections))
        removed = sorted(set(left_sections) - set(right_sections))
        changed = sorted(
            name for name in set(left_sections) & set(right_sections)
            if left_sections[name]["digest"] != right_sections[name]["digest"]
        )
        return {
            "schema": "atlas.knowledge.compare.v1",
            "issuer_id": left["issuer_id"],
            "left": {"document_id": left["document_id"], "accession": left["accession"],
                     "form_type": left["form_type"], "availability_time": left["availability_time"]},
            "right": {"document_id": right["document_id"], "accession": right["accession"],
                      "form_type": right["form_type"], "availability_time": right["availability_time"]},
            "amendment_relationship": (
                "right_amends_left" if right["is_amendment"] and right["amends_accession"] == left["accession"]
                else "right_is_amendment" if right["is_amendment"] else "separate_filings"
            ),
            "added_sections": added,
            "removed_sections": removed,
            "changed_sections": changed,
            "unchanged_sections": sorted(set(left_sections) & set(right_sections) - set(changed)),
            "affected_unit_ids": sorted(
                unit_id
                for name in changed + removed
                for unit_id in left_sections[name]["unit_ids"]
            ),
            "note": (
                "Section-level comparison only. It reports where text changed, not why it changed; "
                "significance requires analyst review."
            ),
        }

    def _section_digests(self, document_id: str) -> dict[str, dict[str, Any]]:
        rows = self.db.query(
            "SELECT unit_id, section_path, body FROM knowledge_unit WHERE document_id = ? "
            "ORDER BY ordinal", (document_id,),
        )
        grouped: dict[str, list[Any]] = {}
        for row in rows:
            grouped.setdefault(row["section_path"], []).append(row)
        out: dict[str, dict[str, Any]] = {}
        for name, items in grouped.items():
            digest = hashlib.sha256("\n".join(item["body"] for item in items).encode()).hexdigest()
            out[name] = {"digest": digest, "unit_ids": [item["unit_id"] for item in items],
                         "units": len(items)}
        return out

    def stats(self) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT COUNT(*) AS documents, COALESCE(SUM(unit_count),0) AS units, "
            "COALESCE(SUM(table_count),0) AS tables, COALESCE(SUM(byte_size),0) AS bytes "
            "FROM knowledge_document WHERE status = 'indexed'"
        )
        return {"documents": int(row["documents"]), "units": int(row["units"]),
                "tables": int(row["tables"]), "source_bytes": int(row["bytes"]),
                "engine": ENGINE_SCHEMA, "parser": PARSER_VERSION}


# --------------------------------------------------------------------------- SEC adapter
def _decoded(raw: bytes, content_encoding: str | None) -> bytes:
    """SEC ignores ``identity`` for some documents and still returns gzip."""
    if raw[:2] == b"\x1f\x8b" or (content_encoding or "").lower() == "gzip":
        try:
            return gzip.decompress(raw)
        except OSError as exc:  # pragma: no cover - corrupt upstream payload
            raise ValidationError("SEC payload could not be decompressed") from exc
    return raw


def fetch_sec_document(cik: str, accession: str, primary_document: str) -> str:
    """Fetch the primary filing document from SEC EDGAR (public record)."""
    url = absolute_document_url(cik, accession, primary_document)
    request = Request(url, headers={"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "identity"})
    with urlopen(request, timeout=45) as response:  # noqa: S310 - fixed sec.gov host
        raw = _decoded(response.read(MAX_DOCUMENT_BYTES + 1),
                       response.headers.get("Content-Encoding"))
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValidationError("SEC document exceeds ingestion limit", url=url)
    return raw.decode("utf-8", errors="replace")


def sec_filing_index(cik: str, forms: Iterable[str], limit: int = 4) -> list[dict[str, Any]]:
    """Recent filings for a CIK from the SEC submissions API."""
    cik_digits = str(cik).lstrip("0").zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_digits}.json"
    request = Request(url, headers={"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "identity"})
    with urlopen(request, timeout=45) as response:  # noqa: S310
        raw = _decoded(response.read(), response.headers.get("Content-Encoding"))
    payload = json.loads(raw.decode("utf-8"))
    recent = payload.get("filings", {}).get("recent", {})
    wanted = {form.upper() for form in forms}
    out: list[dict[str, Any]] = []
    for index, form in enumerate(recent.get("form", [])):
        if form.upper() not in wanted:
            continue
        out.append({
            "accession": recent["accessionNumber"][index],
            "form_type": form.upper(),
            "filed_date": recent["filingDate"][index],
            "acceptance_time": recent["acceptanceDateTime"][index],
            "period_of_report": recent.get("reportDate", [None] * (index + 1))[index],
            "primary_document": recent["primaryDocument"][index],
            "is_amendment": form.upper().endswith("/A"),
        })
        if len(out) >= limit:
            break
    return out


def absolute_document_url(cik: str, accession: str, primary_document: str) -> str:
    cik_digits = str(cik).lstrip("0").zfill(10)
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik_digits)}/"
        f"{accession.replace('-', '')}/{primary_document}"
    )


def _periods_from_rows(rows: list[list[str]]) -> list[str]:
    for row in rows[:3]:
        found = [cell for cell in row[1:] if re.search(r"\b(19|20)\d{2}\b", cell)]
        if len(found) >= 1:
            return found[:6]
    return []


def _footnotes(rows: list[list[str]]) -> str | None:
    notes = [row[0] for row in rows if row and re.match(r"^\s*(\(?\d\)?|note\s)", row[0], re.I)]
    return " | ".join(notes[:6]) if notes else None


__all__ = [
    "ENGINE_SCHEMA", "PARSER_VERSION", "KnowledgeEngine", "extract_units",
    "normalise_document", "fetch_sec_document", "sec_filing_index", "absolute_document_url",
]
