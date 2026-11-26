"""Reverse dependency index for derived computations.

Atlas records lineage on every derived evidence record, but lineage stored *inside* a
record only answers "what did this value come from". A compiler needs the inverse
question, asked from the other end: **when this evidence changes, which computations are
affected?** Answering that by scanning every derived record's JSON does not scale and
cannot be indexed.

``computation`` and ``computation_input`` (migration 002) are the indexed projection of
that lineage. This module owns them.

Design constraints, so the Phase 2 compiler can rely on it:

* One computation produces exactly one derived evidence record (``output_evidence`` is
  unique). Recomputing produces a *new* evidence record, which supersedes the old one;
  history is never rewritten.
* Every input is a real evidence id, enforced by foreign keys. A computation that names
  a missing input is rejected at write time rather than discovered later.
* Recording is idempotent: the same rule over the same output is stored once. Re-recording
  with different inputs replaces them atomically.
* Staleness is defined precisely: a computation is stale when an input it consumed has
  since been superseded, or the input no longer exists. "An input was re-asserted with the
  same value" is not staleness, mirroring the kernel's supersession rule.
* Nothing here derives a value. Derivation is the compiler's job; this module only
  records and answers dependency questions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from .core.errors import MissingDataError, ValidationError
from .core.temporal import iso, utcnow
from .evidence.model import EvidenceRecord
from .storage.db import Database

ENGINE = "atlas.dependencies.v1"


def computation_id(rule_id: str, output_evidence: str) -> str:
    """Deterministic id: the same rule over the same output is always one computation."""
    digest = hashlib.sha256(f"{rule_id}\x1f{output_evidence}".encode("utf-8")).hexdigest()[:24]
    return f"CMP-{digest.upper()}"


@dataclass(slots=True)
class InputRef:
    evidence_id: str
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {"evidence_id": self.evidence_id, "role": self.role}


@dataclass(slots=True)
class Computation:
    computation_id: str
    rule_id: str
    output_evidence_id: str
    knowledge_as_of: str | None
    mode: str | None
    engine: str | None
    created_at: str
    inputs: list[dict[str, Any]] = field(default_factory=list)
    output_concept: str | None = None
    output_value: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "computation_id": self.computation_id,
            "rule_id": self.rule_id,
            "output_evidence_id": self.output_evidence_id,
            "output_concept": self.output_concept,
            "output_value": self.output_value,
            "knowledge_as_of": self.knowledge_as_of,
            "mode": self.mode,
            "engine": self.engine,
            "created_at": self.created_at,
            "inputs": self.inputs,
        }


@dataclass(slots=True)
class ImpactReport:
    evidence_id: str
    direct: list[Computation]
    transitive: list[tuple[int, Computation]]
    stale: list[dict[str, Any]]
    affected_outputs: list[str]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "direct": [c.to_dict() for c in self.direct],
            "transitive": [{"depth": depth, **c.to_dict()} for depth, c in self.transitive],
            "stale": self.stale,
            "affected_outputs": self.affected_outputs,
            "direct_count": len(self.direct),
            "transitive_count": len(self.transitive),
            "notes": self.notes,
        }


class DependencyIndex:
    """Persistent reverse index over derived computations."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ writes
    def record(
        self,
        *,
        rule_id: str,
        output_evidence_id: str,
        inputs: Sequence[InputRef | tuple[str, str] | str],
        knowledge_as_of: str | None = None,
        mode: str | None = None,
        engine: str = ENGINE,
    ) -> Computation:
        if not rule_id or not str(rule_id).strip():
            raise ValidationError("a computation requires a rule id")
        output = self._evidence(output_evidence_id)
        if output.derivation_kind != "derived_calculation":
            raise ValidationError(
                "only derived calculations can be recorded as computations",
                evidence_id=output_evidence_id,
                derivation_kind=output.derivation_kind,
            )
        normalised: list[InputRef] = []
        for item in inputs:
            if isinstance(item, InputRef):
                ref = item
            elif isinstance(item, tuple):
                ref = InputRef(evidence_id=str(item[0]), role=str(item[1]))
            else:
                ref = InputRef(evidence_id=str(item), role="input")
            if not ref.evidence_id:
                raise ValidationError("computation input has no evidence id", rule_id=rule_id)
            if ref.evidence_id == output_evidence_id:
                raise ValidationError(
                    "a computation cannot consume its own output",
                    evidence_id=output_evidence_id,
                    rule_id=rule_id,
                )
            self._evidence(ref.evidence_id)  # existence is enforced before writing
            if not any(existing.evidence_id == ref.evidence_id and existing.role == ref.role for existing in normalised):
                normalised.append(ref)
        if not normalised:
            raise ValidationError(
                "a computation with no inputs cannot be invalidated; record its provenance instead",
                rule_id=rule_id,
                output_evidence=output_evidence_id,
            )

        identifier = computation_id(rule_id, output_evidence_id)
        existing = self.db.query_one(
            "SELECT rule_id FROM computation WHERE output_evidence = ?", (output_evidence_id,)
        )
        if existing is not None and existing["rule_id"] != rule_id:
            raise ValidationError(
                "this derived record was already attributed to a different rule",
                output_evidence=output_evidence_id,
                recorded_rule=existing["rule_id"],
                incoming_rule=rule_id,
            )
        created = iso(utcnow())
        self.db.execute(
            "INSERT INTO computation (computation_id, rule_id, output_evidence, knowledge_as_of, mode, engine, "
            "created_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(output_evidence) DO UPDATE SET "
            "rule_id=excluded.rule_id, knowledge_as_of=excluded.knowledge_as_of, mode=excluded.mode, "
            "engine=excluded.engine, created_at=excluded.created_at",
            (
                identifier,
                rule_id,
                output_evidence_id,
                iso(knowledge_as_of) if knowledge_as_of else None,
                mode,
                engine,
                created,
            ),
        )
        self.db.execute("DELETE FROM computation_input WHERE computation_id = ?", (identifier,))
        for ref in normalised:
            self.db.execute(
                "INSERT INTO computation_input (computation_id, evidence_id, role) VALUES (?,?,?)",
                (identifier, ref.evidence_id, ref.role),
            )
        return self.get(identifier)  # type: ignore[return-value]

    def record_for_derived(self, record: EvidenceRecord) -> Computation | None:
        """Record the computation described by a derived record's own lineage."""
        if record.derivation_kind != "derived_calculation":
            return None
        lineage = record.lineage
        entries = lineage.get("inputs") if isinstance(lineage.get("inputs"), list) else []
        inputs: list[InputRef] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            evidence_id = entry.get("evidence_id")
            if not evidence_id:
                continue
            role = str(entry.get("role") or entry.get("concept") or f"input{index}")
            inputs.append(InputRef(evidence_id=str(evidence_id), role=role))
        if not inputs:
            return None
        return self.record(
            rule_id=record.derivation_rule or f"atlas.derived.{record.concept}.unversioned",
            output_evidence_id=record.evidence_id,
            inputs=inputs,
            knowledge_as_of=record.observed_at,
            mode=None,
        )

    def backfill(self) -> int:
        """Index derived records that were stored before this index existed."""
        rows = self.db.query(
            "SELECT evidence_id FROM evidence WHERE derivation_kind = 'derived_calculation' "
            "AND transformation_lineage IS NOT NULL AND evidence_id NOT IN "
            "(SELECT output_evidence FROM computation)"
        )
        recorded = 0
        for row in rows:
            record = self._evidence(row["evidence_id"])
            if self.record_for_derived(record) is not None:
                recorded += 1
        return recorded

    # ------------------------------------------------------------------- reads
    def _evidence(self, evidence_id: str) -> EvidenceRecord:
        row = self.db.query_one(
            "SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)
        )
        if row is None:
            raise MissingDataError("no such evidence record", evidence_id=evidence_id)
        return EvidenceRecord.from_row(row)

    def get(self, computation_id_value: str) -> Computation | None:
        row = self.db.query_one(
            "SELECT * FROM computation WHERE computation_id = ?", (computation_id_value,)
        )
        if row is None:
            return None
        return self._hydrate(row)

    def for_output(self, evidence_id: str) -> Computation | None:
        row = self.db.query_one("SELECT * FROM computation WHERE output_evidence = ?", (evidence_id,))
        return self._hydrate(row) if row is not None else None

    def _hydrate(self, row: Any) -> Computation:
        inputs = [
            {
                "evidence_id": item["evidence_id"],
                "role": item["role"],
                "concept": item["concept"],
                "value": item["value_numeric"] if item["value_numeric"] is not None else item["value_text"],
                "unit": item["unit"],
            }
            for item in self.db.query(
                "SELECT ci.evidence_id, ci.role, e.concept, e.value_numeric, e.value_text, e.unit "
                "FROM computation_input ci LEFT JOIN evidence e ON e.evidence_id = ci.evidence_id "
                "WHERE ci.computation_id = ? ORDER BY ci.role, ci.evidence_id",
                (row["computation_id"],),
            )
        ]
        output = self.db.query_one(
            "SELECT concept, value_numeric, value_text FROM evidence WHERE evidence_id = ?",
            (row["output_evidence"],),
        )
        return Computation(
            computation_id=row["computation_id"],
            rule_id=row["rule_id"],
            output_evidence_id=row["output_evidence"],
            knowledge_as_of=row["knowledge_as_of"],
            mode=row["mode"],
            engine=row["engine"],
            created_at=row["created_at"],
            inputs=inputs,
            output_concept=output["concept"] if output is not None else None,
            output_value=(
                (output["value_numeric"] if output["value_numeric"] is not None else output["value_text"])
                if output is not None
                else None
            ),
        )

    def dependents(self, evidence_id: str) -> list[Computation]:
        """Computations whose inputs include ``evidence_id`` (direct dependents)."""
        rows = self.db.query(
            "SELECT c.* FROM computation c JOIN computation_input ci ON ci.computation_id = c.computation_id "
            "WHERE ci.evidence_id = ? ORDER BY c.rule_id, c.computation_id",
            (evidence_id,),
        )
        return [self._hydrate(row) for row in rows]

    def transitive_dependents(self, evidence_id: str, *, max_depth: int = 8) -> list[tuple[int, Computation]]:
        """Dependents of dependents, up to ``max_depth`` levels."""
        if max_depth < 1:
            raise ValidationError("max_depth must be at least 1", max_depth=max_depth)
        frontier = [evidence_id]
        seen: set[str] = set()
        results: list[tuple[int, Computation]] = []
        for depth in range(1, max_depth + 1):
            next_frontier: list[str] = []
            for current in frontier:
                for computation in self.dependents(current):
                    if computation.computation_id in seen:
                        continue
                    seen.add(computation.computation_id)
                    results.append((depth, computation))
                    next_frontier.append(computation.output_evidence_id)
            if not next_frontier:
                break
            frontier = next_frontier
        return results

    def stale(self, evidence_ids: Sequence[str] | None = None) -> list[dict[str, Any]]:
        """Computations whose inputs have since been superseded (or disappeared).

        A re-assertion of the same value does not mark an input stale, because the kernel
        does not supersede unchanged values either.
        """
        params: list[Any] = []
        where = ""
        if evidence_ids:
            where = f" AND ci.evidence_id IN ({', '.join('?' for _ in evidence_ids)})"
            params.extend(evidence_ids)
        rows = self.db.query(
            "SELECT DISTINCT c.computation_id FROM computation c "
            "JOIN computation_input ci ON ci.computation_id = c.computation_id" + where,
            params,
        )
        stale: list[dict[str, Any]] = []
        for row in rows:
            computation = self.get(row["computation_id"])
            if computation is None:  # pragma: no cover - defensive
                continue
            reasons: list[dict[str, Any]] = []
            for entry in computation.inputs:
                input_id = entry["evidence_id"]
                exists = self.db.query_one("SELECT 1 FROM evidence WHERE evidence_id = ?", (input_id,))
                if exists is None:
                    reasons.append({"input": input_id, "reason": "input_missing"})
                    continue
                newer = self.db.query(
                    "SELECT superseding_id FROM evidence_supersession WHERE superseded_id = ? "
                    "ORDER BY created_at DESC",
                    (input_id,),
                )
                if newer:
                    reasons.append(
                        {
                            "input": input_id,
                            "reason": "input_superseded",
                            "superseded_by": [r["superseding_id"] for r in newer],
                        }
                    )
            if reasons:
                stale.append({**computation.to_dict(), "stale_reasons": reasons})
        return stale

    def impact(self, evidence_id: str) -> ImpactReport:
        direct = self.dependents(evidence_id)
        transitive = self.transitive_dependents(evidence_id)
        stale = self.stale([evidence_id])
        outputs: list[str] = []
        for computation in direct:
            if computation.output_evidence_id not in outputs:
                outputs.append(computation.output_evidence_id)
        notes: list[str] = []
        if not direct and not transitive:
            notes.append(
                "no derived computation consumes this evidence; it may still be used directly by a report"
            )
        if stale:
            notes.append(
                f"{len(stale)} computation(s) consumed an input that has since been superseded"
            )
        return ImpactReport(
            evidence_id=evidence_id,
            direct=direct,
            transitive=transitive,
            stale=stale,
            affected_outputs=outputs,
            notes=notes,
        )

    def integrity(self) -> dict[str, Any]:
        """Structural checks over the index itself."""
        findings: list[dict[str, Any]] = []
        dangling = self.db.query(
            "SELECT ci.computation_id, ci.evidence_id FROM computation_input ci "
            "LEFT JOIN evidence e ON e.evidence_id = ci.evidence_id WHERE e.evidence_id IS NULL"
        )
        for row in dangling:
            findings.append(
                {
                    "code": "dangling_computation_input",
                    "severity": "error",
                    "computation_id": row["computation_id"],
                    "evidence_id": row["evidence_id"],
                }
            )
        non_derived = self.db.query(
            "SELECT c.computation_id, c.output_evidence, e.derivation_kind FROM computation c "
            "JOIN evidence e ON e.evidence_id = c.output_evidence "
            "WHERE e.derivation_kind != 'derived_calculation'"
        )
        for row in non_derived:
            findings.append(
                {
                    "code": "computation_output_not_derived",
                    "severity": "error",
                    "computation_id": row["computation_id"],
                    "derivation_kind": row["derivation_kind"],
                }
            )
        inputless = self.db.query(
            "SELECT c.computation_id FROM computation c WHERE NOT EXISTS "
            "(SELECT 1 FROM computation_input ci WHERE ci.computation_id = c.computation_id)"
        )
        for row in inputless:
            findings.append(
                {
                    "code": "computation_without_inputs",
                    "severity": "error",
                    "computation_id": row["computation_id"],
                }
            )
        return {
            "computations": int(self.db.scalar("SELECT COUNT(*) FROM computation", default=0) or 0),
            "inputs": int(self.db.scalar("SELECT COUNT(*) FROM computation_input", default=0) or 0),
            "findings": findings,
            "ok": not findings,
        }

    def summary(self) -> dict[str, Any]:
        by_rule = {
            row["rule_id"]: row["n"]
            for row in self.db.query(
                "SELECT rule_id, COUNT(*) AS n FROM computation GROUP BY rule_id ORDER BY n DESC"
            )
        }
        return {"by_rule": by_rule, **self.integrity()}
