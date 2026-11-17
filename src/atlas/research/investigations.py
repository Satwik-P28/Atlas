"""Immutable, versioned price-movement investigations on the UROS contract.

A saved investigation is a research object of kind ``price_investigation``. Saving
reuses :class:`atlas.research.objects.ResearchObjectStore`: the document is validated,
content-hashed and stored with a version, so it can be reopened, compared and exported
through the contracts that already exist.

What is preserved: the exact market observations (ids, revisions, content hashes), the
historical cutoff, the company-event evidence and document spans, the model assumptions
and calculations, the source-rights decision and the full reproducibility manifest.

What is never done: an existing version is not overwritten. Re-running an investigation
against later stored state produces a **change-impact report** that names what moved —
a provider price revision, a new or amended filing, a changed document, a changed
calculation version — beside the original hash.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..core.errors import ValidationError
from ..core.temporal import iso, utcnow
from ..storage.db import Database
from . import move_intelligence
from .objects import SCHEMA_VERSION, ResearchObjectStore

KIND = "price_investigation"
DOCUMENT_SCHEMA = "atlas.price_investigation.v1"


def investigation_name(report: Mapping[str, Any]) -> str:
    selection = report["selection"]
    ticker = selection.get("ticker") or selection.get("security_id")
    return f"{ticker} {selection['start_session']}..{selection['end_session']}"


def _knowledge_as_of(report: Mapping[str, Any]) -> str:
    """The instant the investigation's claims are as-of.

    A historical reconstruction is as-of its cutoff (end of that UTC day). A
    retrospective investigation uses the last selected session's end of day, because
    that is the newest market evidence it could contain.
    """
    request = report["request"]
    if request.get("information_cutoff"):
        return f"{request['information_cutoff']}T23:59:59Z"
    return f"{report['selection']['end_session']}T23:59:59Z"


def build_document(
    report: Mapping[str, Any],
    *,
    name: str | None = None,
    version: str = "1.0.0",
    status: str = "validated",
) -> dict[str, Any]:
    """Turn an engine report into a UROS ``price_investigation`` document."""
    selection = report["selection"]
    statistics = report["price_statistics"]
    request = report["request"]
    source_ids = sorted(
        {
            source["source_id"]
            for source in report["rights"]["sources"]
            if source.get("source_id")
        }
    )
    spans = [
        span
        for event in report["events"]["items"]
        for span in (event.get("passages") or [])
    ]
    document: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "name": name or investigation_name(report),
        "version": version,
        "status": status,
        "description": (
            f"Price-movement investigation of {selection.get('ticker') or selection['security_id']} "
            f"over {selection['start_session']}..{selection['end_session']} on the "
            f"{statistics['basis_label']} basis, with its evidence, calculations and rights."
        ),
        "as_of": _knowledge_as_of(report),
        "mode": "public_available",
        "evidence_ids": [],
        "source_ids": source_ids,
        "assumptions": [
            f"return basis: {statistics['requested_basis']}",
            f"return convention: {statistics['return_convention']}",
            f"one provider held constant: {selection['series'].get('source_id')}",
            "market model: single-factor OLS on aligned daily simple returns",
            f"annualisation: {statistics.get('annualization') or 'not applicable'}",
        ],
        "limitations": list(report["limitations"]) + [
            "a saved investigation is a statement about the stored state at its creation; "
            "later corrections do not modify it",
            "no news, consensus or macro-release source is licensed, so the event timeline is "
            "incomplete by construction",
        ],
        "spec": {
            "security_id": selection["security_id"],
            "issuer_id": selection.get("issuer_id"),
            "ticker": selection.get("ticker"),
            "interval": {
                "requested_start": selection["requested_start"],
                "requested_end": selection["requested_end"],
                "start_session": selection["start_session"],
                "end_session": selection["end_session"],
                "sessions": selection["sessions"],
                "timeframe": selection["timeframe"],
                "timezone": selection["timezone"],
            },
            "historical_cutoff": request.get("information_cutoff"),
            "mode": request.get("mode"),
            "price_basis": request.get("price_basis"),
            "request": dict(request),
            "statistics": dict(statistics),
            "benchmark": dict(report["benchmark"]),
            "market_model": dict(report["market_model"]),
            "peers": list(report["peers"]),
            "events": list(report["events"]["items"]),
            "evidence_coverage": dict(report["events"]["coverage"]),
            "observations": list(report["observations"]),
            "hypotheses": list(report["hypotheses"]),
            "analysis": dict(report.get("analysis") or {}),
            "rights": dict(report["rights"]),
            # UROS forbids an executable-looking key anywhere in a document, so a
            # diagnostic's `code` is stored as `warning_code`.
            "warnings": [
                {
                    "warning_code": warning.get("code"),
                    "message": warning.get("message"),
                    "context": warning.get("context"),
                }
                for warning in report["warnings"]
            ],
            "refusals": [
                {
                    "refusal_code": refusal.get("code"),
                    "reason": refusal.get("reason"),
                    "detail": refusal.get("detail"),
                }
                for refusal in report["refusals"]
            ],
            "reproducibility": dict(report["reproducibility"]),
            "calculations": {
                "engine": dict(report["engine"]),
                "contract": report["schema"],
                "calculation": report["reproducibility"]["components"]["calculation"],
            },
            "manifest": {
                "selected_series": report["reproducibility"]["components"]["selected_series"],
                "context_series": report["reproducibility"]["components"]["context_series"],
                "benchmark": report["reproducibility"]["components"]["benchmark"],
                "market_model": report["reproducibility"]["components"]["market_model"],
                "peers": report["reproducibility"]["components"]["peers"],
                "corporate_actions": report["reproducibility"]["components"]["corporate_actions"],
                "document_spans": spans,
            },
        },
    }
    return document


def save(
    db: Database,
    report: Mapping[str, Any],
    *,
    name: str | None = None,
    version: str = "1.0.0",
    owner_id: str = "local",
) -> dict[str, Any]:
    """Persist an investigation immutably. A duplicate name/version is refused."""
    document = build_document(report, name=name, version=version)
    stored = ResearchObjectStore(db).create(document, owner_id=owner_id)
    return {
        "object_id": stored["object_id"],
        "kind": stored["kind"],
        "name": stored["name"],
        "version": stored["version"],
        "status": stored["status"],
        "content_hash": stored["content_hash"],
        "created_at": stored["created_at"],
        "as_of": document["as_of"],
        "rights": report["rights"],
        "reproducibility_hash": report["reproducibility"]["hash"],
    }


def _request_from_object(stored: Mapping[str, Any]) -> move_intelligence.ExplanationRequest:
    spec = stored["document"]["spec"]
    request = spec.get("request") or {}
    return move_intelligence.ExplanationRequest(
        security_id=spec["security_id"],
        start_session=spec["interval"]["requested_start"],
        end_session=spec["interval"]["requested_end"],
        timeframe=request.get("timeframe", "1d"),
        timezone=request.get("timezone", move_intelligence.DEFAULT_TIMEZONE),
        price_basis=request.get("price_basis", spec.get("price_basis", "split_adjusted")),
        mode=request.get("mode", spec.get("mode", move_intelligence.MODE_RETROSPECTIVE)),
        information_cutoff=request.get("information_cutoff"),
        benchmark_security_id=request.get("benchmark_security_id"),
        peer_security_ids=tuple(request.get("peer_security_ids") or ()),
        estimation_sessions=request.get("estimation_sessions", move_intelligence.DEFAULT_ESTIMATION_SESSIONS),
        evidence_limit=request.get("evidence_limit", 50),
        return_convention=request.get("return_convention", "auto"),
    )


def reproduce(db: Database, object_id: str) -> dict[str, Any]:
    """Recompute a saved investigation from stored state and compare its hash."""
    stored = ResearchObjectStore(db).get(object_id)
    if stored["kind"] != KIND:
        raise ValidationError(
            "this research object is not a price investigation", object_id=object_id, kind=stored["kind"]
        )
    request = _request_from_object(stored)
    current = move_intelligence.explain_range(db, request)
    original_hash = stored["document"]["spec"]["reproducibility"]["hash"]
    current_hash = current["reproducibility"]["hash"]
    return {
        "object_id": object_id,
        "content_hash": stored["content_hash"],
        "original_reproducibility_hash": original_hash,
        "current_reproducibility_hash": current_hash,
        "matches": original_hash == current_hash,
        "recomputed_at": current["selection"]["end_session"],
    }


def _index(items: Any, key: str) -> dict[str, Mapping[str, Any]]:
    return {str(item[key]): item for item in items}


def impact(db: Database, object_id: str) -> dict[str, Any]:
    """A change-impact report. The stored investigation is never overwritten."""
    stored = ResearchObjectStore(db).get(object_id)
    if stored["kind"] != KIND:
        raise ValidationError(
            "this research object is not a price investigation", object_id=object_id, kind=stored["kind"]
        )
    document = stored["document"]
    original = document["spec"]
    current = move_intelligence.explain_range(db, _request_from_object(stored))
    original_hash = original["reproducibility"]["hash"]
    current_hash = current["reproducibility"]["hash"]
    if original_hash == current_hash:
        return {
            "object_id": object_id,
            "status": "unchanged",
            "original_hash": original_hash,
            "current_hash": current_hash,
            "categories": [],
            "note": "the stored state still reproduces the investigation exactly",
        }

    categories: list[str] = []
    findings: dict[str, Any] = {}

    before_stats = original.get("statistics") or {}
    after_stats = current["price_statistics"]
    changed_statistics = [
        {"field": field, "before": before_stats.get(field), "after": after_stats.get(field)}
        for field in (
            "interval_return",
            "start_price",
            "end_price",
            "sessions",
            "annualized_volatility",
            "max_drawdown",
            "start_observation_id",
            "end_observation_id",
        )
        if before_stats.get(field) != after_stats.get(field)
    ]
    if changed_statistics:
        categories.append("market_observations_or_calculation")
        findings["statistics"] = changed_statistics

    before_events = _index(original.get("events") or [], "event_id")
    after_events = _index(current["events"]["items"], "event_id")
    added = sorted(set(after_events) - set(before_events))
    removed = sorted(set(before_events) - set(after_events))
    changed_events = []
    for event_id in sorted(set(before_events) & set(after_events)):
        before_event = before_events[event_id]
        after_event = after_events[event_id]
        before_doc = (before_event.get("document") or {}).get("sha256")
        after_doc = (after_event.get("document") or {}).get("sha256")
        fields = [
            field
            for field in ("availability_time", "relation", "form_type", "disclosed_items")
            if before_event.get(field) != after_event.get(field)
        ]
        if before_doc != after_doc:
            fields.append("document_sha256")
        if fields:
            changed_events.append(
                {
                    "event_id": event_id,
                    "fields": fields,
                    "before_document": before_doc,
                    "after_document": after_doc,
                }
            )
    if added or removed or changed_events:
        categories.append("company_event_evidence")
        findings["events"] = {
            "added": [after_events[event_id] for event_id in added],
            "removed": [before_events[event_id] for event_id in removed],
            "changed": changed_events,
        }
    if added:
        categories.append("new_filing_or_amendment")
    amendments = [
        event
        for event in (after_events[event_id] for event_id in added)
        if event.get("is_amendment")
    ]
    if amendments:
        categories.append("amended_filing")

    before_calc = (original.get("calculations") or {}).get("calculation", {})
    after_calc = current["reproducibility"]["components"]["calculation"]
    if before_calc.get("version") != after_calc.get("version"):
        categories.append("calculation_version_changed")
        findings["calculation"] = {
            "before": before_calc.get("version"),
            "after": after_calc.get("version"),
        }

    before_rights = (original.get("rights") or {}).get("sources") or []
    after_rights = current["rights"]["sources"]
    rights_changed = [
        source["source_id"]
        for source, new in zip(before_rights, after_rights)
        if source != new
    ]
    if len(before_rights) != len(after_rights) or rights_changed:
        categories.append("source_rights_changed")
        findings["rights"] = {
            "before": before_rights,
            "after": after_rights,
        }

    hypotheses_before = [
        (item.get("hypothesis_id"), item.get("rank")) for item in original.get("hypotheses") or []
    ]
    hypotheses_after = [
        (item.get("hypothesis_id"), item.get("rank")) for item in current["hypotheses"]
    ]
    if hypotheses_before != hypotheses_after:
        categories.append("hypothesis_ranking_changed")
        findings["hypotheses"] = {
            "before": hypotheses_before,
            "after": hypotheses_after,
        }

    return {
        "object_id": object_id,
        "status": "changes_detected",
        "original_hash": original_hash,
        "current_hash": current_hash,
        "categories": sorted(set(categories)),
        "findings": findings,
        "comparison_as_of": {
            "original": document["as_of"],
            "now": iso(utcnow()),
        },
        "note": (
            "the saved investigation is unchanged; this report describes how later stored "
            "state differs from it, and a new version is needed to record the new state"
        ),
    }


def export(db: Database, object_id: str) -> dict[str, Any]:
    """A rights-compliant export: refused when any cited source is restricted."""
    stored = ResearchObjectStore(db).get(object_id)
    if stored["kind"] != KIND:
        raise ValidationError(
            "this research object is not a price investigation", object_id=object_id, kind=stored["kind"]
        )
    rights = stored["document"]["spec"]["rights"]
    if not rights.get("export_allowed"):
        raise ValidationError(
            "a cited source is restricted, so this investigation may be inspected but not exported",
            object_id=object_id,
            restricted_sources=rights.get("restricted_sources"),
            unregistered_sources=rights.get("unregistered_sources"),
            missing_licence_sources=rights.get("missing_licence_sources"),
        )
    manifest = ResearchObjectStore(db).export_manifest(object_id)
    manifest["rights"] = rights
    manifest["export_policy"] = (
        "every contributing source is registered, licensed and redistributable; document "
        "excerpts are included only where the document's own rights permit"
    )
    return manifest


def list_investigations(db: Database, *, limit: int = 50) -> list[dict[str, Any]]:
    return ResearchObjectStore(db).list(kind=KIND, limit=limit)


__all__ = [
    "DOCUMENT_SCHEMA",
    "KIND",
    "build_document",
    "export",
    "impact",
    "investigation_name",
    "list_investigations",
    "reproduce",
    "save",
]
