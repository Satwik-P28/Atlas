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
from ..entities.master import SecurityMaster
from ..storage.db import Database
from . import move_intelligence
from .objects import SCHEMA_VERSION, ResearchObjectStore

KIND = "price_investigation"
DOCUMENT_SCHEMA = "atlas.price_investigation.v2"
TEMPORAL_SCHEMA = "atlas.price_investigation.temporal.v1"


def investigation_name(report: Mapping[str, Any]) -> str:
    selection = report["selection"]
    ticker = selection.get("ticker") or selection.get("security_id")
    return f"{ticker} {selection['start_session']}..{selection['end_session']}"


def _temporal_semantics(
    report: Mapping[str, Any], created_at: str
) -> tuple[str, dict[str, Any]]:
    """Separate the five clocks a saved investigation can otherwise conflate.

    The market observation period is historical; the knowledge cutoff is when the
    evidence used became public; the analysis time and the saved-object creation time
    are when this investigation was actually produced; and the source vintages record
    which provider revisions and archived document versions were used.

    A retrospective investigation is **not** knowledge that was public at the end of its
    price window. Its knowledge cutoff is the run time, because it can contain later
    amendments and later provider revisions. Only a historical reconstruction has a
    cutoff inside the observation period, and even then the provider price vintage is
    unverified.
    """
    selection = report["selection"]
    request = report["request"]
    historical = request.get("mode") == move_intelligence.MODE_HISTORICAL
    cutoff = request.get("information_cutoff")
    if historical:
        knowledge = f"{cutoff}T23:59:59Z" if cutoff else created_at
        basis = (
            "information_cutoff_end_of_day_utc"
            if cutoff
            else "analysis_run_time_no_cutoff"
        )
        as_of_basis = (
            "historical reconstruction: claims are as of the end of the requested "
            "information-cutoff day, and later evidence is excluded"
        )
    else:
        knowledge = created_at
        basis = "analysis_run_time_retrospective"
        as_of_basis = (
            "retrospective investigation: claims are as of the run time, not the end of "
            "the price observation period; later amendments and revisions may be present"
        )
    documents = []
    for event in report["events"]["items"]:
        document = event.get("document") or {}
        if not document.get("accession"):
            continue
        documents.append(
            {
                "event_id": event["event_id"],
                "accession": document["accession"],
                "document_sha256": document.get("sha256"),
                "availability_time": (
                    document.get("availability_time") or event.get("availability_time")
                ),
                "availability_precision": (
                    document.get("availability_precision")
                    or event.get("availability_precision")
                ),
                "ingested_at": document.get("ingested_at"),
                "document_status": document.get("status"),
            }
        )
    temporal = {
        "schema": TEMPORAL_SCHEMA,
        "observation_period": {
            "start_session": selection["start_session"],
            "end_session": selection["end_session"],
            "sessions": selection["sessions"],
            "timeframe": selection["timeframe"],
            "timezone": selection["timezone"],
            "price_basis": request.get("price_basis"),
        },
        "public_knowledge_cutoff": {
            "instant": knowledge,
            "date": knowledge[:10],
            "basis": basis,
        },
        "analysis_time": created_at,
        "object_created_at": created_at,
        "mode": request.get("mode"),
        "retrospective": not historical,
        "as_of_basis": as_of_basis,
        "source_vintages": {
            "prices": dict(report["selection"].get("price_vintage") or {}),
            "filings": documents,
            "note": (
                "prices are stored session revisions, not the provider's publication "
                "history; documents are archived versions, not the SEC HTML as published"
            ),
        },
        "limitations": [
            "the observation period is not a knowledge cutoff",
            "a retrospective report must not be read as what was knowable at the period end",
            "no licensed news, consensus or macro-release vintage is present",
        ],
    }
    return knowledge, temporal


def build_document(
    report: Mapping[str, Any],
    *,
    name: str | None = None,
    version: str = "1.0.0",
    status: str = "validated",
    created_at: str | None = None,
) -> dict[str, Any]:
    """Turn an engine report into a UROS ``price_investigation`` document."""
    created_at = created_at or iso(utcnow())
    as_of, temporal = _temporal_semantics(report, created_at)
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
        "as_of": as_of,
        # All contributing evidence was public at `as_of`. For a retrospective report
        # `as_of` is the run time, not the end of the price window.
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
            "temporal": temporal,
            "source_vintages": temporal["source_vintages"],
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
    created_at = iso(utcnow())
    display_name = name
    if display_name is None and not report["selection"].get("ticker"):
        # The ticker in force at the historical end date may not be stored, but a saved
        # object still needs a readable name. Use the current ticker as a display label,
        # never as the ticker in force at the observation date.
        current = SecurityMaster(db).current_ticker(report["selection"]["security_id"])
        label = current.get("ticker") if current else None
        if label:
            display_name = (
                f"{label} {report['selection']['start_session']}.."
                f"{report['selection']['end_session']}"
            )
    document = build_document(
        report, name=display_name, version=version, created_at=created_at
    )
    stored = ResearchObjectStore(db).create(
        document, owner_id=owner_id, created_at=created_at
    )
    return {
        "object_id": stored["object_id"],
        "kind": stored["kind"],
        "name": stored["name"],
        "version": stored["version"],
        "status": stored["status"],
        "content_hash": stored["content_hash"],
        "created_at": stored["created_at"],
        "as_of": document["as_of"],
        "temporal": document["spec"]["temporal"],
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


def _temporal_from_document(document: Mapping[str, Any]) -> dict[str, Any]:
    """Read temporal semantics, including documents saved before they were explicit."""
    spec = document.get("spec") or {}
    temporal = spec.get("temporal")
    if temporal:
        return dict(temporal)
    return {
        "schema": None,
        "legacy_document": True,
        "observation_period": {
            "start_session": (spec.get("interval") or {}).get("start_session"),
            "end_session": (spec.get("interval") or {}).get("end_session"),
            "timezone": (spec.get("interval") or {}).get("timezone"),
            "price_basis": spec.get("price_basis"),
        },
        "public_knowledge_cutoff": {
            "instant": document.get("as_of"),
            "basis": "legacy_as_of_field_unverified",
        },
        "analysis_time": document.get("as_of"),
        "object_created_at": None,
        "retrospective": (spec.get("request") or {}).get("mode")
        == move_intelligence.MODE_RETROSPECTIVE,
        "as_of_basis": (
            "saved before the five clocks were separated; the as_of value is preserved "
            "for compatibility and must not be read as a verified knowledge cutoff"
        ),
        "source_vintages": spec.get("source_vintages") or {},
        "limitations": ["legacy saved document: temporal semantics are incomplete"],
    }


def get(db: Database, object_id: str) -> dict[str, Any]:
    """Reopen a saved investigation exactly as stored, with its temporal semantics."""
    stored = ResearchObjectStore(db).get(object_id)
    if stored["kind"] != KIND:
        raise ValidationError(
            "this research object is not a price investigation",
            object_id=object_id,
            kind=stored["kind"],
        )
    document = stored["document"]
    return {
        "schema": DOCUMENT_SCHEMA,
        "object_id": stored["object_id"],
        "kind": stored["kind"],
        "name": stored["name"],
        "version": stored["version"],
        "status": stored["status"],
        "content_hash": stored["content_hash"],
        "created_at": stored["created_at"],
        "as_of": document.get("as_of"),
        "temporal": _temporal_from_document(document),
        "document": document,
        "note": (
            "this is the stored document, not a recomputation; use the reproduce endpoint "
            "for a current-state drift comparison"
        ),
    }


def reproduce(db: Database, object_id: str) -> dict[str, Any]:
    """Current-state reproducibility comparison, not a pinned historical replay.

    The request is re-run against the database **as it is now**. A matching hash means
    today's stored observations, filings and calculation inputs still produce the same
    reproducibility digest; it does not prove that a historical run could be replayed
    from the inputs captured at save time. Atlas does not yet store a pinned input
    snapshot, so this endpoint is explicit about the weaker guarantee.
    """
    stored = ResearchObjectStore(db).get(object_id)
    if stored["kind"] != KIND:
        raise ValidationError(
            "this research object is not a price investigation", object_id=object_id, kind=stored["kind"]
        )
    started = iso(utcnow())
    request = _request_from_object(stored)
    current = move_intelligence.explain_range(db, request)
    original_hash = stored["document"]["spec"]["reproducibility"]["hash"]
    current_hash = current["reproducibility"]["hash"]
    return {
        "object_id": object_id,
        "content_hash": stored["content_hash"],
        "comparison_kind": "current_state_recomputation",
        "pinned_input_replay": False,
        "guarantee": (
            "re-running the saved request against the current database reproduces the "
            "same reproducibility hash"
            if original_hash == current_hash
            else "the current database no longer produces the saved reproducibility hash"
        ),
        "guarantee_scope": (
            "a match does not prove that the original run is replayable from pinned "
            "inputs, that no source changed, or that a historical reader could have known "
            "the same values; inspect the change-impact report for what moved"
        ),
        "saved_as_of": stored["document"].get("as_of"),
        "saved_temporal": _temporal_from_document(stored["document"]),
        "original_reproducibility_hash": original_hash,
        "current_reproducibility_hash": current_hash,
        "matches": original_hash == current_hash,
        "recomputed_at": iso(utcnow()),
        "recompute_started_at": started,
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
            "comparison_kind": "current_state_drift_check",
            "original_hash": original_hash,
            "current_hash": current_hash,
            "categories": [],
            "saved_temporal": _temporal_from_document(document),
            "computed_at": iso(utcnow()),
            "note": (
                "the current stored state still produces the saved reproducibility hash; "
                "this is a drift check, not a replay of pinned historical inputs"
            ),
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
        "comparison_kind": "current_state_drift_check",
        "original_hash": original_hash,
        "current_hash": current_hash,
        "categories": sorted(set(categories)),
        "findings": findings,
        "saved_temporal": _temporal_from_document(document),
        "comparison_as_of": {
            "original": document["as_of"],
            "now": iso(utcnow()),
        },
        "computed_at": iso(utcnow()),
        "note": (
            "the saved investigation is unchanged; this report describes how the current "
            "stored state differs from it, and a new version is needed to record the new "
            "state. It is a drift comparison, not a pinned-input replay."
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
    "get",
    "impact",
    "investigation_name",
    "list_investigations",
    "reproduce",
    "save",
]
