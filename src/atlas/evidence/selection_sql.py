"""SQL implementation of point-in-time selection.

The Python selector fetches every candidate version and groups them in memory. That is
easy to audit but transfers the whole candidate set for an all-concept query. This
module expresses the *same* documented policy as a single SQL statement: tier
resolution, latest-version ranking and the earliest-evidence-of-unchanged-value rule
become window functions and correlated subqueries, and only the winning records are
hydrated.

Ranking (identical to :mod:`atlas.evidence.kernel`):

1. lowest basis tier in the group wins (a source observation outranks a derived value);
2. within that tier, the latest availability (or observation, for the
   ``atlas_ingested`` question) at or before the query instant;
3. ties on that instant are broken by best quality, then latest ingestion order, then
   evidence id, so the result is deterministic;
4. if the values at the winning instant disagree, the group is returned as conflicting
   and the kernel adjudicates visibly (it never silently picks one);
5. if the value did not change, the *earliest* evidence of that value is returned so
   provenance points at the document that first established it.

Why the kernel still adjudicates in Python: genuine same-instant contradictions are rare,
and choosing between them requires walking supersession edges, which is cheap on a
handful of rows and much clearer in code than in SQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ..core.errors import ValidationError
from ..storage.db import Database
from .model import COLUMNS, EvidenceRecord

_SELECT_COLUMNS = ", ".join(COLUMNS)

#: Quality rank must match ``EvidenceRecord.quality_rank`` in model.py.
_QUALITY_CASE = (
    "CASE quality WHEN 'verified' THEN 0 WHEN 'unverified' THEN 1 "
    "WHEN 'suspect' THEN 2 WHEN 'quarantined' THEN 3 ELSE 9 END"
)
_TIER_CASE = (
    "CASE derivation_kind WHEN 'source_observation' THEN 0 "
    "WHEN 'normalized_source_observation' THEN 0 "
    "WHEN 'derived_calculation' THEN 2 WHEN 'estimate' THEN 3 ELSE 1 END"
)

_SQL = f"""
WITH cand AS (
    SELECT
        {_SELECT_COLUMNS},
        COALESCE(period_start, '') AS ps,
        COALESCE(period_end, '') AS pe,
        COALESCE(value_numeric, value_text, '') AS val,
        {{column}} AS instant,
        {_TIER_CASE} AS tier,
        {_QUALITY_CASE} AS qrank
    FROM evidence
    WHERE entity_id = ? AND {{column}} IS NOT NULL AND {{column}} <= ?{{concept_clause}}
),
grp AS (
    SELECT concept, ps, pe, unit, MIN(tier) AS tier
    FROM cand
    GROUP BY concept, ps, pe, unit
),
elig AS (
    SELECT c.*
    FROM cand c
    JOIN grp g
      ON g.concept = c.concept AND g.ps = c.ps AND g.pe = c.pe AND g.unit = c.unit
    WHERE c.tier = g.tier
),
-- One window pass computes everything the policy needs: the latest version, the
-- earliest evidence of each value, whether the values at the winning instant disagree,
-- and how many versions the group holds. Correlated subqueries per group made the first
-- version of this query slower than the Python path.
windowed AS (
    SELECT e.*,
           COUNT(*) OVER (PARTITION BY concept, ps, pe, unit) AS n,
           ROW_NUMBER() OVER (
               PARTITION BY concept, ps, pe, unit
               ORDER BY instant DESC, qrank ASC, ingest_seq DESC, evidence_id ASC
           ) AS latest_rn,
           ROW_NUMBER() OVER (
               PARTITION BY concept, ps, pe, unit, val
               ORDER BY instant ASC, qrank ASC, ingest_seq ASC, evidence_id ASC
           ) AS earliest_val_rn,
           MIN(val) OVER (PARTITION BY concept, ps, pe, unit, instant) AS min_at_instant,
           MAX(val) OVER (PARTITION BY concept, ps, pe, unit, instant) AS max_at_instant
    FROM elig e
),
latest AS (
    SELECT * FROM windowed WHERE latest_rn = 1
)
SELECT l.concept, l.ps, l.pe, l.unit, l.instant, l.n, l.tier,
       CASE WHEN l.min_at_instant <> l.max_at_instant THEN NULL
            ELSE COALESCE(pick.evidence_id, l.evidence_id) END AS chosen_id,
       (l.min_at_instant <> l.max_at_instant) AS conflicting
FROM latest l
LEFT JOIN windowed pick
  ON pick.concept = l.concept AND pick.ps = l.ps AND pick.pe = l.pe AND pick.unit = l.unit
 AND pick.val = l.val AND pick.earliest_val_rn = 1
ORDER BY l.pe, l.ps, l.concept, l.unit
"""


@dataclass(slots=True)
class GroupSelection:
    """One fact group as selected by SQL, before kernel adjudication/rendering."""

    concept: str
    period_start: str | None
    period_end: str | None
    unit: str
    revisions: int
    tier: int
    latest_instant: str
    chosen: EvidenceRecord
    conflicting: list[EvidenceRecord] | None = None

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.concept, self.period_start or "", self.period_end or "", self.unit)


def select_sql(
    db: Database,
    *,
    entity_id: str,
    ts: str,
    column: str,
    wanted: Sequence[str] | None,
) -> list[GroupSelection]:
    """Return one selection per fact group, using SQL for grouping and ranking."""
    if column not in {"availability_time", "observed_at"}:
        raise ValidationError("unsupported temporal column", column=column)
    params: list[Any] = [entity_id, ts]
    concept_clause = ""
    if wanted:
        concept_clause = f" AND concept IN ({', '.join('?' for _ in wanted)})"
        params.extend(wanted)
    rows = db.query(_SQL.format(column=column, concept_clause=concept_clause), params)
    if not rows:
        return []

    chosen_ids = [str(row["chosen_id"]) for row in rows if row["chosen_id"]]
    hydrated: dict[str, EvidenceRecord] = {}
    if chosen_ids:
        for chunk_start in range(0, len(chosen_ids), 400):
            chunk = chosen_ids[chunk_start : chunk_start + 400]
            placeholders = ", ".join("?" for _ in chunk)
            for record_row in db.query(
                f"SELECT {_SELECT_COLUMNS} FROM evidence WHERE evidence_id IN ({placeholders})", chunk
            ):
                record = EvidenceRecord.from_row(record_row)
                hydrated[record.evidence_id] = record

    groups: list[GroupSelection] = []
    for row in rows:
        chosen_id = row["chosen_id"]
        if chosen_id and chosen_id in hydrated:
            chosen = hydrated[str(chosen_id)]
        elif row["conflicting"]:
            # Only reachable for a conflicting group whose chosen id is NULL; the
            # adjudication query below supplies the rows. Use a placeholder that the
            # caller replaces after adjudication.
            conflicting_rows = _conflicting_rows(
                db,
                entity_id=entity_id,
                ts=ts,
                column=column,
                concept=row["concept"],
                period_start=row["ps"],
                period_end=row["pe"],
                unit=row["unit"],
                instant=str(row["instant"]),
                tier=int(row["tier"]),
            )
            if not conflicting_rows:  # pragma: no cover - defensive
                continue
            groups.append(
                GroupSelection(
                    concept=row["concept"],
                    period_start=row["ps"] or None,
                    period_end=row["pe"] or None,
                    unit=row["unit"],
                    revisions=int(row["n"]),
                    tier=int(row["tier"]),
                    latest_instant=str(row["instant"]),
                    chosen=conflicting_rows[0],
                    conflicting=conflicting_rows,
                )
            )
            continue
        else:  # pragma: no cover - defensive
            continue
        conflicting_rows = None
        if row["conflicting"]:
            conflicting_rows = _conflicting_rows(
                db,
                entity_id=entity_id,
                ts=ts,
                column=column,
                concept=row["concept"],
                period_start=row["ps"],
                period_end=row["pe"],
                unit=row["unit"],
                instant=str(row["instant"]),
                tier=int(row["tier"]),
            )
        groups.append(
            GroupSelection(
                concept=row["concept"],
                period_start=row["ps"] or None,
                period_end=row["pe"] or None,
                unit=row["unit"],
                revisions=int(row["n"]),
                tier=int(row["tier"]),
                latest_instant=str(row["instant"]),
                chosen=chosen,
                conflicting=conflicting_rows,
            )
        )
    return groups


def _conflicting_rows(
    db: Database,
    *,
    entity_id: str,
    ts: str,
    column: str,
    concept: str,
    period_start: str,
    period_end: str,
    unit: str,
    instant: str,
    tier: int,
) -> list[EvidenceRecord]:
    rows = db.query(
        f"SELECT {_SELECT_COLUMNS}, {_TIER_CASE} AS tier FROM evidence "
        f"WHERE entity_id = ? AND concept = ? AND COALESCE(period_start,'') = ? "
        f"AND COALESCE(period_end,'') = ? AND unit = ? AND {column} = ? AND {column} <= ?",
        (entity_id, concept, period_start, period_end, unit, instant, ts),
    )
    records = []
    for row in rows:
        if int(row["tier"]) != tier:
            continue
        payload = {key: row[key] for key in COLUMNS}
        records.append(EvidenceRecord(**payload))
    return records
