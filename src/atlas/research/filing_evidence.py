"""Original-source evidence for a filing event.

The price-movement engine may show that a filing was published, but an 8-K *being
filed* is not an explanation. This module resolves each filing to its exact SEC
identity and, when the document bytes were archived by Atlas's existing Financial
Knowledge Engine (``atlas.research.knowledge``), to the sections, 8-K item
disclosures and narrative passages that the stored document actually contains.

Rules enforced here:

* **Temporal Evidence Kernel policy, not a new one.** Availability is the SEC
  acceptance instant when it is stored. A filing date alone is date-precision
  evidence pinned to the end of that UTC day by
  :func:`atlas.core.temporal.availability_from_date`, so it is never promoted to
  the beginning of the day. Unknown availability is reported, never guessed.
* **No fabricated locator.** The SEC archive URL is derived only from a
  well-formed accession, a numeric CIK and a primary document filename. If any
  part is missing or malformed, the status is ``unavailable`` and no URL is
  emitted.
* **No fabricated excerpt.** A passage is returned only from a stored
  ``knowledge_unit`` row written by the ingestion path. An un-ingested document
  yields ``passages: []`` with an explicit reason.
* **Amendments never replace the original.** The original accession stays the
  event identity; an amendment carries ``amends_accession`` and is linked to the
  evidence it supersedes, with both documents resolvable.
* **Rights are enforced.** A document whose redistribution class is not
  redistributable can be inspected locally, but its text is withheld from the
  exportable payload and labelled ``excerpt_withheld``.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from ..core.temporal import (
    availability_from_date,
    iso,
    iso_date,
    parse_date,
    parse_iso,
)
from ..storage.db import Database
from .knowledge import absolute_document_url

#: Redistribution classes whose document text may travel in an exported artefact.
REDISTRIBUTABLE = frozenset({"public_domain", "project_authored", "permitted"})

#: SEC Form 8-K item numbering. The labels are the form's own item headings; they are
#: used to name the disclosed event, never to infer what the text says.
EIGHT_K_ITEMS: dict[str, str] = {
    "1.01": "Entry into a Material Definitive Agreement",
    "1.02": "Termination of a Material Definitive Agreement",
    "1.03": "Bankruptcy or Receivership",
    "1.04": "Mine Safety - Reporting of Shutdowns and Patterns of Violations",
    "1.05": "Material Cybersecurity Incidents",
    "2.01": "Completion of Acquisition or Disposition of Assets",
    "2.02": "Results of Operations and Financial Condition",
    "2.03": "Creation of a Direct Financial Obligation or an Obligation under an Off-Balance Sheet Arrangement",
    "2.04": "Triggering Events That Accelerate or Increase a Direct Financial Obligation",
    "2.05": "Costs Associated with Exit or Disposal Activities",
    "2.06": "Material Impairments",
    "3.01": "Notice of Delisting or Failure to Satisfy a Continued Listing Rule or Standard",
    "3.02": "Unregistered Sales of Equity Securities",
    "3.03": "Material Modification to Rights of Security Holders",
    "4.01": "Changes in Registrant's Certifying Accountant",
    "4.02": "Non-Reliance on Previously Issued Financial Statements or a Related Audit Report",
    "5.01": "Changes in Control of Registrant",
    "5.02": "Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers; Compensatory Arrangements of Certain Officers",
    "5.03": "Amendments to Articles of Incorporation or Bylaws; Change in Fiscal Year",
    "5.04": "Temporary Suspension of Trading Under Registrant's Employee Benefit Plans",
    "5.05": "Amendments to the Registrant's Code of Ethics",
    "5.06": "Change in Shell Company Status",
    "5.07": "Submission of Matters to a Vote of Security Holders",
    "5.08": "Shareholder Director Nominations",
    "6.01": "ABS Informational and Computational Material",
    "6.02": "Change of Servicer or Trustee",
    "6.03": "Change in Credit Enhancement or Other External Support",
    "6.04": "Failure to Make a Required Distribution",
    "6.05": "Securities Act Updating Disclosure",
    "7.01": "Regulation FD Disclosure",
    "8.01": "Other Events",
    "9.01": "Financial Statements and Exhibits",
}

_ITEM_RE = re.compile(r"\bitem\s+(\d{1,2}\.\d{2})\b", re.IGNORECASE)
_ACCESSION_RE = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_CIK_RE = re.compile(r"^\d{1,10}$")

DOC_RESOLVED = "resolved"
# Availability derived from EDGAR acceptance plus a fixed publication lag is a modelled
# *upper bound* on the public-release instant, never an observed instant. Phase 9.6.1
# records such documents with precision "unknown" and this named model, so the bound can
# still order and exclude evidence while never being presented as exact.
MODELLED_AVAILABILITY_BASIS = "sec_acceptance_plus_publication_lag"
DOC_NOT_INGESTED = "not_ingested"
DOC_NOT_AT_CUTOFF = "not_available_at_cutoff"
DOC_UNKNOWN_AVAILABILITY = "availability_unknown"
DOC_UNAVAILABLE = "unavailable"
DOC_STORED_STATUS = {"text_unavailable", "rejected"}


def filing_availability(row: Mapping[str, Any]) -> tuple[str | None, str, str]:
    """Availability of a filing under the Temporal Evidence Kernel policy.

    Returns ``(iso_instant, precision, basis)``. An acceptance timestamp gives an exact
    instant; a filed date alone gives date precision pinned to ``23:59:59Z`` on that
    UTC day; neither gives unknown availability and no instant at all.
    """
    acceptance = row["acceptance_datetime"] if "acceptance_datetime" in row.keys() else None
    if acceptance:
        return iso(parse_iso(acceptance)), "exact", "sec_submissions.acceptance_datetime"
    filed = row["filed_date"] if "filed_date" in row.keys() else None
    if filed:
        conservative = availability_from_date(filed, "sec_submissions.filed_date_end_of_day_utc")
        return conservative.iso, "date", conservative.basis
    return None, "unknown", "sec_submissions:no_publication_time"


def cutoff_instant(cutoff: str | None) -> str | None:
    """The as-of instant for a date cutoff: end of that UTC day, per kernel policy."""
    if not cutoff:
        return None
    return availability_from_date(cutoff, "request.information_cutoff_end_of_day_utc").iso


def source_locator(
    cik: str | None, accession: str | None, primary_document: str | None
) -> dict[str, Any]:
    """The original SEC document locator, or an explicit reason it cannot be built.

    No URL is invented: every component is validated, and a missing or malformed part
    produces ``status: unavailable`` instead of a plausible-looking link.
    """
    if not accession:
        return {"status": DOC_UNAVAILABLE, "reason": "no accession number is stored", "url": None}
    if not _ACCESSION_RE.match(str(accession)):
        return {
            "status": DOC_UNAVAILABLE,
            "reason": "accession number is not in SEC 0000000000-00-000000 form",
            "url": None,
            "accession": accession,
        }
    if not cik or not _CIK_RE.match(str(cik).strip()):
        return {
            "status": DOC_UNAVAILABLE,
            "reason": "no numeric CIK is stored for this filing",
            "url": None,
            "accession": accession,
        }
    if not primary_document or "/" in str(primary_document) or "\\" in str(primary_document):
        return {
            "status": DOC_UNAVAILABLE,
            "reason": "no valid primary document filename is stored",
            "url": None,
            "accession": accession,
        }
    return {
        "status": "available",
        "url": absolute_document_url(str(cik), str(accession), str(primary_document)),
        "accession": accession,
        "cik": str(cik),
        "primary_document": primary_document,
        "publisher": "U.S. Securities and Exchange Commission (EDGAR)",
    }


def _local_time(instant: str, timezone: str) -> str | None:
    try:
        zone = ZoneInfo(timezone)
    except Exception:  # noqa: BLE001 - an unknown timezone is a display limitation
        return None
    return parse_iso(instant).astimezone(zone).isoformat()


def publication_context(
    *,
    availability: str | None,
    precision: str,
    timezone: str,
    session_bounds: Mapping[str, tuple[str, str]],
    stored_sessions: Sequence[str],
    venue_timezone: str | None = None,
) -> dict[str, Any]:
    """Where a publication sits relative to the selected venue's trading sessions.

    Ordering and cutoff decisions use the UTC availability instant. The exchange-local
    session date is derived by converting that instant into the *venue's* timezone, not
    by taking the UTC date: an SEC acceptance at ``2025-01-03T00:30:00Z`` is 2 January
    19:30 in New York and therefore an after-close release for the 2 January session,
    with 3 January as its first tradable session. Weekends, exchange holidays, early
    closes and daylight-saving changes are all resolved from the stored session bounds;
    when a date has no stored bounds the phase says so rather than assuming one.
    """
    if availability is None:
        return {
            "local_time": None,
            "local_date": None,
            "utc_date": None,
            "session_date": None,
            "timezone": timezone,
            "venue_timezone": venue_timezone or timezone,
            "phase": "unknown",
            "phase_basis": "public availability time is not evidenced",
            "is_trading_session": None,
            "tradable_session": None,
            "tradable_session_basis": "no publication instant to place",
            "date_precision_note": None,
        }
    moment = parse_iso(availability)
    venue_zone = venue_timezone or timezone
    local_time = _local_time(availability, timezone)
    local_date = local_time[:10] if local_time else None
    venue_local = _local_time(availability, venue_zone)
    session_date = venue_local[:10] if venue_local else moment.date().isoformat()
    all_sessions = sorted(set(session_bounds) | set(stored_sessions))
    next_session = next((day for day in all_sessions if day > session_date), None)
    phase = "unknown"
    basis = "no stored session bounds for the venue-local publication date"
    tradable: str | None = None
    tradable_basis = "no stored session follows the publication"
    is_session: bool | None = None
    bounds = session_bounds.get(session_date)
    if bounds is not None:
        is_session = True
        open_instant, close_instant = bounds
        if moment < parse_iso(open_instant):
            phase = "before_open"
            tradable = session_date
            tradable_basis = "the publication precedes this venue-local session's open"
        elif moment < parse_iso(close_instant):
            phase = "regular_session"
            tradable = session_date
            tradable_basis = "the publication falls inside this venue-local session"
        else:
            phase = "after_close"
            tradable = next_session
            tradable_basis = (
                "the publication follows this venue-local session's close, so the first "
                "eligible trading session is the next stored session"
            )
        basis = "stored venue session open/close bounds for the venue-local session date"
    elif session_date in stored_sessions:
        is_session = True
        phase = "no_stored_session_bounds"
        tradable = session_date
        tradable_basis = "a stored observation exists for the date but no calendar bounds do"
        basis = "a stored observation exists for the date but no calendar bounds do"
    else:
        is_session = False
        phase = "non_session"
        tradable = next_session
        tradable_basis = (
            "the venue-local date is a weekend, exchange holiday or unscheduled closure; "
            "the first eligible trading session is the next stored session"
        )
        basis = "the venue-local publication date is not a stored venue session"
    return {
        "local_time": local_time,
        "local_date": local_date,
        "utc_date": moment.date().isoformat(),
        "session_date": session_date,
        "timezone": timezone,
        "venue_timezone": venue_zone,
        "phase": phase,
        "phase_basis": basis,
        "is_trading_session": is_session,
        "tradable_session": tradable,
        "tradable_session_basis": tradable_basis,
        "date_precision_note": (
            "date-only availability is pinned to 23:59:59Z, so its phase is conservative"
            if precision == "date"
            else None
        ),
    }

def _units(db: Database, document_id: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.query(
            "SELECT unit_id, ordinal, unit_kind, section_path, heading, body, char_start, "
            "char_end, sha256 FROM knowledge_unit WHERE document_id = ? ORDER BY ordinal",
            (document_id,),
        )
    ]


def extract_items(units: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """8-K item disclosures present in the stored document's own headings.

    The item number and heading come from the document text. Atlas does not infer an
    item that is not written in the filing, and a document with no item headings yields
    an empty list rather than a guess.
    """
    found: dict[str, dict[str, Any]] = {}
    for unit in units:
        text = " ".join(
            part for part in (unit.get("section_path"), unit.get("heading")) if part
        )
        for match in _ITEM_RE.finditer(text):
            code = match.group(1)
            if code in found:
                continue
            heading = (unit.get("heading") or unit.get("section_path") or "").strip()
            found[code] = {
                "item": code,
                "label": EIGHT_K_ITEMS.get(code, heading or f"Item {code}"),
                "observed_heading": heading or None,
                "section_path": unit.get("section_path"),
                "unit_id": unit.get("unit_id"),
            }
    return [found[code] for code in sorted(found)]


def _excerpt(body: str, limit: int = 700) -> tuple[str, bool]:
    text = " ".join(body.split())
    if len(text) <= limit:
        return text, False
    return text[:limit].rstrip(), True


def _passages(
    units: Sequence[Mapping[str, Any]],
    *,
    items: Sequence[Mapping[str, Any]],
    redistributable: bool,
    accession: str,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Narrative passages that a claim can cite, with originals where permitted."""
    preferred: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        section = item.get("section_path")
        candidates = [
            unit
            for unit in units
            if unit["section_path"] == section and unit["unit_kind"] != "table"
        ]
        # Prefer the narrative paragraph under the item heading over the heading itself:
        # a claim should quote what was disclosed, not only its label.
        candidates.sort(key=lambda unit: (unit["unit_kind"] != "paragraph", unit["ordinal"]))
        for unit in candidates:
            if unit["unit_id"] in seen:
                continue
            preferred.append(unit)
            seen.add(unit["unit_id"])
            if len(preferred) >= limit:
                break
    for unit in units:
        if len(preferred) >= limit:
            break
        if unit["unit_id"] in seen or unit["unit_kind"] == "table":
            continue
        if unit["unit_kind"] == "paragraph" and len(str(unit["body"]).strip()) >= 80:
            preferred.append(unit)
            seen.add(unit["unit_id"])
    passages: list[dict[str, Any]] = []
    for unit in preferred[:limit]:
        excerpt, truncated = _excerpt(str(unit["body"]))
        passages.append(
            {
                "unit_id": unit["unit_id"],
                "section_path": unit["section_path"],
                "heading": unit["heading"],
                "unit_kind": unit["unit_kind"],
                "char_start": unit["char_start"],
                "char_end": unit["char_end"],
                "sha256": unit["sha256"],
                "excerpt": excerpt if redistributable else None,
                "excerpt_truncated": truncated if redistributable else None,
                "excerpt_withheld": (
                    None
                    if redistributable
                    else "source rights do not permit redistribution of this text"
                ),
                "citation": (
                    f"accession {accession} section {unit['section_path']} "
                    f"chars {unit['char_start']}-{unit['char_end']}"
                ),
            }
        )
    return passages


def prior_item_disclosure(
    db: Database,
    *,
    issuer_id: str,
    items: Sequence[str],
    before_instant: str | None,
    forms: Sequence[str] = ("8-K", "8-K/A"),
    limit: int = 5,
) -> dict[str, Any]:
    """Novelty of each disclosure item against the issuer's archived earlier filings.

    Only documents that are actually archived can be compared, so the result says so.
    An item absent from every archived prior filing is reported as a first disclosure
    *in the archived record*, never as a first disclosure in the world.
    """
    if not items:
        return {"basis": "no_item_disclosure_in_document", "prior_documents": [], "first_disclosure_items": [], "repeated_items": []}
    clauses = ["issuer_id = ?", "status = 'indexed'"]
    params: list[Any] = [issuer_id]
    if forms:
        clauses.append("form_type IN (" + ",".join("?" for _ in forms) + ")")
        params.extend(forms)
    if before_instant:
        clauses.append("availability_time < ?")
        params.append(before_instant)
    params.append(limit)
    rows = db.query(
        "SELECT document_id, accession, form_type, availability_time FROM knowledge_document "
        f"WHERE {' AND '.join(clauses)} ORDER BY availability_time DESC, accession LIMIT ?",
        params,
    )
    prior_documents = []
    repeated: set[str] = set()
    for row in rows:
        codes = {item["item"] for item in extract_items(_units(db, row["document_id"]))}
        prior_documents.append(
            {
                "accession": row["accession"],
                "form_type": row["form_type"],
                "availability_time": row["availability_time"],
                "items": sorted(codes),
            }
        )
        repeated.update(codes & set(items))
    return {
        "basis": (
            "archived_prior_filings" if prior_documents else "no_archived_prior_filing"
        ),
        "prior_documents": prior_documents,
        "first_disclosure_items": sorted(set(items) - repeated),
        "repeated_items": sorted(repeated),
        "coverage_note": (
            "novelty is relative to the filings archived in this deployment, not to every "
            "disclosure the issuer ever made"
        ),
    }


def resolve_document(
    db: Database,
    *,
    row: Mapping[str, Any],
    cutoff: str | None,
    mode_historical: bool,
    passage_limit: int = 4,
) -> dict[str, Any]:
    """Resolve one filing to its original document, items and citable passages."""
    accession = row["accession_number"]
    locator = source_locator(row["cik"], accession, row["primary_document"])
    stored = db.query_one(
        "SELECT * FROM knowledge_document WHERE accession = ?", (accession,)
    )
    payload: dict[str, Any] = {
        "status": DOC_NOT_INGESTED,
        "accession": accession,
        "filed_date": row["filed_date"],
        "acceptance_datetime": row["acceptance_datetime"],
        "form_type": row["form_type"],
        "is_amendment": bool(row["is_amendment"]),
        "amends_accession": row["amends_accession"],
        "filing_version": "amendment" if row["is_amendment"] else "original",
        "primary_document": row["primary_document"],
        "source_locator": locator,
        "document_id": None,
        "sha256": None,
        "byte_size": None,
        "media_type": None,
        "parser_version": None,
        "ingested_at": None,
        "availability_time": None,
        "availability_precision": None,
        "availability_basis": None,
        "rights": None,
        "items": [],
        "passages": [],
        "passage_status": "document_not_ingested",
        "reason": (
            "the filing's primary document is not archived in this deployment; the original "
            "SEC locator is shown, but Atlas has no text and will not invent an excerpt"
        ),
    }
    if stored is None:
        return payload

    redistributable = str(stored["rights"] or "") in REDISTRIBUTABLE
    payload.update(
        {
            "document_id": stored["document_id"],
            "sha256": stored["sha256"],
            "byte_size": stored["byte_size"],
            "media_type": stored["media_type"],
            "parser_version": stored["parser_version"],
            "ingested_at": stored["ingested_at"],
            "availability_time": stored["availability_time"],
            "availability_precision": stored["availability_precision"],
            "availability_basis": stored["availability_basis"],
            "rights": {
                "redistribution": stored["rights"],
                "redistributable": redistributable,
                "retention_policy": stored["retention_policy"],
            },
            "stored_status": stored["status"],
            "primary_document_url": stored["primary_document_url"],
            "reason": None,
        }
    )
    # The archived document's own locator wins over a constructed one: it is what the
    # ingestion path actually retrieved. It is never replaced by a guess.
    payload["source_locator"] = {
        "status": "available",
        "url": stored["primary_document_url"],
        "accession": stored["accession"],
        "content_sha256": stored["sha256"],
        "publisher": "U.S. Securities and Exchange Commission (EDGAR)",
        "archived": True,
        "must_reverify": True,
    }

    precision = str(stored["availability_precision"] or "")
    basis = str(stored["availability_basis"] or "")
    modelled_bound = bool(
        precision == "unknown"
        and basis.startswith(MODELLED_AVAILABILITY_BASIS)
        and stored["availability_time"]
    )
    payload["availability_is_upper_bound"] = modelled_bound
    if modelled_bound:
        # The bound is usable evidence ordering: the document was certainly public at or
        # before it. It is reported as modelled, and the stored "unknown" precision is kept
        # so no consumer can read it back as an exact release instant.
        payload["availability_precision"] = "modeled_bound"
        payload["availability_stored_precision"] = precision
        payload["availability_model"] = stored["availability_model"]
        payload["availability_note"] = (
            "the public-release instant was not observed; availability_time is a "
            "conservative upper bound derived from EDGAR acceptance plus a modelled "
            "publication lag, so the document is citable as evidence that was public by "
            "that bound and never as an exact release timestamp"
        )
    if precision == "unknown" and not modelled_bound:
        payload["status"] = DOC_UNKNOWN_AVAILABILITY
        payload["passage_status"] = "availability_unknown"
        return payload
    if mode_historical and cutoff and str(stored["availability_time"]) > cutoff:
        payload["status"] = DOC_NOT_AT_CUTOFF
        payload["passage_status"] = "not_available_at_cutoff"
        payload["reason"] = (
            "this document was not publicly available at the information cutoff; it is "
            "excluded rather than quoted as contemporaneous evidence"
        )
        return payload
    if stored["status"] in DOC_STORED_STATUS:
        payload["status"] = stored["status"]
        payload["passage_status"] = "text_unavailable"
        payload["reason"] = "the archived document has no extractable text"
        return payload

    units = _units(db, stored["document_id"])
    items = extract_items(units) if str(stored["form_type"]).startswith("8-K") else []
    payload["status"] = DOC_RESOLVED
    payload["items"] = items
    payload["passages"] = _passages(
        units,
        items=items,
        redistributable=redistributable,
        accession=str(stored["accession"]),
        limit=passage_limit,
    )
    payload["passage_status"] = "available" if payload["passages"] else "no_narrative_passage"
    payload["section_paths"] = sorted({str(unit["section_path"]) for unit in units})
    payload["unit_count"] = len(units)
    payload["table_count"] = sum(1 for unit in units if unit["unit_kind"] == "table")
    return payload


def citation_for(document: Mapping[str, Any], passage: Mapping[str, Any]) -> dict[str, Any]:
    """A citation that points at an exact span of an exact document version."""
    return {
        "kind": "sec_document_span",
        "accession": document.get("accession"),
        "document_id": document.get("document_id"),
        "document_sha256": document.get("sha256"),
        "section_path": passage.get("section_path"),
        "unit_id": passage.get("unit_id"),
        "char_start": passage.get("char_start"),
        "char_end": passage.get("char_end"),
        "span_sha256": passage.get("sha256"),
        "excerpt": passage.get("excerpt"),
        "excerpt_withheld": passage.get("excerpt_withheld"),
        "source_url": (document.get("source_locator") or {}).get("url"),
    }


__all__ = [
    "DOC_NOT_AT_CUTOFF",
    "DOC_NOT_INGESTED",
    "DOC_RESOLVED",
    "DOC_UNAVAILABLE",
    "DOC_UNKNOWN_AVAILABILITY",
    "EIGHT_K_ITEMS",
    "REDISTRIBUTABLE",
    "citation_for",
    "cutoff_instant",
    "extract_items",
    "filing_availability",
    "prior_item_disclosure",
    "publication_context",
    "resolve_document",
    "source_locator",
]
