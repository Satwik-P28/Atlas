"""The temporal evidence kernel.

Responsibilities:

* persist immutable evidence records with idempotent semantics;
* maintain explicit supersession links between versions of the same fact;
* answer the two distinct temporal questions (``PUBLIC_AVAILABLE`` vs
  ``ATLAS_INGESTED``) without leaking later information;
* expose complete provenance for any value, in both structured and narrative form.

The selection policy is deliberately simple and documented rather than clever:
within a lineage, the version that was known *latest at or before the query instant*
wins, and a direct observation always outranks a derived value. When a value has not
changed across re-publications, the earliest evidence of that value is reported so
that provenance points at the first document that established it.

Nothing here mutates past records. ``supersedes`` lives on the newer record and the
pair is also recorded in ``evidence_supersession`` for fast traversal in both
directions.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence
from datetime import datetime

from ..core.concepts import CONCEPTS, DERIVATIONS, concept_keys
from ..core.errors import MissingDataError, TemporalError, ValidationError
from ..core.temporal import AsOfMode, iso, to_utc, utcnow
from ..core.units import canonical_decimal, parse_decimal
from ..storage.db import Database
from .model import COLUMNS, EvidenceRecord, Verification, basis_tier
from .selection_sql import GroupSelection, select_sql

#: Identifier of the point-in-time selection policy. Stored on every result so a
#: future policy change is visible rather than silently altering historical answers.
SELECTION_POLICY = "atlas.select.point_in_time.v2"

#: Selection implementations. ``sql`` and ``python`` must agree exactly; the
#: differential test ``tests/test_selection_engines.py`` is the guard.
ENGINE_PYTHON = "python"
ENGINE_SQL = "sql"
ENGINES = (ENGINE_PYTHON, ENGINE_SQL)

_INSERT_SQL = (
    f"INSERT INTO evidence ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})"
)
_SELECT_SQL = f"SELECT {', '.join(COLUMNS)} FROM evidence"


class IngestStatus(str):
    INSERTED = "inserted"
    DUPLICATE = "duplicate"
    SUPERSEDING = "superseding"
    REJECTED = "rejected"


@dataclass(slots=True)
class IngestOutcome:
    status: str
    evidence_id: str
    concept: str
    superseded: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def inserted(self) -> bool:
        return self.status in {IngestStatus.INSERTED, IngestStatus.SUPERSEDING}


@dataclass(slots=True)
class IngestSummary:
    inserted: int = 0
    duplicates: int = 0
    superseding: int = 0
    rejected: int = 0
    supersessions: int = 0
    outcomes: list[IngestOutcome] = field(default_factory=list)
    rejections: list[dict[str, Any]] = field(default_factory=list)

    def add(self, outcome: IngestOutcome) -> None:
        self.supersessions += len(outcome.superseded)
        if outcome.status == IngestStatus.INSERTED:
            self.inserted += 1
        elif outcome.status == IngestStatus.SUPERSEDING:
            self.superseding += 1
        elif outcome.status == IngestStatus.DUPLICATE:
            self.duplicates += 1
        else:
            self.rejected += 1
        self.outcomes.append(outcome)

    @property
    def written(self) -> int:
        return self.inserted + self.superseding

    def to_dict(self) -> dict[str, Any]:
        return {
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "superseding": self.superseding,
            "rejected": self.rejected,
            "supersessions": self.supersessions,
            "written": self.written,
        }


@dataclass(slots=True)
class SelectedFact:
    """One fact selected for a point in time, with its evidence attached."""

    concept: str
    concept_label: str
    value: str | None
    value_text: str | None
    unit: str
    currency: str | None
    period_start: str | None
    period_end: str | None
    period_type: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    evidence_id: str
    source_id: str
    source_concept: str | None
    derivation_kind: str
    derivation_rule: str | None
    quality: str
    verification: str
    availability_time: str | None
    availability_precision: str
    availability_basis: str | None
    observed_at: str
    accession_number: str | None
    form_type: str | None
    revision_kind: str
    revision_count: int
    superseded_versions: list[str]
    availability_unknown: bool
    quality_flags: list[str] = field(default_factory=list)
    lineage: dict[str, Any] = field(default_factory=dict)
    limitations: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {name: getattr(self, name) for name in self.__slots__}
        payload.pop("quality_flags", None)
        payload["flags"] = list(self.quality_flags)
        return payload


@dataclass(slots=True)
class SelectionResult:
    """Result of a point-in-time query, including what it *could not* show."""

    entity_id: str
    as_of: str
    mode: str
    policy: str
    facts: list[SelectedFact]
    excluded_not_yet_available: int = 0
    excluded_unknown_availability: int = 0
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def completeness(self) -> str:
        if self.excluded_unknown_availability and not self.facts:
            return "incomplete: no evidenced availability for any candidate record"
        if self.excluded_unknown_availability:
            return (
                f"partial: {self.excluded_unknown_availability} candidate record(s) excluded "
                "because public availability is not evidenced"
            )
        return "complete_for_query"

    def by_concept(self) -> dict[str, SelectedFact]:
        return {fact.concept: fact for fact in self.facts}

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "as_of": self.as_of,
            "mode": self.mode,
            "mode_description": AsOfMode(self.mode).description,
            "policy": self.policy,
            "completeness": self.completeness,
            "excluded_not_yet_available": self.excluded_not_yet_available,
            "excluded_unknown_availability": self.excluded_unknown_availability,
            "contradictions": self.contradictions,
            "notes": self.notes,
            "truncated": self.truncated,
            "facts": [fact.to_dict() for fact in self.facts],
        }


@dataclass(slots=True)
class ProvenanceReport:
    """Financial X-Ray: value -> transformation -> source record -> filing."""

    evidence_id: str
    record: EvidenceRecord
    source: dict[str, Any] | None
    raw_document: dict[str, Any] | None
    filing: dict[str, Any] | None
    transformation: list[dict[str, Any]]
    revision_chain: list[dict[str, Any]]
    derived_inputs: list[dict[str, Any]]
    limitations: list[str]
    narrative: list[str]

    def to_dict(self) -> dict[str, Any]:
        record = self.record.to_dict()
        # The stored record separates exact text from a numeric projection. Consumers
        # (X-Ray, exports) expect one displayable `value`; prefer the canonical string.
        record.setdefault("value", record.get("value_text") or record.get("value_numeric"))
        return {
            "evidence_id": self.evidence_id,
            "record": record,
            "source": self.source,
            "raw_document": self.raw_document,
            "filing": self.filing,
            "transformation": self.transformation,
            "revision_chain": self.revision_chain,
            "derived_inputs": self.derived_inputs,
            "limitations": self.limitations,
            "narrative": self.narrative,
        }


class EvidenceKernel:
    """Storage and query engine for versioned financial evidence."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ writes
    def ingest(
        self,
        record: EvidenceRecord,
        *,
        supersede: bool = True,
        reason: str | None = None,
    ) -> IngestOutcome:
        """Persist one record idempotently, linking it to the version it replaces."""
        existing = self.db.query_one("SELECT evidence_id FROM evidence WHERE content_hash = ?", (record.content_hash,))
        if existing is not None:
            return IngestOutcome(
                status=IngestStatus.DUPLICATE,
                evidence_id=str(existing["evidence_id"]),
                concept=record.concept,
                notes=["identical evidence already stored (content hash match)"],
            )
        # A collision here would mean two economically different observations hash to
        # the same identity. That is a defect in the identity tuple, not a duplicate, so
        # it is surfaced loudly instead of being swallowed as idempotent.
        identity_clash = self.db.query_one(
            "SELECT content_hash FROM evidence WHERE evidence_id = ?", (record.evidence_id,)
        )
        if identity_clash is not None:
            from ..core.errors import StorageError

            raise StorageError(
                "evidence identity collision: same evidence_id with different content",
                evidence_id=record.evidence_id,
                incoming_hash=record.content_hash,
                stored_hash=identity_clash["content_hash"],
                hint="the evidence identity tuple is missing a discriminating field",
            )

        prior = self._lineage_versions(record.lineage_key(), exclude_id=record.evidence_id) if supersede else []
        superseded: list[str] = []
        revisions: list[str] = []
        if supersede:
            for candidate in prior:
                if not self._candidate_supersedes(record, candidate):
                    continue
                superseded.append(candidate.evidence_id)
                if not record.same_value(candidate):
                    revisions.append(candidate.source_concept or candidate.concept)
        # Ingestion order is assigned by the kernel, not the caller: it is a property of
        # when Atlas learned the fact, and it breaks ties between records whose public
        # availability timestamps are identical.
        record.ingest_seq = int(
            self.db.scalar("SELECT COALESCE(MAX(ingest_seq), 0) FROM evidence", default=0) or 0
        ) + 1
        self.db.execute(_INSERT_SQL, record.to_row())
        for old_id in superseded:
            self._link_supersession(old_id, record.evidence_id, reason or self._supersession_reason(record, old_id))
        # A derived record that names its inputs is indexed immediately, so the reverse
        # dependency question is answerable without a later scan. Recording is inside the
        # caller's transaction: if an input does not exist, the whole ingest rolls back
        # rather than persisting a derived value with broken provenance.
        if record.derivation_kind == "derived_calculation" and record.lineage.get("inputs"):
            from ..dependencies import DependencyIndex

            DependencyIndex(self.db).record_for_derived(record)
        status = IngestStatus.SUPERSEDING if superseded else IngestStatus.INSERTED
        notes = []
        if revisions:
            notes.append(
                "value differs from an earlier version of the same fact in "
                + ", ".join(sorted(set(revisions)))
            )
        return IngestOutcome(
            status=status,
            evidence_id=record.evidence_id,
            concept=record.concept,
            superseded=superseded,
            notes=notes,
        )

    def ingest_many(
        self,
        records: Iterable[EvidenceRecord],
        *,
        continue_on_error: bool = False,
    ) -> IngestSummary:
        summary = IngestSummary()
        for record in records:
            try:
                with self.db.transaction():
                    outcome = self.ingest(record)
                    summary.add(outcome)
            except Exception as exc:  # noqa: BLE001 - recorded, optionally re-raised
                summary.rejected += 1
                summary.rejections.append({"evidence_id": record.evidence_id, "concept": record.concept, "error": str(exc)})
                if not continue_on_error:
                    raise
        return summary

    def _link_supersession(self, superseded_id: str, superseding_id: str, reason: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO evidence_supersession (superseded_id, superseding_id, reason, created_at) "
            "VALUES (?,?,?,?)",
            (superseded_id, superseding_id, reason, iso(utcnow())),
        )

    def _supersession_reason(self, record: EvidenceRecord, old_id: str) -> str:
        old = self.get(old_id, required=False)
        if old is None:  # pragma: no cover - defensive
            return "later_version"
        if old.accession_number and record.accession_number:
            if record.accession_number != old.accession_number:
                if record.revision_kind in {"amendment", "restatement"}:
                    return f"{record.revision_kind}_of_{old.accession_number}"
                return "later_filing_same_period"
        return "later_version"

    def _candidate_supersedes(self, new: EvidenceRecord, old: EvidenceRecord) -> bool:
        """Whether ``new`` is a *changed* later version of the same fact.

        Supersession means "the earlier assertion is no longer current". A mere
        re-assertion of an identical value in a later filing is not a revision: the
        value never changed, and marking it superseded would misrepresent the source
        history and inflate revision noise. Such records are still retained (they are
        separate observations from separate documents) and the selection policy simply
        reports the earliest evidence of the unchanged value.

        A record whose availability is unknown may be older than what we hold, so it
        can never supersede anything.
        """
        if new.evidence_id == old.evidence_id:
            return False
        if new.availability_time is None or old.availability_time is None:
            return False
        if new.availability_time < old.availability_time:
            return False
        return not new.same_value(old)

    def _lineage_versions(self, key: Sequence[str], exclude_id: str | None = None) -> list[EvidenceRecord]:
        sql = (
            f"{_SELECT_SQL} WHERE entity_id = ? AND record_kind = ? AND concept = ? AND unit = ? "
            "AND COALESCE(period_start,'') = ? AND COALESCE(period_end,'') = ? "
            "ORDER BY availability_time NULLS LAST, ingest_seq"
        )
        rows = self.db.query(sql, (key[0], key[1], key[2], key[3], key[4], key[5]))
        records = [EvidenceRecord.from_row(row) for row in rows]
        records = [r for r in records if str(r.tier) == str(key[6])]
        if exclude_id:
            records = [r for r in records if r.evidence_id != exclude_id]
        return records

    # ------------------------------------------------------------------- reads
    def get(self, evidence_id: str, *, required: bool = True) -> EvidenceRecord | None:
        row = self.db.query_one(f"{_SELECT_SQL} WHERE evidence_id = ?", (evidence_id,))
        if row is None:
            if required:
                raise MissingDataError("no such evidence record", evidence_id=evidence_id)
            return None
        return EvidenceRecord.from_row(row)

    def count(self, *, entity_id: str | None = None) -> int:
        if entity_id:
            return int(self.db.scalar("SELECT COUNT(*) FROM evidence WHERE entity_id = ?", (entity_id,), 0) or 0)
        return int(self.db.scalar("SELECT COUNT(*) FROM evidence", default=0) or 0)

    def history(
        self,
        entity_id: str,
        concept: str,
        *,
        period_end: str | None = None,
        unit: str | None = None,
        include_derived: bool = True,
    ) -> list[EvidenceRecord]:
        """Every stored version of a fact, oldest availability first."""
        sql = f"{_SELECT_SQL} WHERE entity_id = ? AND concept = ?"
        params: list[Any] = [entity_id, concept]
        if period_end:
            sql += " AND period_end = ?"
            params.append(period_end)
        if unit:
            sql += " AND unit = ?"
            params.append(unit)
        sql += " ORDER BY availability_time NULLS LAST, observed_at, ingest_seq, evidence_id"
        records = [EvidenceRecord.from_row(row) for row in self.db.query(sql, params)]
        if not include_derived:
            records = [r for r in records if not r.is_derived()]
        return records

    def lineage(self, evidence_id: str) -> list[dict[str, Any]]:
        record = self.get(evidence_id)
        chain = self._lineage_versions(record.lineage_key())
        return [self._chain_entry(item) for item in sorted(chain, key=lambda r: r.ordering_key())]

    def revision_chain(self, evidence_id: str) -> list[dict[str, Any]]:
        return self.lineage(evidence_id)

    def _chain_entry(self, record: EvidenceRecord) -> dict[str, Any]:
        superseded_by = [
            row["superseding_id"]
            for row in self.db.query(
                "SELECT superseding_id FROM evidence_supersession WHERE superseded_id = ? ORDER BY created_at",
                (record.evidence_id,),
            )
        ]
        return {
            "evidence_id": record.evidence_id,
            "concept": record.concept,
            "value": record.value_numeric or record.value_text,
            "unit": record.unit,
            "period_start": record.period_start,
            "period_end": record.period_end,
            "revision_kind": record.revision_kind,
            "derivation_kind": record.derivation_kind,
            "availability_time": record.availability_time,
            "availability_precision": record.availability_precision,
            "observed_at": record.observed_at,
            "ingest_seq": record.ingest_seq,
            "accession_number": record.accession_number,
            "superseded_by": superseded_by,
            "quality": record.quality,
        }

    # -------------------------------------------------------------- as-of query
    def as_of(
        self,
        entity_id: str,
        as_of: datetime | str,
        *,
        mode: AsOfMode | str = AsOfMode.PUBLIC_AVAILABLE,
        concepts: Sequence[str] | None = None,
        statement: str | None = None,
        include_unknown: bool = False,
        include_derived: bool = True,
        limit: int | None = None,
        offset: int = 0,
        engine: str = ENGINE_PYTHON,
    ) -> SelectionResult:
        """Select the fact versions knowable at ``as_of`` under explicit semantics.

        ``engine`` selects the implementation only; both must return identical results
        (guarded by a differential test). ``sql`` avoids transferring the whole
        candidate set and is the faster path on large histories.
        """
        resolved_mode = mode if isinstance(mode, AsOfMode) else AsOfMode(str(mode))
        ts = iso(to_utc(as_of))
        column = resolved_mode.column
        if engine not in ENGINES:
            raise ValidationError(
                "unknown selection engine", engine=engine, supported=list(ENGINES)
            )

        wanted = self._resolve_concept_filter(concepts, statement, include_derived)
        not_yet_available = self._count_not_yet_available(entity_id, ts, column, wanted)

        # A record with unevidenced *public availability* cannot be placed in time, so it
        # is excluded and counted. Under ``atlas_ingested`` semantics the observation
        # time is itself the evidenced instant, so such a record is genuinely knowable
        # and must not be reported as excluded (nor included twice).
        availability_mode = resolved_mode is AsOfMode.PUBLIC_AVAILABLE
        unknown_candidates = (
            [EvidenceRecord.from_row(row) for row in self._unknown_rows(entity_id, wanted)]
            if availability_mode
            else []
        )

        if engine == ENGINE_SQL:
            groups = select_sql(self.db, entity_id=entity_id, ts=ts, column=column, wanted=wanted)
        else:
            known_rows = self._fetch_known_candidates(entity_id, ts, column, wanted)
            groups = self._groups_from_records(known_rows, column=column)

        facts: list[SelectedFact] = []
        contradictions: list[dict[str, Any]] = []
        for group in groups:
            fact, contradiction = self._fact_from_group(group)
            if contradiction is not None:
                contradictions.append(contradiction)
            if fact is not None:
                facts.append(fact)

        if include_unknown:
            for record in unknown_candidates:
                facts.append(self._fact_from_record(record, revisions=0, superseded=[], flags=["availability_unknown"]))

        facts.sort(key=lambda f: (f.period_end or "", f.period_start or "", f.concept, f.unit))
        truncated = False
        if limit is not None:
            window = facts[offset : offset + limit]
            truncated = (offset + limit) < len(facts)
            facts = window

        notes: list[str] = []
        if unknown_candidates and not include_unknown:
            notes.append(
                "candidate records without evidenced public availability were excluded; "
                "the reconstruction is therefore not provably complete"
            )
        if not_yet_available:
            notes.append(f"{not_yet_available} record(s) existed but were not available at the requested instant")
        if resolved_mode is AsOfMode.ATLAS_INGESTED:
            notes.append(
                "selection used Atlas ingestion time, not public availability; a value may have "
                "been publicly available before Atlas stored it"
            )

        return SelectionResult(
            entity_id=entity_id,
            as_of=ts,
            mode=resolved_mode.value,
            policy=SELECTION_POLICY,
            facts=facts,
            excluded_not_yet_available=not_yet_available,
            excluded_unknown_availability=(
                0 if (include_unknown or not availability_mode) else len(unknown_candidates)
            ),
            contradictions=contradictions,
            notes=notes,
            truncated=truncated,
        )

    def _resolve_concept_filter(
        self,
        concepts: Sequence[str] | None,
        statement: str | None,
        include_derived: bool,
    ) -> list[str] | None:
        if concepts:
            wanted = list(concepts)
        elif statement:
            wanted = [c.key for c in CONCEPTS.values() if c.statement == statement]
            wanted += [d.key for d in DERIVATIONS.values() if d.statement == statement]
        elif include_derived:
            return None
        else:
            return [c.key for c in CONCEPTS.values()]
        if not include_derived:
            wanted = [c for c in wanted if c not in DERIVATIONS]
        unknown = [c for c in wanted if c not in CONCEPTS and c not in DERIVATIONS]
        if unknown:
            raise ValidationError(
                "unknown concept(s) requested; Atlas does not invent concept mappings",
                concepts=unknown,
            )
        return wanted

    def _concept_clause(self, wanted: Sequence[str] | None) -> str:
        if not wanted:
            return ""
        return f" AND concept IN ({', '.join('?' for _ in wanted)})"

    def _fetch_known_candidates(
        self,
        entity_id: str,
        ts: str,
        column: str,
        wanted: Sequence[str] | None,
    ) -> list[Mapping[str, Any]]:
        params: list[Any] = [entity_id, ts]
        params.extend(wanted or [])
        sql = (
            f"{_SELECT_SQL} WHERE entity_id = ? AND {column} IS NOT NULL AND {column} <= ?"
            + self._concept_clause(wanted)
        )
        return list(self.db.query(sql, params))

    def _unknown_rows(self, entity_id: str, wanted: Sequence[str] | None) -> list[Mapping[str, Any]]:
        params: list[Any] = [entity_id]
        params.extend(wanted or [])
        sql = (
            f"{_SELECT_SQL} WHERE entity_id = ? AND availability_precision = 'unknown'"
            + self._concept_clause(wanted)
        )
        return list(self.db.query(sql, params))

    def _count_not_yet_available(
        self, entity_id: str, ts: str, column: str, wanted: Sequence[str] | None
    ) -> int:
        concept_clause = ""
        params: list[Any] = [entity_id, ts]
        if wanted:
            concept_clause = f" AND concept IN ({', '.join('?' for _ in wanted)})"
            params.extend(wanted)
        sql = f"SELECT COUNT(*) FROM evidence WHERE entity_id = ? AND {column} IS NOT NULL AND {column} > ?" + concept_clause
        return int(self.db.scalar(sql, params, 0) or 0)

    def _groups_from_records(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        column: str,
    ) -> list[GroupSelection]:
        """Group candidates and apply the documented ranking in Python.

        Mirrors :func:`atlas.evidence.selection_sql.select_sql` step for step; the two
        implementations are compared by a differential test rather than assumed equal.
        """
        by_group: dict[tuple[str, str, str, str], list[EvidenceRecord]] = defaultdict(list)
        for row in rows:
            record = EvidenceRecord.from_row(row)
            by_group[
                (record.concept, record.period_start or "", record.period_end or "", record.unit)
            ].append(record)

        groups: list[GroupSelection] = []
        for (concept, period_start, period_end, unit), versions in by_group.items():
            by_tier: dict[int, list[EvidenceRecord]] = defaultdict(list)
            for record in versions:
                by_tier[record.tier].append(record)
            tier = min(by_tier)
            pool = by_tier[tier]
            # Availability ascending, best quality last, latest ingestion last.
            pool.sort(
                key=lambda r: (
                    getattr(r, column) or "",
                    -r.quality_rank()[0],
                    -r.quality_rank()[1],
                    r.ingest_seq,
                    r.evidence_id,
                )
            )
            latest = pool[-1]
            latest_instant = getattr(latest, column) or ""
            same_moment = [r for r in pool if (getattr(r, column) or "") == latest_instant]
            conflicting = (
                same_moment
                if len({r.value_numeric or r.value_text for r in same_moment}) > 1
                else None
            )
            chosen = conflicting[0] if conflicting else self._earliest_of_value(pool, column, latest)
            groups.append(
                GroupSelection(
                    concept=concept,
                    period_start=period_start or None,
                    period_end=period_end or None,
                    unit=unit,
                    revisions=len(pool),
                    tier=tier,
                    latest_instant=latest_instant,
                    chosen=chosen,
                    conflicting=conflicting,
                )
            )
        return groups

    def _earliest_of_value(
        self, pool: Sequence[EvidenceRecord], column: str, latest: EvidenceRecord
    ) -> EvidenceRecord:
        """Earliest evidence of a value that never changed.

        Provenance should point at the document that first established the number, not
        at the most recent comparative that repeated it.
        """
        target_value = latest.value_numeric or latest.value_text
        equivalent = [r for r in pool if (r.value_numeric or r.value_text) == target_value]
        equivalent.sort(
            key=lambda r: (
                getattr(r, column) or "",
                r.quality_rank()[0],
                r.quality_rank()[1],
                r.ingest_seq,
                r.evidence_id,
            )
        )
        return equivalent[0] if equivalent else latest

    def _adjudicate(self, rows: Sequence[EvidenceRecord]) -> EvidenceRecord:
        """Choose one record when several assert different values at the same instant.

        Identical availability means public time cannot order them. The revision chain
        can: a record that supersedes another in the set is the later assertion. Only
        when the chain is silent does quality, then ingestion order, decide. The caller
        always reports the conflict, so this is adjudication, never concealment.
        """
        ids = [r.evidence_id for r in rows]
        placeholders = ", ".join("?" for _ in ids)
        superseded_within = {
            row["superseded_id"]
            for row in self.db.query(
                f"SELECT superseded_id FROM evidence_supersession WHERE superseding_id IN ({placeholders})",
                ids,
            )
        }
        candidates = [r for r in rows if r.evidence_id not in superseded_within] or list(rows)
        candidates.sort(key=lambda r: (r.quality_rank()[0], r.quality_rank()[1], -r.ingest_seq, r.evidence_id))
        return candidates[0]

    def _fact_from_group(
        self, group: GroupSelection
    ) -> tuple[SelectedFact | None, dict[str, Any] | None]:
        chosen = group.chosen
        contradiction: dict[str, Any] | None = None
        flags: list[str] = []
        if group.conflicting:
            chosen = self._adjudicate(group.conflicting)
            contradiction = {
                "concept": group.concept,
                "period_end": group.period_end or "",
                "unit": group.unit,
                "time": group.latest_instant,
                "values": sorted({r.value_numeric or r.value_text or "" for r in group.conflicting}),
                "evidence_ids": sorted(r.evidence_id for r in group.conflicting),
                "selected": chosen.evidence_id,
                "note": (
                    "multiple values asserted with identical availability; reported as a "
                    "contradiction and adjudicated by revision-chain tip, then quality, then "
                    "ingestion order"
                ),
            }
            flags.append("contradictory_evidence")
        if chosen.quality in {"suspect", "quarantined"}:
            flags.append(f"quality_{chosen.quality}")
        if group.revisions > 1:
            flags.append("multiple_versions")
        if chosen.derivation_kind == "estimate":
            flags.append("estimated_value")
        superseded = [
            row["superseded_id"]
            for row in self.db.query(
                "SELECT superseded_id FROM evidence_supersession WHERE superseding_id = ?",
                (chosen.evidence_id,),
            )
        ]
        return (
            self._fact_from_record(
                chosen, revisions=group.revisions, superseded=superseded, flags=flags
            ),
            contradiction,
        )

    def _fact_from_record(
        self,
        record: EvidenceRecord,
        *,
        revisions: int,
        superseded: list[str],
        flags: list[str],
    ) -> SelectedFact:
        return SelectedFact(
            concept=record.concept,
            concept_label=record.concept_label,
            value=record.value_numeric,
            value_text=record.value_text,
            unit=record.unit,
            currency=record.currency,
            period_start=record.period_start,
            period_end=record.period_end,
            period_type=record.period_type,
            fiscal_year=record.fiscal_year,
            fiscal_period=record.fiscal_period,
            evidence_id=record.evidence_id,
            source_id=record.source_id,
            source_concept=f"{record.taxonomy}:{record.source_concept}" if record.taxonomy and record.source_concept else record.source_concept,
            derivation_kind=record.derivation_kind,
            derivation_rule=record.derivation_rule,
            quality=record.quality,
            verification=record.verification,
            availability_time=record.availability_time,
            availability_precision=record.availability_precision,
            availability_basis=record.availability_basis,
            observed_at=record.observed_at,
            accession_number=record.accession_number,
            form_type=record.form_type,
            revision_kind=record.revision_kind,
            revision_count=revisions,
            superseded_versions=superseded,
            availability_unknown=not record.availability_known,
            quality_flags=flags,
            lineage=record.lineage,
            limitations=record.limitations,
        )

    # --------------------------------------------------------------- provenance
    def provenance(self, evidence_id: str, *, include_raw_body: bool = False) -> ProvenanceReport:
        record = self.get(evidence_id)
        source = self.db.query_one("SELECT * FROM source WHERE source_id = ?", (record.source_id,))
        raw_document = None
        if record.raw_doc_id:
            row = self.db.query_one(
                "SELECT doc_id, url, content_hash, media_type, http_status, byte_size, retrieved_at, etag, last_modified"
                + (", body" if include_raw_body else "")
                + " FROM raw_document WHERE doc_id = ?",
                (record.raw_doc_id,),
            )
            if row is not None:
                raw_document = {key: row[key] for key in row.keys()}
                if raw_document.get("body") is not None:
                    raw_document["body"] = f"<{len(raw_document['body'])} bytes>"
        filing = None
        if record.accession_number:
            row = self.db.query_one("SELECT * FROM filing WHERE accession_number = ?", (record.accession_number,))
            if row is not None:
                filing = {key: row[key] for key in row.keys() if key != "doc_id"}

        lineage = record.lineage
        transformation: list[dict[str, Any]] = []
        if lineage:
            if "steps" in lineage and isinstance(lineage["steps"], list):
                transformation = list(lineage["steps"])
            elif "rule" in lineage:
                transformation = [{"step": "derived", "rule": lineage.get("rule"), "detail": lineage.get("description")}]

        derived_inputs: list[dict[str, Any]] = []
        for entry in lineage.get("inputs", []) if isinstance(lineage.get("inputs"), list) else []:
            input_id = entry.get("evidence_id")
            if not input_id:
                continue
            input_record = self.get(input_id, required=False)
            derived_inputs.append(
                {
                    "evidence_id": input_id,
                    "concept": entry.get("concept"),
                    "value": entry.get("value"),
                    "unit": entry.get("unit"),
                    "found": input_record is not None,
                    "availability_time": input_record.availability_time if input_record else None,
                    "accession_number": input_record.accession_number if input_record else None,
                }
            )

        limitations: list[str] = []
        if record.limitations:
            limitations.append(record.limitations)
        if not record.availability_known:
            limitations.append(
                "Public availability is not evidenced for this record; it is excluded from "
                "public-availability as-of queries by default."
            )
        elif record.availability_precision == "date":
            limitations.append(
                "Availability is known only to a calendar date and is treated as end-of-day UTC, "
                "so intraday as-of queries on that date will not return it."
            )
        if record.verification == Verification.UNCHECKED.value:
            limitations.append("Value has not been independently cross-validated.")
        if record.revision_kind != "original":
            limitations.append(
                f"This record is a {record.revision_kind} superseding an earlier version; earlier values are retained."
            )

        narrative = self._narrative(record, source, raw_document, filing, transformation, derived_inputs)
        return ProvenanceReport(
            evidence_id=evidence_id,
            record=record,
            source={k: source[k] for k in source.keys()} if source is not None else None,
            raw_document=raw_document,
            filing=filing,
            transformation=transformation,
            revision_chain=self.lineage(evidence_id),
            derived_inputs=derived_inputs,
            limitations=limitations,
            narrative=narrative,
        )

    def _narrative(
        self,
        record: EvidenceRecord,
        source: Mapping[str, Any] | None,
        raw_document: Mapping[str, Any] | None,
        filing: Mapping[str, Any] | None,
        transformation: list[dict[str, Any]],
        derived_inputs: list[dict[str, Any]],
    ) -> list[str]:
        lines: list[str] = []
        value = record.value_numeric or record.value_text
        lines.append(
            f"{record.concept} = {value} {record.unit} for period "
            f"{record.period_start or '(instant)'}..{record.period_end or '(none)'}."
        )
        lines.append(
            f"Asserted by source '{record.source_id}'"
            + (f" as element {record.taxonomy}:{record.source_concept}" if record.source_concept else "")
            + "."
        )
        if filing:
            lines.append(
                f"Filing {filing['accession_number']} ({filing['form_type']}) filed {filing['filed_date']}"
                + (f", accepted {filing['acceptance_datetime']}" if filing["acceptance_datetime"] else "")
                + "."
            )
        elif record.accession_number:
            lines.append(
                f"Filing {record.accession_number}"
                + (f" ({record.form_type})" if record.form_type else "")
                + (f" filed {record.filed_date}" if record.filed_date else "")
                + " (filing metadata not stored in this dataset)."
            )
        if record.availability_time:
            lines.append(
                f"Public availability: {record.availability_time} (precision {record.availability_precision}, "
                f"basis {record.availability_basis})."
            )
        else:
            lines.append("Public availability: NOT EVIDENCED.")
        lines.append(f"Atlas observed this record at {record.observed_at} (derivation: {record.derivation_kind}).")
        for step in transformation:
            detail = f" - {step.get('detail')}" if step.get("detail") else ""
            lines.append(f"Transformation: {step.get('step')}{detail}")
        for item in derived_inputs:
            lines.append(
                f"Derived from {item['concept']} = {item['value']} (evidence {item['evidence_id']}"
                + (f", accession {item['accession_number']}" if item.get("accession_number") else "")
                + ")."
            )
        if raw_document:
            lines.append(
                f"Raw document {raw_document.get('doc_id')} retrieved {raw_document.get('retrieved_at')} "
                f"(sha256 {str(raw_document.get('content_hash'))[:16]}..., {raw_document.get('byte_size')} bytes)."
            )
        return lines

    # -------------------------------------------------------------------- stats
    def stats(self, *, entity_id: str | None = None) -> dict[str, Any]:
        where = " WHERE entity_id = ?" if entity_id else ""
        params: tuple[Any, ...] = (entity_id,) if entity_id else ()
        total = int(self.db.scalar(f"SELECT COUNT(*) FROM evidence{where}", params, 0) or 0)
        by_concept = {
            row["concept"]: row["n"]
            for row in self.db.query(
                f"SELECT concept, COUNT(*) AS n FROM evidence{where} GROUP BY concept ORDER BY n DESC", params
            )
        }
        by_quality = {
            row["quality"]: row["n"]
            for row in self.db.query(f"SELECT quality, COUNT(*) AS n FROM evidence{where} GROUP BY quality", params)
        }
        by_derivation = {
            row["derivation_kind"]: row["n"]
            for row in self.db.query(
                f"SELECT derivation_kind, COUNT(*) AS n FROM evidence{where} GROUP BY derivation_kind", params
            )
        }
        unknown_availability = int(
            self.db.scalar(
                f"SELECT COUNT(*) FROM evidence{where}{' AND' if where else ' WHERE'} availability_precision = 'unknown'",
                params,
                0,
            )
            or 0
        )
        supersessions = int(self.db.scalar("SELECT COUNT(*) FROM evidence_supersession", default=0) or 0)
        accessions = int(
            self.db.scalar(
                f"SELECT COUNT(DISTINCT accession_number) FROM evidence{where}", params, 0
            )
            or 0
        )
        return {
            "entity_id": entity_id,
            "evidence_records": total,
            "distinct_accessions": accessions,
            "supersession_links": supersessions,
            "unknown_availability": unknown_availability,
            "by_concept": by_concept,
            "by_quality": by_quality,
            "by_derivation": by_derivation,
        }


def decimal_or_none(value: str | None):
    return parse_decimal(value) if value is not None else None
