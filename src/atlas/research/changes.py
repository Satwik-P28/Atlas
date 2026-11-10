"""Deterministic, dependency-aware evidence change detection for saved research.

A newer filing does not make an old memo false. This module reports exactly which claims
depend on a source that changed, what the original and replacement values are, and whether a
replay is possible. It never rewrites a stored memo and never silently re-points a claim at
new evidence.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..core.temporal import iso, utcnow
from ..fec.compiler import COMPILER_VERSION
from ..storage.db import Database

SCHEMA = "atlas.research_change_report.v1"
CHANGE_CATEGORIES = (
    "unchanged",
    "new_relevant_evidence",
    "superseded_evidence",
    "revised_market_observation",
    "missing_dependency",
    "model_version_incompatible",
    "rights_changed",
    "requires_review",
)
REDISTRIBUTABLE = frozenset({"public_domain", "project_authored", "permitted"})


def _claims_for(memo: dict[str, Any], predicate) -> list[dict[str, Any]]:
    return [
        {
            "claim_id": claim["claim_id"],
            "key": claim["key"],
            "claim_type": claim["claim_type"],
            "statement": claim["statement"],
            "value": claim.get("value"),
        }
        for claim in memo["claims"] if predicate(claim)
    ]


def check(db: Database, memo: dict[str, Any], *, object_id: str | None = None) -> dict[str, Any]:
    manifest = memo.get("manifest") or {}
    evidence_ids = list(manifest.get("evidence_dependencies") or [])
    cutoff = memo.get("cutoff")
    issuer_id = (memo.get("issuer") or {}).get("issuer_id")
    findings: list[dict[str, Any]] = []
    categories: list[str] = []

    def add(category: str, *, detail: str, **payload: Any) -> None:
        if category not in categories:
            categories.append(category)
        findings.append({"category": category, "detail": detail, **payload})

    cited: dict[str, dict[str, Any]] = {}
    if evidence_ids:
        marks = ",".join("?" for _ in evidence_ids)
        for row in db.query(
            "SELECT evidence_id, concept, period_end, value_numeric, unit, availability_time, "
            "revision_kind, supersedes, source_id FROM evidence WHERE evidence_id IN ("
            + marks + ")",
            evidence_ids,
        ):
            cited[row["evidence_id"]] = dict(row)
    missing = [eid for eid in evidence_ids if eid not in cited]
    for evidence_id in missing:
        affected = _claims_for(memo, lambda claim, eid=evidence_id: eid in claim["evidence_ids"])
        add(
            "missing_dependency",
            detail=f"cited evidence {evidence_id} is not present in this database",
            evidence_id=evidence_id,
            affected_claims=affected,
            replay_possible=False,
        )

    replacements: list[dict[str, Any]] = []
    if cited:
        marks = ",".join("?" for _ in cited)
        for row in db.query(
            "SELECT evidence_id, concept, period_end, value_numeric, unit, availability_time, "
            "revision_kind, supersedes, accession_number, form_type FROM evidence "
            "WHERE supersedes IN (" + marks + ") ORDER BY availability_time, evidence_id",
            sorted(cited),
        ):
            original = cited[row["supersedes"]]
            affected = _claims_for(
                memo, lambda claim, old=row["supersedes"]: old in claim["evidence_ids"]
            )
            replacements.append({
                "original_evidence_id": row["supersedes"],
                "replacement_evidence_id": row["evidence_id"],
                "concept": row["concept"],
                "period_end": row["period_end"],
                "original_value": original["value_numeric"],
                "replacement_value": row["value_numeric"],
                "revision_kind": row["revision_kind"],
                "replacement_available_at": row["availability_time"],
                "accession_number": row["accession_number"],
                "form_type": row["form_type"],
            })
            add(
                "superseded_evidence",
                detail=(
                    f"{row['supersedes']} was superseded by {row['evidence_id']} "
                    f"({row['revision_kind']}); the stored memo keeps the original value"
                ),
                original_evidence_id=row["supersedes"],
                replacement_evidence_id=row["evidence_id"],
                original_value=original["value_numeric"],
                replacement_value=row["value_numeric"],
                affected_claims=affected,
                replay_possible=True,
                auto_replay_performed=False,
            )

    if issuer_id and cutoff:
        marks = ",".join("?" for _ in evidence_ids) or "''"
        for row in db.query(
            "SELECT e.evidence_id, e.concept, e.period_end, e.availability_time "
            "FROM evidence e WHERE e.entity_id = ? AND e.availability_time > ? "
            "AND e.evidence_id NOT IN (" + marks + ") "
            "AND e.supersedes IS NULL ORDER BY e.availability_time DESC LIMIT 25",
            [issuer_id, cutoff, *evidence_ids],
        ):
            add(
                "new_relevant_evidence",
                detail=(
                    f"new evidence {row['evidence_id']} ({row['concept']}, "
                    f"{row['period_end']}) became available after the memo cutoff"
                ),
                evidence_id=row["evidence_id"],
                concept=row["concept"],
                period_end=row["period_end"],
                availability_time=row["availability_time"],
                affected_claims=_claims_for(
                    memo,
                    lambda claim, concept=row["concept"], period=row["period_end"]: (
                        claim.get("concept") == concept
                        and (claim.get("period") or {}).get("end") == period
                    ),
                ),
                replay_possible=True,
                auto_replay_performed=False,
            )

    for pin in manifest.get("observation_pins") or []:
        security_id = pin.get("security_id")
        session = pin.get("session")
        if not security_id or not session:
            continue
        latest = db.scalar(
            "SELECT MAX(revision_seq) FROM bar WHERE security_id = ? AND substr(ts_utc,1,10) = ?",
            (security_id, str(session)[:10]), default=None,
        )
        recorded = pin.get("revision")
        if latest is not None and recorded is not None and int(latest) > int(recorded):
            add(
                "revised_market_observation",
                detail=(
                    f"a newer revision of the {session} observation for {security_id} exists "
                    f"(recorded revision {recorded}, stored maximum {latest})"
                ),
                security_id=security_id,
                session=session,
                recorded_revision=recorded,
                stored_revision=latest,
                affected_claims=_claims_for(
                    memo, lambda claim, obs=pin.get("observation_id"): obs in claim["observation_ids"]
                ),
                replay_possible=True,
                auto_replay_performed=False,
            )

    recorded_compiler = manifest.get("compiler_version")
    if recorded_compiler and recorded_compiler != COMPILER_VERSION:
        add(
            "model_version_incompatible",
            detail=(
                f"the memo recorded compiler {recorded_compiler}; the current implementation is "
                f"{COMPILER_VERSION}"
            ),
            recorded_compiler=recorded_compiler,
            current_compiler=COMPILER_VERSION,
            affected_claims=_claims_for(memo, lambda claim: claim["claim_type"] == "model_output"),
            replay_possible=False,
        )

    rights = memo.get("rights") or {}
    for blocked in rights.get("blocked_sources") or []:
        add(
            "rights_changed",
            detail=(
                f"source {blocked.get('source_id')} does not permit redistribution "
                f"({blocked.get('redistribution')}); the memo cannot be exported"
            ),
            source_id=blocked.get("source_id"),
            redistribution=blocked.get("redistribution"),
            affected_claims=[],
            replay_possible=False,
        )

    review_categories = {
        "missing_dependency", "superseded_evidence", "revised_market_observation",
        "model_version_incompatible", "rights_changed",
    }
    blocking = [
        finding for finding in findings
        if finding.get("affected_claims") or finding["category"] in review_categories
    ]
    status = "unchanged" if not blocking else "requires_review"
    if not findings:
        categories.append("unchanged")
    affected = {
        claim["claim_id"]
        for finding in findings
        for claim in finding.get("affected_claims") or []
    }
    return {
        "schema": SCHEMA,
        "checked_at": iso(utcnow()),
        "object_id": object_id,
        "memo_content_hash": memo.get("content_hash"),
        "issuer_id": issuer_id,
        "cutoff": cutoff,
        "status": status,
        "review_required": bool(blocking),
        "categories": [category for category in CHANGE_CATEGORIES if category in categories],
        "findings": findings,
        "impact": {
            "claims_affected": sorted(affected),
            "claims_total": len(memo.get("claims") or []),
            "claims_unaffected": len(memo.get("claims") or []) - len(affected),
        },
        "replay": {
            "automatic": False,
            "note": (
                "Atlas reports the change and leaves the stored memo untouched. Creating a new "
                "version is a separate, explicit action that re-runs the analysis at a stated "
                "cutoff."
            ),
        },
        "note": (
            "A new filing does not invalidate unrelated analysis, and a provider correction does "
            "not rewrite a saved memo. Only findings that name a dependent claim require review."
        ),
    }


def affected_claims(report: dict[str, Any]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for finding in report.get("findings") or []:
        for claim in finding.get("affected_claims") or []:
            seen.setdefault(claim["claim_id"], claim)
    return list(seen.values())


def summarise(report: dict[str, Any]) -> str:
    categories: Iterable[str] = report.get("categories") or []
    return (
        f"{report.get('status')}: " + ", ".join(categories)
        + f" ({len(report.get('findings') or [])} finding(s))"
    )
