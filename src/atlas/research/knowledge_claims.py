"""Source-grounded qualitative claims built on the Financial Knowledge Engine.

The numeric memo pipeline (``atlas.research_memo.v1``) verifies financial facts against
the evidence kernel. This module adds the qualitative counterpart without touching the
numeric contract: a document claim is a separately versioned object that carries an exact
passage citation, an explicit epistemic status and a verification block.

The distinction the specification requires is enforced here rather than described:

* ``observed_fact`` — must resolve to a passage whose bytes and span match the archive.
* ``derived_calculation`` — out of scope for this module; numeric claims stay in claims.py.
* ``analyst_inference`` — interpretation; its citations are checked but it is not a fact.
* ``hypothesis`` — not established by its citation.
* ``unsupported`` — the engine could not ground it; recorded as a first-class outcome.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

from ..core.errors import ValidationError
from ..core.temporal import iso, utcnow
from ..storage.db import Database
from .knowledge import KnowledgeEngine

CLAIM_SCHEMA = "atlas.knowledge.claim.v1"
CLAIM_VERSION = "1.0.0"
EPISTEMIC_STATUSES = (
    "observed_fact",
    "analyst_inference",
    "hypothesis",
    "unsupported",
)
EXPORTABLE_RIGHTS = {"public_domain", "project_authored", "permitted"}
NEGATION = re.compile(
    r"\b(no longer|did not|does not|not material|ceased|terminated|without material|"
    r"no assurance|removed|reversed|reclassified)\b",
    re.IGNORECASE,
)


def claim_id(issuer_id: str, key: str) -> str:
    digest = hashlib.sha256(f"{issuer_id}|document|{key}".encode("utf-8")).hexdigest()
    return f"KCL-{digest[:16]}"


def _citation(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": result["document_id"],
        "unit_id": result["unit_id"],
        "accession": result["accession"],
        "form_type": result["form_type"],
        "is_amendment": result["is_amendment"],
        "section_path": result["section_path"],
        "char_start": result["char_start"],
        "char_end": result["char_end"],
        "unit_sha256": result["body_sha256"],
        "availability_time": result["availability_time"],
        "availability_precision": result["availability_precision"],
        "rights": result["rights"],
        "resolution": "exact_span",
        "source_url": result["resolve_original"],
    }


def build_document_claim(
    engine: KnowledgeEngine,
    *,
    issuer_id: str,
    cutoff: str,
    key: str,
    question: str,
    epistemic_status: str,
    policy: str = "public_available",
    forms: Iterable[str] | None = None,
    limit: int = 4,
    max_chars: int = 400,
) -> dict[str, Any]:
    if epistemic_status not in EPISTEMIC_STATUSES:
        raise ValidationError("unknown epistemic status", status=epistemic_status,
                              supported=list(EPISTEMIC_STATUSES))
    search = engine.search(question, issuer_id=issuer_id, cutoff=cutoff, policy=policy,
                           forms=forms, limit=limit)
    abstained = search["abstained"] or not search["results"]
    # An abstention carries no citation. Attaching the incidental BM25 matches would
    # let an unsupported question look sourced, and a citation is a claim of support.
    citations = [] if abstained else [_citation(item) for item in search["results"][:limit]]
    body = citations and search["results"][0]
    if abstained:
        statement = (
            f"No archived passage in this issuer's filings answers “{question}” at the "
            f"information cutoff {cutoff}. The question is recorded as unsupported rather than answered."
        )
        status = "unsupported"
    else:
        # The snippet carries match markers for the UI; a stored quotation must be
        # the source text, not the rendered highlight.
        excerpt = (body["excerpt"] or body["unit_id"]).replace("⟦", "").replace("⟧", "")
        statement = f"{body['form_type']} {body['accession']} · {body['section_path']}: “{excerpt}”"
        status = epistemic_status
    claim = {
        "schema": CLAIM_SCHEMA,
        "claim_version": CLAIM_VERSION,
        "claim_id": claim_id(issuer_id, key),
        "key": key,
        "issuer_id": issuer_id,
        "question": question,
        "cutoff": cutoff,
        "policy": policy,
        "epistemic_status": status,
        "statement": statement[: max_chars * 2],
        "statement_kind": "abstention" if abstained else "verbatim_excerpt",
        "citations": citations,
        "counter_evidence": [] if abstained else _counter_evidence(engine, search),
        "search": {
            "retriever": search["plan"]["retriever"],
            "count": search["count"],
            "abstained": search["abstained"],
            "abstention_reason": search["abstention_reason"],
            "excluded_later_than_cutoff": search["excluded"]["later_than_cutoff"],
            "latency_ms": search["latency_ms"],
        },
        "limitations": (
            ["No grounded passage was found; absence of a passage is not proof the disclosure "
             "does not exist elsewhere in the corpus."] if abstained else
            ["A verbatim excerpt is evidence of what the filing says, not that the assertion is "
             "economically true.", "Passages are retrieved lexically; paraphrased disclosure with "
             "different vocabulary may be missed."]
        ),
        "generated_at": iso(utcnow()),
    }
    claim["verification"] = verify_document_claim(engine, claim)
    return claim


def _counter_evidence(engine: KnowledgeEngine, search: dict[str, Any]) -> list[dict[str, Any]]:
    """Other passages containing negation language for the same query terms.

    This is a transparent lexical heuristic, not a contradiction detector with semantic
    understanding. It surfaces candidates for review and never asserts a conflict.
    """
    out: list[dict[str, Any]] = []
    for item in search["results"][1:8]:
        row = engine.db.query_one("SELECT body FROM knowledge_unit WHERE unit_id = ?",
                                 (item["unit_id"],))
        if row and NEGATION.search(row["body"]):
            out.append({
                "unit_id": item["unit_id"],
                "accession": item["accession"],
                "section_path": item["section_path"],
                "matched": NEGATION.search(row["body"]).group(0).lower(),
                "resolution": "exact_span",
                "note": "Negation language near the query terms; review before treating as a conflict.",
            })
    return out


def verify_document_claim(engine: KnowledgeEngine, claim: dict[str, Any]) -> dict[str, Any]:
    db = engine.db
    checks: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    status = claim["epistemic_status"]
    if status == "unsupported":
        return {
            "outcome": "unsupported",
            "checks": [{"name": "grounding", "passed": False,
                        "detail": "no passage satisfied the query at the cutoff"}],
            "diagnostics": diagnostics,
            "export_allowed": True,
        }
    resolved = 0
    for citation in claim["citations"]:
        unit = db.query_one(
            "SELECT u.body, u.sha256, u.char_start, u.char_end, d.issuer_id, d.availability_time, "
            "d.availability_precision, d.rights, d.document_id "
            "FROM knowledge_unit u JOIN knowledge_document d ON d.document_id = u.document_id "
            "WHERE u.unit_id = ?", (citation["unit_id"],),
        )
        if unit is None:
            diagnostics.append({"code": "passage_missing", "unit_id": citation["unit_id"]})
            continue
        if unit["document_id"] != citation["document_id"]:
            diagnostics.append({"code": "document_mismatch", "unit_id": citation["unit_id"]})
            continue
        if unit["issuer_id"] != claim["issuer_id"]:
            diagnostics.append({"code": "issuer_mismatch", "unit_id": citation["unit_id"],
                               "detail": f"passage belongs to {unit['issuer_id']}"})
            continue
        # Recompute from the stored body: a stale hash column must not be able to
        # certify text that no longer matches what the citation quoted.
        recomputed = hashlib.sha256(unit["body"].encode("utf-8")).hexdigest()
        if recomputed != unit["sha256"]:
            diagnostics.append({"code": "passage_corruption", "unit_id": citation["unit_id"],
                               "detail": "stored body no longer matches its recorded hash"})
            continue
        if recomputed != citation["unit_sha256"]:
            diagnostics.append({"code": "passage_hash_mismatch", "unit_id": citation["unit_id"]})
            continue
        if (unit["char_start"], unit["char_end"]) != (citation["char_start"], citation["char_end"]):
            diagnostics.append({"code": "span_mismatch", "unit_id": citation["unit_id"]})
            continue
        if unit["availability_time"] > claim["cutoff"]:
            diagnostics.append({"code": "availability_after_cutoff", "unit_id": citation["unit_id"],
                               "detail": f"{unit['availability_time']} > {claim['cutoff']}"})
            continue
        if unit["availability_precision"] != "exact":
            diagnostics.append({
                "code": "availability_date_precision",
                "unit_id": citation["unit_id"],
                "detail": "the source proves a filing date, not an intraday publication time",
            })
        if unit["rights"] not in EXPORTABLE_RIGHTS:
            diagnostics.append({"code": "restricted_source", "unit_id": citation["unit_id"],
                               "detail": f"rights {unit['rights']} block byte export"})
        resolved += 1
    complete = resolved == len(claim["citations"]) and resolved > 0
    checks.append({
        "name": "citation_resolution",
        "passed": complete,
        "detail": f"{resolved}/{len(claim['citations'])} citations resolve to an exact, "
                  "issuer-matched, pre-cutoff span",
    })
    if status == "observed_fact":
        checks.append({"name": "epistemic_boundary", "passed": True,
                       "detail": "stated as an observed fact with a verbatim citation"})
    elif status == "analyst_inference":
        checks.append({"name": "epistemic_boundary", "passed": True,
                       "detail": "recorded as an inference, never as an established fact"})
    elif status == "hypothesis":
        checks.append({"name": "epistemic_boundary", "passed": True,
                       "detail": "recorded as a hypothesis not established by the citation"})
    outcome = "verified" if complete else "partially_verified" if resolved else "missing_evidence"
    if any(item["code"] == "availability_date_precision" for item in diagnostics):
        outcome = "unverifiable_historical_availability" if complete else outcome
    if any(item["code"] == "restricted_source" for item in diagnostics):
        outcome = "restricted_source" if complete else outcome
    if status in {"analyst_inference", "hypothesis"}:
        checks.append({"name": "factual_outcome", "passed": True,
                       "detail": f"`{status}` is not presented as an observed fact"})
    return {
        "outcome": outcome,
        "checks": checks,
        "diagnostics": diagnostics,
        "export_allowed": not any(item["code"] == "restricted_source" for item in diagnostics),
    }


def revision_report(
    engine: KnowledgeEngine,
    *,
    earlier_document_id: str,
    later_document_id: str,
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    comparison = engine.compare(earlier_document_id, later_document_id)
    affected_units = set(comparison["affected_unit_ids"])
    impacted = []
    for claim in claims:
        touched = [c["unit_id"] for c in claim["citations"] if c["unit_id"] in affected_units]
        if not touched:
            continue
        impacted.append({
            "claim_id": claim["claim_id"],
            "key": claim["key"],
            "epistemic_status": claim["epistemic_status"],
            "reason": "cited_passage_section_changed",
            "unit_ids": touched,
            "requires_review": True,
        })
    significance = []
    for name in comparison["added_sections"]:
        significance.append({"section": name, "rule": "section_present_only_in_later_filing",
                             "level": "review"})
    for name in comparison["removed_sections"]:
        significance.append({"section": name, "rule": "section_present_only_in_earlier_filing",
                             "level": "high"})
    for name in comparison["changed_sections"]:
        significance.append({"section": name, "rule": "section_text_changed", "level": "review"})
    return {
        "schema": "atlas.knowledge.revision.v1",
        "comparison": comparison,
        "impacted_claims": impacted,
        "significance": significance,
        "historical_note": (
            "The earlier memo remains valid for what was knowable at its cutoff. This report "
            "describes what later information changed; it does not rewrite the earlier analysis."
        ),
        "rules_note": (
            "Significance is derived from structural rules (section added, removed or changed), "
            "not from a model-generated confidence score."
        ),
    }


def attach_document_claims(memo: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach grounded document claims to an existing research memo.

    Additive by design: ``atlas.research_memo.v1`` keeps its numeric claims, integrity block and
    sections untouched, and gains an optional ``document_claims`` list. The memo hash is
    recomputed with the existing function so reopen/export verification keeps working, and no
    numeric claim, formula or evidence id is altered.
    """
    from .memo import memo_hash

    if not isinstance(memo, dict):
        raise ValidationError("memo payload must be an object")
    updated = dict(memo)
    updated["document_claims"] = list(claims)
    verified = sum(1 for claim in claims if claim.get("verification", {}).get("outcome") == "verified")
    updated["document_claim_summary"] = {
        "total": len(claims),
        "verified": verified,
        "unsupported": sum(1 for claim in claims if claim.get("epistemic_status") == "unsupported"),
        "restricted": sum(
            1 for claim in claims
            if claim.get("verification", {}).get("outcome") == "restricted_source"
        ),
        "schema": CLAIM_SCHEMA,
    }
    updated["content_hash"] = memo_hash(updated)
    updated["memo_id"] = f"RMO-{updated['content_hash'][:16]}"
    return updated


def claim_to_json(claim: dict[str, Any]) -> str:
    return json.dumps(claim, sort_keys=True, ensure_ascii=False)


__all__ = [
    "CLAIM_SCHEMA", "CLAIM_VERSION", "EPISTEMIC_STATUSES", "build_document_claim",
    "verify_document_claim", "revision_report", "claim_id", "attach_document_claims",
]
