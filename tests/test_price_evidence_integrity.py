"""Adversarial tests for the price-evidence integrity pass.

Each test pins one failure mode that would otherwise make an investigation look
authoritative while being wrong: a date-only filing promoted to the first second of its
day, a timeline ordered by the SEC's calendar date rather than publication time, an
after-hours disclosure attributed to the wrong session, a document quoted when it was
published after the cutoff, an amendment that replaces its original, a fabricated SEC
link, an unexplained 8-K presented as an explanation, or a saved investigation that
silently changes underneath its reader.

The 8-K text used here is an explicit offline test fixture, not a reproduction of any
real filing. Its accession numbers are in a reserved test range.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

from atlas.core.errors import ValidationError
from atlas.entities.master import SecurityMaster
from atlas.market.actions import ActionStore, CorporateAction
from atlas.market.calendar import TradingCalendar
from atlas.research import filing_evidence as fe
from atlas.research import investigations, move_intelligence as mi, prices
from atlas.research.knowledge import KnowledgeEngine, absolute_document_url

DAY_ONE = "2025-01-02"
DAY_TWO = "2025-01-03"
DAY_THREE = "2025-01-06"

FIXTURE_TEXT = (
    "TEST FIXTURE: the registrant reports a hypothetical change in quarterly revenue for "
    "this offline integrity test. No figure here is a real issuer disclosure."
)
FIXTURE_HTML = f"""<html><body>
<h1>FORM 8-K</h1>
<h2>Item 2.02. Results of Operations and Financial Condition</h2>
<p>{FIXTURE_TEXT}</p>
<p>TEST FIXTURE: this paragraph exists so a citation can point at a narrative span.</p>
</body></html>"""


def _identity(db, *, ticker: str = "TST", cik: str = "1000001"):
    master = SecurityMaster(db)
    master.ensure_venue("XNYS", "New York Stock Exchange", country="US", timezone="America/New_York")
    issuer_id = master.register_issuer(legal_name=f"{ticker} Fixture Corp", cik=cik, sic="6021")
    security_id = master.ensure_security(issuer_id, class_designation="common stock", currency="USD")
    listing_id = master.ensure_listing(security_id, mic="XNYS", valid_from="2020-01-01", is_primary=True)
    master.assign_ticker(
        listing_id, ticker, valid_from="2020-01-01", confidence=1.0, status="confirmed",
        source_id="sec-edgar",
    )
    return issuer_id, security_id


def _import(db, ticker: str, pairs):
    return prices.import_price_series(
        db,
        ticker=ticker,
        rows=[
            {
                "date": day,
                "open": close - 0.5,
                "high": close + 0.5,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000,
            }
            for day, close in pairs
        ],
        source_name="Provider A",
        licence="Project-authored test series",
        redistribution="project_authored",
        adjustment_semantics="unadjusted",
        mic="XNYS",
    )


def _filing(
    db,
    *,
    issuer_id: str,
    accession: str,
    filed_date: str,
    acceptance: str | None,
    form_type: str = "8-K",
    is_amendment: bool = False,
    amends: str | None = None,
    primary_document: str | None = "primary.htm",
    cik: str = "1000001",
) -> None:
    db.execute(
        "INSERT INTO filing (filing_id, issuer_id, cik, accession_number, form_type, filed_date, "
        "acceptance_datetime, period_of_report, primary_document, is_amendment, amends_accession, "
        "source_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            f"FIL-{accession}",
            issuer_id,
            cik,
            accession,
            form_type,
            filed_date,
            acceptance,
            None,
            primary_document,
            int(is_amendment),
            amends,
            "sec-edgar",
        ),
    )


def _ingest(
    db,
    *,
    issuer_id: str,
    accession: str,
    acceptance: str,
    filed_date: str = DAY_TWO,
    html: str = FIXTURE_HTML,
    form_type: str = "8-K",
    cik: str = "1000001",
):
    return KnowledgeEngine(db).ingest_document(
        issuer_id=issuer_id,
        accession=accession,
        form_type=form_type,
        html=html,
        filed_date=filed_date,
        acceptance_time=acceptance,
        primary_document_url=absolute_document_url(cik, accession, "primary.htm"),
        rights="public_domain",
        notes="offline integrity fixture",
    )


def _request(security_id: str, **overrides) -> mi.ExplanationRequest:
    params = {
        "security_id": security_id,
        "start_session": DAY_ONE,
        "end_session": DAY_THREE,
    }
    params.update(overrides)
    return mi.ExplanationRequest(**params)


def _codes(report) -> set[str]:
    return {warning["code"] for warning in report["warnings"]}


def _event(report, accession: str):
    return next(
        item
        for item in report["events"]["items"]
        if item.get("accession_number") == accession
    )


# --------------------------------------------------------------- publication timing
def test_date_only_filing_is_available_at_end_of_day_and_orders_last(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    _filing(
        db, issuer_id=issuer_id, accession="0000000000-25-900001",
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T09:00:00Z",
    )
    _filing(
        db, issuer_id=issuer_id, accession="0000000000-25-900002",
        filed_date=DAY_TWO, acceptance=None,
    )

    report = mi.explain_range(db, _request(security_id))
    exact = _event(report, "0000000000-25-900001")
    date_only = _event(report, "0000000000-25-900002")

    # A filed date alone is not evidence that the filing was public at 00:00 UTC.
    assert date_only["availability_precision"] == "date"
    assert date_only["availability_time"] == f"{DAY_TWO}T23:59:59Z"
    assert date_only["availability_basis"] == "sec_submissions.filed_date_end_of_day_utc"
    assert date_only["filed_date"] == DAY_TWO
    # Ordering places the exact 09:00Z publication before the date-only one, even though
    # both share the same SEC filed date.
    accessions = [item.get("accession_number") for item in report["events"]["items"]]
    assert accessions.index("0000000000-25-900001") < accessions.index("0000000000-25-900002")
    assert any(
        warning["code"] == mi.W_DATE_PRECISION
        and "end of that UTC day" in warning["message"]
        for warning in report["warnings"]
    )


def test_timeline_orders_by_publication_instant_not_sec_filing_date(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    # Filed on the earlier date but accepted later than the other filing.
    _filing(
        db, issuer_id=issuer_id, accession="0000000000-25-900010",
        filed_date=DAY_ONE, acceptance=f"{DAY_TWO}T14:00:00Z",
    )
    _filing(
        db, issuer_id=issuer_id, accession="0000000000-25-900011",
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T10:00:00Z",
    )

    report = mi.explain_range(db, _request(security_id))
    accessions = [item.get("accession_number") for item in report["events"]["items"]]

    assert accessions.index("0000000000-25-900011") < accessions.index("0000000000-25-900010")
    assert report["events"]["chronological_order"].startswith("evidenced publication instant")
    # The filing date is retained as metadata rather than discarded.
    assert _event(report, "0000000000-25-900010")["date"] == DAY_ONE
    assert _event(report, "0000000000-25-900010")["publication_date"] == DAY_TWO


def test_one_candle_warning_no_longer_claims_a_zero_return(db):
    _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])

    report = mi.explain_range(db, _request(security_id, start_session=DAY_TWO, end_session=DAY_TWO))
    warning = next(item for item in report["warnings"] if item["code"] == mi.W_SINGLE_SESSION)

    assert "reported as zero" not in warning["message"]
    assert "never reports a flat 0%" in warning["message"]
    assert report["price_statistics"]["interval_return"] == pytest.approx(0.01)


def test_publication_local_date_and_timezone_shift_are_reported(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    # 00:30Z on 3 January is still 2 January, 19:30, in New York.
    _filing(
        db, issuer_id=issuer_id, accession="0000000000-25-900020",
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T00:30:00Z",
    )

    report = mi.explain_range(db, _request(security_id, timezone="America/New_York"))
    event = _event(report, "0000000000-25-900020")

    assert event["publication_date"] == DAY_TWO
    assert event["publication"]["local_time"].startswith(f"{DAY_ONE}T19:30:00")
    assert event["publication_local_date_differs"] is True
    assert mi.W_TIMEZONE_SHIFT in _codes(report)
    # Ordering still uses the UTC instant, so the same event is not moved.
    assert event["availability_time"] == f"{DAY_TWO}T00:30:00Z"

    tokyo = mi.explain_range(db, _request(security_id, timezone="Asia/Tokyo"))
    tokyo_event = _event(tokyo, "0000000000-25-900020")
    assert tokyo_event["publication"]["local_time"].startswith(f"{DAY_TWO}T09:30:00")
    assert tokyo_event["publication_local_date_differs"] is False


def test_after_hours_publication_maps_to_the_next_tradable_session(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    TradingCalendar(db).ensure_range("XNYS", "2024-12-20", "2025-01-15")
    # 23:30Z on Friday 3 January is 18:30 ET, after the 21:00Z close.
    _filing(
        db, issuer_id=issuer_id, accession="0000000000-25-900030",
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T23:30:00Z",
    )

    report = mi.explain_range(db, _request(security_id, timezone="America/New_York"))
    event = _event(report, "0000000000-25-900030")

    assert event["publication"]["phase"] == "after_close"
    assert event["publication"]["tradable_session"] == DAY_THREE
    # It stays on its own calendar date; it is not shifted to the previous session.
    assert event["publication_date"] == DAY_TWO


def test_corporate_action_with_unknown_availability_is_never_placed_in_window(db):
    _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 100.0), (DAY_THREE, 100.0)])
    ActionStore(db).add(
        CorporateAction(
            security_id=security_id,
            action_type="cash_dividend",
            source_id="sec-edgar",
            ex_date=DAY_TWO,
            cash_amount=Decimal("2"),
            currency="USD",
            availability_time=None,
        )
    )

    retrospective = mi.explain_range(db, _request(security_id))
    action = next(item for item in retrospective["events"]["items"] if item["kind"] == "corporate_action")
    assert action["relation"] == "unknown_availability"
    assert action["known_at_range_end"] is False
    assert retrospective["events"]["in_window_count"] == 0
    assert mi.W_UNKNOWN_AVAILABILITY in _codes(retrospective)
    assert retrospective["hypotheses"][0]["relevance"]["tier"] in (3, 4, 5)

    historical = mi.explain_range(
        db, _request(security_id, mode=mi.MODE_HISTORICAL, information_cutoff=DAY_THREE)
    )
    assert not [item for item in historical["events"]["items"] if item["kind"] == "corporate_action"]
    assert historical["events"]["coverage"]["corporate_actions"]["excluded_unknown_availability"] == 1


# ------------------------------------------------------------- original documents
def test_document_resolves_to_exact_accession_hash_and_original_locator(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    accession = "0000000000-25-900101"
    _filing(
        db, issuer_id=issuer_id, accession=accession,
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T21:05:00Z",
    )
    _ingest(db, issuer_id=issuer_id, accession=accession, acceptance=f"{DAY_TWO}T21:05:00Z")

    report = mi.explain_range(db, _request(security_id))
    event = _event(report, accession)
    document = event["document"]

    assert document["status"] == fe.DOC_RESOLVED
    assert document["accession"] == accession
    assert document["sha256"] == hashlib.sha256(FIXTURE_HTML.encode()).hexdigest()
    assert document["source_locator"]["url"].startswith(
        "https://www.sec.gov/Archives/edgar/data/1000001/000000000025900101/"
    )
    assert document["source_locator"]["content_sha256"] == document["sha256"]
    assert event["source_url"] == document["source_locator"]["url"]
    assert [item["item"] for item in event["disclosed_items"]] == ["2.02"]

    passage = next(item for item in event["passages"] if item["unit_kind"] == "paragraph")
    assert passage["excerpt"] in FIXTURE_TEXT
    assert passage["section_path"].startswith("Item 2.02")
    assert len(passage["sha256"]) == 64

    hypothesis = next(
        item for item in report["hypotheses"] if item["relevance"]["tier"] == 2
    )
    assert "Item 2.02" in hypothesis["statement"]
    assert FIXTURE_TEXT[:40] in hypothesis["statement"]
    citation = next(
        item for item in hypothesis["relevance"]["citations"] if item["unit_id"] == passage["unit_id"]
    )
    assert citation["section_path"] == passage["section_path"]
    assert citation["char_start"] == passage["char_start"]
    assert citation["char_end"] == passage["char_end"]
    assert citation["document_sha256"] == document["sha256"]


def test_filing_without_archived_bytes_emits_locator_but_no_excerpt(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    accession = "0000000000-25-900102"
    _filing(
        db, issuer_id=issuer_id, accession=accession,
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T21:05:00Z",
    )

    report = mi.explain_range(db, _request(security_id))
    event = _event(report, accession)

    assert event["document"]["status"] == fe.DOC_NOT_INGESTED
    assert event["document"]["passages"] == []
    assert event["source_url"]
    assert mi.W_DOCUMENT_NOT_INGESTED in _codes(report)
    hypothesis = next(item for item in report["hypotheses"] if item["relevance"]["tier"] == 2)
    # The filing's existence is a timing fact; no disclosed event is claimed.
    assert "cannot identify the disclosed event" in hypothesis["statement"]
    assert hypothesis["relevance"]["citations"] == []
    assert "Item 2.02" not in hypothesis["statement"]


def test_missing_primary_document_produces_no_fabricated_url(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    _filing(
        db, issuer_id=issuer_id, accession="0000000000-25-900103",
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T21:05:00Z", primary_document=None,
    )

    spec = fe.source_locator("1000001", "0000000000-25-900103", None)
    assert spec["status"] == fe.DOC_UNAVAILABLE
    assert spec["url"] is None
    assert "primary document" in spec["reason"]

    report = mi.explain_range(db, _request(security_id))
    event = _event(report, "0000000000-25-900103")
    assert event["source_url"] is None
    assert event["document"]["source_locator"]["url"] is None


def test_historical_cutoff_excludes_an_archived_document_published_later(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    accession = "0000000000-25-900104"
    _filing(
        db, issuer_id=issuer_id, accession=accession,
        filed_date=DAY_ONE, acceptance=f"{DAY_ONE}T21:05:00Z",
    )
    # The archived bytes carry their own later availability: the document governs itself.
    _ingest(
        db, issuer_id=issuer_id, accession=accession,
        acceptance=f"{DAY_THREE}T21:05:00Z", filed_date=DAY_ONE,
    )

    report = mi.explain_range(
        db,
        _request(
            security_id, start_session=DAY_ONE, end_session=DAY_TWO,
            mode=mi.MODE_HISTORICAL, information_cutoff=DAY_TWO,
        ),
    )
    event = _event(report, accession)

    assert event["document"]["status"] == fe.DOC_NOT_AT_CUTOFF
    assert event["passages"] == []
    assert mi.W_DOCUMENT_NOT_AT_CUTOFF in _codes(report)
    assert all(
        citation["document_id"] is None
        for hypothesis in report["hypotheses"]
        for citation in hypothesis["relevance"]["citations"]
    )


def test_restricted_document_text_is_withheld_from_citations(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    accession = "0000000000-25-900105"
    _filing(
        db, issuer_id=issuer_id, accession=accession,
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T21:05:00Z",
    )
    stored = _ingest(db, issuer_id=issuer_id, accession=accession, acceptance=f"{DAY_TWO}T21:05:00Z")
    db.execute("UPDATE knowledge_document SET rights='restricted' WHERE document_id=?", (stored["document_id"],))

    report = mi.explain_range(db, _request(security_id))
    event = _event(report, accession)

    assert event["document"]["rights"]["redistributable"] is False
    assert all(passage["excerpt"] is None for passage in event["passages"])
    assert all(passage["excerpt_withheld"] for passage in event["passages"])
    assert mi.W_DOCUMENT_RESTRICTED in _codes(report)
    hypothesis = next(item for item in report["hypotheses"] if item["relevance"]["tier"] == 2)
    assert "does not permit quoting" in hypothesis["statement"]
    assert all(citation["excerpt"] is None for citation in hypothesis["relevance"]["citations"])


def test_amendment_links_to_original_and_keeps_both_documents(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    original = "0000000000-25-900110"
    amendment = "0000000000-25-900111"
    _filing(
        db, issuer_id=issuer_id, accession=original,
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T20:05:00Z",
    )
    _ingest(db, issuer_id=issuer_id, accession=original, acceptance=f"{DAY_TWO}T20:05:00Z")
    _filing(
        db, issuer_id=issuer_id, accession=amendment, form_type="8-K/A",
        filed_date=DAY_THREE, acceptance=f"{DAY_THREE}T21:05:00Z",
        is_amendment=True, amends=original,
    )
    _ingest(
        db, issuer_id=issuer_id, accession=amendment, acceptance=f"{DAY_THREE}T21:05:00Z",
        form_type="8-K/A",
    )

    # A later amendment is subsequent evidence: shown, never used to explain the window.
    report = mi.explain_range(
        db, _request(security_id, start_session=DAY_ONE, end_session=DAY_TWO)
    )
    original_event = _event(report, original)
    amendment_event = _event(report, amendment)

    assert original_event["relation"] == "in_window"
    assert amendment_event["relation"] == "subsequent"
    assert amendment_event["supersedes_event_id"] == f"FIL-FIL-{original}"
    assert amendment_event["original_evidence_retained"] is True
    assert original_event["document"]["status"] == fe.DOC_RESOLVED
    assert amendment_event["document"]["status"] == fe.DOC_RESOLVED
    assert original_event["passages"], "the original evidence must not be replaced"
    supporting = {
        evidence_id
        for hypothesis in report["hypotheses"]
        for evidence_id in hypothesis["relevance"]["supporting_evidence"]
    }
    assert amendment_event["event_id"] not in supporting


def test_identical_document_bytes_are_deduplicated(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    first = "0000000000-25-900120"
    second = "0000000000-25-900121"
    for accession in (first, second):
        _filing(
            db, issuer_id=issuer_id, accession=accession,
            filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T21:05:00Z",
        )
        _ingest(db, issuer_id=issuer_id, accession=accession, acceptance=f"{DAY_TWO}T21:05:00Z")

    report = mi.explain_range(db, _request(security_id))
    duplicate = next(
        item for item in report["events"]["items"] if item.get("duplicate_document_of")
    )

    assert duplicate["document"]["sha256"] == _event(report, first)["document"]["sha256"]
    assert report["events"]["coverage"]["sec_filings"]["duplicates_suppressed"] >= 1
    assert mi.W_EVENT_DUPLICATE in _codes(report)


def test_item_novelty_is_relative_to_archived_filings(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    first = "0000000000-25-900130"
    second = "0000000000-25-900131"
    _filing(
        db, issuer_id=issuer_id, accession=first,
        filed_date=DAY_ONE, acceptance=f"{DAY_ONE}T21:05:00Z",
    )
    _ingest(db, issuer_id=issuer_id, accession=first, acceptance=f"{DAY_ONE}T21:05:00Z")
    _filing(
        db, issuer_id=issuer_id, accession=second,
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T21:05:00Z",
    )
    _ingest(db, issuer_id=issuer_id, accession=second, acceptance=f"{DAY_TWO}T21:05:00Z")

    report = mi.explain_range(db, _request(security_id))

    assert "2.02" in _event(report, first)["novelty"]["first_disclosure_items"]
    assert "2.02" in _event(report, second)["novelty"]["repeated_items"]
    first_novelty = _event(report, first)["novelty"]
    assert first_novelty["basis"] == "no_archived_prior_filing"
    assert first_novelty["prior_documents"] == []
    assert "cannot assess novelty" in " ".join(item["statement"] for item in report["hypotheses"])
    assert "repeat disclosure" in " ".join(item["statement"] for item in report["hypotheses"])


def test_unknown_document_availability_excludes_passages(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    accession = "0000000000-25-900140"
    _filing(
        db, issuer_id=issuer_id, accession=accession,
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T21:05:00Z",
    )
    _ingest(db, issuer_id=issuer_id, accession=accession, acceptance=f"{DAY_TWO}T21:05:00Z")
    # A document whose own timing evidence is unknown cannot supply a contemporaneous quote.
    db.execute(
        "UPDATE knowledge_document SET availability_precision='unknown', "
        "availability_basis='no_timing_evidence' WHERE accession=?",
        (accession,),
    )
    row = db.query_one("SELECT * FROM filing WHERE accession_number=?", (accession,))
    document = fe.resolve_document(db, row=row, cutoff=None, mode_historical=False)

    assert document["status"] == fe.DOC_UNKNOWN_AVAILABILITY
    assert document["passages"] == []
    assert document["passage_status"] == "availability_unknown"


# -------------------------------------------------------------- persisted research
def test_saved_investigation_is_immutable_reproducible_and_change_impacted(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    accession = "0000000000-25-900150"
    _filing(
        db, issuer_id=issuer_id, accession=accession,
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T21:05:00Z",
    )
    _ingest(db, issuer_id=issuer_id, accession=accession, acceptance=f"{DAY_TWO}T21:05:00Z")
    report = mi.explain_range(db, _request(security_id))

    saved = investigations.save(db, report, name="TST review", version="1.0.0")
    assert saved["kind"] == investigations.KIND
    assert saved["reproducibility_hash"] == report["reproducibility"]["hash"]

    # Immutable: the same name and version cannot be overwritten.
    with pytest.raises(ValidationError):
        investigations.save(db, report, name="TST review", version="1.0.0")

    reproduced = investigations.reproduce(db, saved["object_id"])
    assert reproduced["matches"] is True

    # Later evidence produces a change-impact report, not a silent overwrite.
    _filing(
        db, issuer_id=issuer_id, accession="0000000000-25-900151",
        filed_date=DAY_THREE, acceptance=f"{DAY_THREE}T21:05:00Z", form_type="10-Q",
    )
    change = investigations.impact(db, saved["object_id"])
    assert change["status"] == "changes_detected"
    assert change["original_hash"] == report["reproducibility"]["hash"]
    assert change["current_hash"] != change["original_hash"]
    assert "company_event_evidence" in change["categories"]
    assert "new_filing_or_amendment" in change["categories"]
    assert change["findings"]["events"]["added"]

    stored = investigations.ResearchObjectStore(db).get(saved["object_id"])
    assert stored["document"]["spec"]["reproducibility"]["hash"] == report["reproducibility"]["hash"]

    exported = investigations.export(db, saved["object_id"])
    assert exported["rights"]["export_allowed"] is True
    assert exported["export_policy"]


def test_restricted_source_investigation_cannot_be_exported(db):
    issuer_id, security_id = _identity(db)
    prices.import_price_series(
        db,
        ticker="TST",
        rows=[
            {"date": day, "open": close - 0.5, "high": close + 0.5, "low": close - 1.0,
             "close": close, "volume": 1_000}
            for day, close in [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)]
        ],
        source_name="Vendor Feed",
        licence="Vendor terms",
        redistribution="restricted",
        adjustment_semantics="unadjusted",
        mic="XNYS",
    )
    report = mi.explain_range(db, _request(security_id))
    saved = investigations.save(db, report, name="restricted review", version="1.0.0")

    with pytest.raises(ValidationError) as error:
        investigations.export(db, saved["object_id"])
    assert "restricted" in str(error.value).lower()
    assert saved["rights"]["export_allowed"] is False


def test_historical_provider_revision_changes_the_hash_and_stays_unverified(db):
    _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    request = _request(
        security_id, mode=mi.MODE_HISTORICAL, information_cutoff=DAY_THREE
    )
    first = mi.explain_range(db, request)

    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 99.0)])
    corrected = mi.explain_range(db, request)

    assert corrected["price_statistics"]["end_revision_seq"] >= 2
    assert corrected["reproducibility"]["hash"] != first["reproducibility"]["hash"]
    # A revised provider value still does not prove what the vendor had published.
    assert corrected["selection"]["price_vintage"]["status"] == "unverified"
    assert corrected["selection"]["price_vintage"]["verified_at_cutoff"] is False
    assert mi.W_VINTAGE_AT_CUTOFF in _codes(corrected)


# ------------------------------------------------- end-of-window explanatory eligibility
def test_publication_after_final_session_close_is_not_a_candidate_explanation(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    before_close = "0000000000-25-900160"
    after_close = "0000000000-25-900161"
    for accession, acceptance in (
        (before_close, f"{DAY_TWO}T20:05:00Z"),
        (after_close, f"{DAY_TWO}T21:05:00Z"),
    ):
        _filing(
            db, issuer_id=issuer_id, accession=accession,
            filed_date=DAY_TWO, acceptance=acceptance,
        )
        _ingest(db, issuer_id=issuer_id, accession=accession, acceptance=acceptance)

    # The selected interval ends at the 3 January close; the 21:05Z release is five
    # minutes too late to explain that close even though its date is inside the range.
    report = mi.explain_range(
        db, _request(security_id, start_session=DAY_ONE, end_session=DAY_TWO)
    )
    early = _event(report, before_close)
    late = _event(report, after_close)

    assert early["relation"] == "in_window"
    assert early["explanatory_eligible"] is True
    assert late["relation"] == "subsequent_to_price_window"
    assert late["explanatory_eligible"] is False
    assert late["explanatory_eligibility"]["eligible"] is False
    assert "at or after" in late["explanatory_eligibility"]["basis"]
    assert "precedes" in early["explanatory_eligibility"]["basis"]
    assert late["explanatory_eligibility"]["final_session"] == DAY_TWO
    assert late["explanatory_eligibility"]["first_eligible_session"] == DAY_THREE
    assert "cannot explain that close" in late["explanatory_eligibility"]["reason"]
    # It is visible, but never cited as support for an explanation.
    assert late["document"]["status"] == fe.DOC_RESOLVED
    supporting = {
        evidence_id
        for hypothesis in report["hypotheses"]
        for evidence_id in hypothesis["relevance"]["supporting_evidence"]
    }
    assert early["event_id"] in supporting
    assert late["event_id"] not in supporting
    assert report["events"]["coverage"]["sec_filings"][
        "published_after_final_session_close"
    ] == 1
    assert mi.W_AFTER_FINAL_CLOSE in _codes(report)


def test_weekend_publication_after_the_final_session_is_never_ranked(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0)])
    accession = "0000000000-25-900170"
    _filing(
        db, issuer_id=issuer_id, accession=accession,
        filed_date="2025-01-04", acceptance="2025-01-04T15:00:00Z",
    )
    _ingest(
        db, issuer_id=issuer_id, accession=accession, acceptance="2025-01-04T15:00:00Z",
        filed_date="2025-01-04",
    )

    report = mi.explain_range(
        db, _request(security_id, start_session=DAY_ONE, end_session=DAY_TWO)
    )

    # The Saturday release is outside the selected calendar interval and cannot explain
    # Friday's close; it is not silently folded into the window or the ranking.
    assert all(
        item.get("accession_number") != accession for item in report["events"]["items"]
    )
    assert not any(
        accession in hypothesis["statement"] for hypothesis in report["hypotheses"]
    )
    context = fe.publication_context(
        availability="2025-01-04T15:00:00Z",
        precision="exact",
        timezone="America/New_York",
        venue_timezone="America/New_York",
        session_bounds=_january_bounds(db),
        stored_sessions=[DAY_ONE, DAY_TWO, DAY_THREE],
    )
    assert context["phase"] == "non_session"
    assert context["tradable_session"] == DAY_THREE


def _january_bounds(db):
    cal = TradingCalendar(db)
    cal.build("XNYS", "2024-10-31", "2025-03-15")
    sessions = cal.sessions("XNYS", "2024-10-31", "2025-03-15")
    return {s.session_date: (s.open_ts, s.close_ts) for s in sessions}


def test_publication_context_dates_sessions_in_venue_local_time(db):
    bounds = _january_bounds(db)
    # 2 January 2025, 7:30 p.m. Eastern is 3 January 2025, 00:30Z. The SEC's UTC date
    # is one day later than the venue's session date; the publication belongs to the
    # 2 January session, after its close, and first trades on 3 January.
    context = fe.publication_context(
        availability="2025-01-03T00:30:00Z",
        precision="exact",
        timezone="UTC",
        venue_timezone="America/New_York",
        session_bounds=bounds,
        stored_sessions=sorted(bounds),
    )

    assert context["utc_date"] == "2025-01-03"
    assert context["local_date"] == "2025-01-03"
    assert context["session_date"] == "2025-01-02"
    assert context["phase"] == "after_close"
    assert context["is_trading_session"] is True
    assert context["tradable_session"] == "2025-01-03"
    assert context["local_time"] == "2025-01-03T00:30:00+00:00"


def test_publication_context_handles_weekends_holidays_and_dst(db):
    bounds = _january_bounds(db)

    def context(instant: str) -> dict:
        return fe.publication_context(
            availability=instant,
            precision="exact",
            timezone="America/New_York",
            venue_timezone="America/New_York",
            session_bounds=bounds,
            stored_sessions=sorted(bounds),
        )

    saturday = context("2025-01-04T15:00:00Z")
    assert saturday["phase"] == "non_session"
    assert saturday["is_trading_session"] is False
    assert saturday["tradable_session"] == "2025-01-06"

    holiday = context("2025-01-01T06:30:00Z")
    assert holiday["session_date"] == "2025-01-01"
    assert holiday["phase"] == "non_session"
    assert holiday["tradable_session"] == "2025-01-02"

    # US daylight saving began on 9 March 2025. At 00:30Z it is still Sunday evening in
    # New York (20:30 EDT), so the first eligible session is Monday 10 March.
    spring = context("2025-03-10T00:30:00Z")
    assert spring["session_date"] == "2025-03-09"
    assert spring["phase"] == "non_session"
    assert spring["tradable_session"] == "2025-03-10"
    assert context("2025-03-10T13:31:00Z")["phase"] == "regular_session"

    # After the 3 November 2024 change, 14:31Z is 09:31 EST.
    fall = context("2024-11-04T14:31:00Z")
    assert fall["session_date"] == "2024-11-04"
    assert fall["phase"] == "regular_session"
    late = context("2024-11-04T22:00:00Z")
    assert late["phase"] == "after_close"
    assert late["tradable_session"] == "2024-11-05"


# --------------------------------------------------- saved-investigation temporal semantics
def test_retrospective_saved_investigation_is_as_of_run_time_not_period_end(db):
    _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    report = mi.explain_range(
        db, _request(security_id, start_session=DAY_ONE, end_session=DAY_TWO)
    )
    saved = investigations.save(db, report, name="retrospective clocks", version="1.0.0")
    stored = investigations.ResearchObjectStore(db).get(saved["object_id"])
    temporal = stored["document"]["spec"]["temporal"]

    assert temporal["retrospective"] is True
    assert temporal["mode"] == mi.MODE_RETROSPECTIVE
    assert temporal["observation_period"]["end_session"] == DAY_TWO
    assert temporal["public_knowledge_cutoff"]["basis"] == "analysis_run_time_retrospective"
    assert temporal["public_knowledge_cutoff"]["instant"] != f"{DAY_TWO}T23:59:59Z"
    assert stored["document"]["as_of"] == temporal["analysis_time"]
    assert stored["document"]["as_of"] == temporal["object_created_at"]
    assert stored["created_at"] == temporal["object_created_at"]
    assert temporal["source_vintages"]["prices"]["status"] == "unverified"
    assert "not the end of the price observation period" in temporal["as_of_basis"]


def test_historical_saved_investigation_uses_the_cutoff_as_knowledge_time(db):
    _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    report = mi.explain_range(
        db,
        _request(
            security_id, start_session=DAY_ONE, end_session=DAY_TWO,
            mode=mi.MODE_HISTORICAL, information_cutoff=DAY_TWO,
        ),
    )
    saved = investigations.save(db, report, name="historical clocks", version="1.0.0")
    temporal = investigations.ResearchObjectStore(db).get(
        saved["object_id"]
    )["document"]["spec"]["temporal"]

    assert temporal["retrospective"] is False
    assert temporal["public_knowledge_cutoff"]["instant"] == f"{DAY_TWO}T23:59:59Z"
    assert temporal["public_knowledge_cutoff"]["basis"] == "information_cutoff_end_of_day_utc"
    assert saved["as_of"] == f"{DAY_TWO}T23:59:59Z"


def test_reproduce_is_labelled_a_current_state_comparison_and_reports_real_time(db):
    _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    report = mi.explain_range(db, _request(security_id))
    saved = investigations.save(db, report, name="replay scope", version="1.0.0")

    result = investigations.reproduce(db, saved["object_id"])

    assert result["comparison_kind"] == "current_state_recomputation"
    assert result["pinned_input_replay"] is False
    assert result["matches"] is True
    assert result["recomputed_at"] >= result["recompute_started_at"]
    assert result["recomputed_at"] != report["selection"]["end_session"]
    assert result["recomputed_at"][:4] >= "2026"
    assert "does not prove" in result["guarantee_scope"]
    assert result["saved_temporal"]["retrospective"] is True


def test_later_amendment_changes_drift_but_not_the_saved_knowledge_claim(db):
    issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    original = "0000000000-25-900180"
    _filing(
        db, issuer_id=issuer_id, accession=original,
        filed_date=DAY_TWO, acceptance=f"{DAY_TWO}T20:05:00Z",
    )
    _ingest(db, issuer_id=issuer_id, accession=original, acceptance=f"{DAY_TWO}T20:05:00Z")
    report = mi.explain_range(
        db, _request(security_id, start_session=DAY_ONE, end_session=DAY_TWO)
    )
    saved = investigations.save(db, report, name="amended later", version="1.0.0")
    before = investigations.ResearchObjectStore(db).get(saved["object_id"])["document"]

    # The amendment arrives after the saved run. It must change drift, not the saved
    # object's knowledge cutoff or its as_of claim.
    amendment = "0000000000-25-900181"
    _filing(
        db, issuer_id=issuer_id, accession=amendment, form_type="8-K/A",
        filed_date=DAY_THREE, acceptance=f"{DAY_THREE}T15:00:00Z",
        is_amendment=True, amends=original,
    )
    _ingest(
        db, issuer_id=issuer_id, accession=amendment,
        acceptance=f"{DAY_THREE}T15:00:00Z", form_type="8-K/A",
    )

    change = investigations.impact(db, saved["object_id"])
    after = investigations.ResearchObjectStore(db).get(saved["object_id"])["document"]
    replay = investigations.reproduce(db, saved["object_id"])

    assert change["status"] == "changes_detected"
    assert change["comparison_kind"] == "current_state_drift_check"
    assert "amended_filing" in change["categories"]
    assert after["as_of"] == before["as_of"]
    assert after["spec"]["temporal"] == before["spec"]["temporal"]
    assert replay["matches"] is False
    assert replay["pinned_input_replay"] is False
    assert replay["saved_as_of"] == before["as_of"]


def test_legacy_saved_document_is_readable_with_an_explicit_legacy_label(db):
    import json

    _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 104.0), (DAY_THREE, 102.0)])
    report = mi.explain_range(db, _request(security_id))
    saved = investigations.save(db, report, name="legacy clocks", version="1.0.0")

    # Simulate a document saved by the previous schema: no explicit clocks.
    row = db.query_one(
        "SELECT document_json FROM research_object WHERE object_id = ?",
        (saved["object_id"],),
    )
    document = json.loads(row["document_json"])
    document["spec"].pop("temporal", None)
    document["spec"].pop("source_vintages", None)
    document["as_of"] = f"{DAY_TWO}T23:59:59Z"
    db.execute(
        "UPDATE research_object SET document_json = ? WHERE object_id = ?",
        (json.dumps(document), saved["object_id"]),
    )

    replay = investigations.reproduce(db, saved["object_id"])

    assert replay["saved_temporal"]["legacy_document"] is True
    assert replay["saved_temporal"]["public_knowledge_cutoff"]["basis"] == (
        "legacy_as_of_field_unverified"
    )
    assert "must not be read as a verified knowledge cutoff" in replay["saved_temporal"]["as_of_basis"]
    assert replay["comparison_kind"] == "current_state_recomputation"
