"""SEC submissions history: archive layouts, pagination, incremental sync, coverage.

The archive payloads are **real SEC documents** (Apple, Microsoft, Walmart, Alphabet),
retrieved with a contact User-Agent and archived under ``fixtures/``. They matter
because the history layout is not the layout of ``filings.recent``: the live archives
are a flat map of parallel arrays at the top level, with no ``filings`` wrapper. A
parser that assumes ``recent``'s shape silently ingests nothing.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atlas.evidence.kernel import EvidenceKernel
from atlas.ingestion.sec_history import (
    ARCHIVE_FORMAT_OBJECT_LIST,
    ARCHIVE_FORMAT_PARALLEL,
    SubmissionsHistoryStore,
    load_fixture_history,
    parse_history_payload,
)
from atlas.ingestion.sec_sync import SecIngestor

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
APPLE_DIR = FIXTURES / "sec"
MSFT_DIR = FIXTURES / "sec_msft"
WMT_DIR = FIXTURES / "sec_wmt"
GOOGL_DIR = FIXTURES / "sec_googl"

APPLE_CIK = "0000320193"
MSFT_CIK = "0000789019"

MULTI_ISSUERS = [
    ("MSFT", MSFT_DIR, "0000789019"),
    ("WMT", WMT_DIR, "0000104169"),
    ("GOOGL", GOOGL_DIR, "0001652044"),
]


def _load(directory: Path, cik: str) -> tuple[dict, dict]:
    submissions = json.loads((directory / f"submissions_CIK{cik}.json").read_text())
    facts = json.loads((directory / f"companyfacts_CIK{cik}.json").read_text())
    return submissions, facts


def test_parse_real_archive_uses_top_level_parallel_arrays():
    documents = load_fixture_history(MSFT_DIR, MSFT_CIK)
    assert len(documents) == 2
    parsed = parse_history_payload(documents[0].payload, cik=MSFT_CIK, name=documents[0].name,
                                   advertised=documents[0].advertised)
    assert parsed.layout == ARCHIVE_FORMAT_PARALLEL
    assert parsed.filings, "a real archive must yield filing rows"
    assert parsed.advertised_count == len(parsed.filings)
    assert all(filing.cik == MSFT_CIK for filing in parsed.filings)
    assert any(filing.acceptance_datetime for filing in parsed.filings)
    # Archives cover pre-'recent' history that the main payload does not contain.
    assert parsed.advertised_from < "2010-01-01"


@pytest.mark.parametrize("ticker,directory,cik", MULTI_ISSUERS)
def test_every_real_issuer_archive_parses_fully(ticker, directory, cik):
    documents = load_fixture_history(directory, cik)
    assert documents, f"{ticker} advertises history archives"
    for document in documents:
        parsed = parse_history_payload(document.payload, cik=cik, name=document.name,
                                       advertised=document.advertised)
        assert parsed.layout == ARCHIVE_FORMAT_PARALLEL
        assert len(parsed.filings) == parsed.advertised_count, (
            f"{ticker} {document.name}: parsed {len(parsed.filings)} of "
            f"{parsed.advertised_count}; issues={parsed.issues[:2]}"
        )
        assert not [i for i in parsed.issues if i["severity"] == "error"]


def test_parse_object_list_layout_is_accepted_and_labelled():
    """Some derivatives wrap filings as a list of objects; the shape is reported."""
    payload = {
        "cik": MSFT_CIK,
        "filings": [
            {
                "accessionNumber": "0000789019-08-000001",
                "filingDate": "2008-08-01",
                "acceptanceDateTime": "2008-08-01T16:02:11.000Z",
                "form": "10-K",
                "reportDate": "2008-06-30",
                "primaryDocument": "msft10k.htm",
                "isXBRL": 0,
            },
            {
                "accessionNumber": "0000789019-08-000002",
                "filingDate": "2008-10-24",
                "acceptanceDateTime": "2008-10-24T16:01:00.000Z",
                "form": "10-Q",
                "reportDate": "2008-09-30",
            },
        ],
    }
    parsed = parse_history_payload(payload, cik=MSFT_CIK, name="synthetic-object-list.json")
    assert parsed.layout == ARCHIVE_FORMAT_OBJECT_LIST
    assert len(parsed.filings) == 2
    assert parsed.filings[0].form_type == "10-K"
    assert parsed.filings[0].acceptance_datetime == "2008-08-01T16:02:11Z"
    assert parsed.filings[1].is_amendment is False


def test_parse_top_level_object_list_is_accepted():
    parsed = parse_history_payload(
        [{"accessionNumber": "0000320193-03-000001", "filingDate": "2003-01-15", "form": "10-Q"}],
        cik=APPLE_CIK,
    )
    assert parsed.layout == ARCHIVE_FORMAT_OBJECT_LIST
    assert parsed.filings[0].accession_number == "0000320193-03-000001"


def test_archive_count_mismatch_is_reported_not_reconciled():
    documents = load_fixture_history(MSFT_DIR, MSFT_CIK)
    advertised = copy.deepcopy(dict(documents[0].advertised or {}))
    advertised["filingCount"] = int(advertised["filingCount"]) + 7
    parsed = parse_history_payload(documents[0].payload, cik=MSFT_CIK, name="x", advertised=advertised)
    assert any(issue["code"] == "history_count_mismatch" for issue in parsed.issues)
    # The mismatch is reported but no rows are invented or dropped.
    assert len(parsed.filings) == int(documents[0].advertised["filingCount"])


def test_unrecognised_archive_layout_raises():
    from atlas.core.errors import ParseError

    with pytest.raises(ParseError):
        parse_history_payload({"unexpected": []}, cik=APPLE_CIK)
    with pytest.raises(ParseError):
        parse_history_payload("not a payload", cik=APPLE_CIK)


def test_history_store_tracks_content_hash(db):
    store = SubmissionsHistoryStore(db)
    assert not store.is_current(APPLE_CIK, "archive-001.json", "abc")
    store.record_file(
        APPLE_CIK, "archive-001.json", content_hash="abc", doc_id=None,
        advertised={"filingCount": 3, "filingFrom": "1994-01-26", "filingTo": "2000-01-01"},
        filing_rows=3,
    )
    assert store.is_current(APPLE_CIK, "archive-001.json", "abc")
    assert not store.is_current(APPLE_CIK, "archive-001.json", "def")
    state = store.state(APPLE_CIK)
    assert state[0]["filing_rows"] == 3
    assert state[0]["advertised_from"] == "1994-01-26"


def test_sync_without_history_reports_incomplete_coverage(db):
    submissions, facts = _load(APPLE_DIR, APPLE_CIK)
    report = SecIngestor(db).sync_payloads(
        APPLE_CIK, submissions_payload=submissions, companyfacts_payload=facts
    )
    coverage = report.history["coverage"]
    assert coverage["expected_files"], "Apple advertises history archives"
    assert coverage["complete"] is False
    assert coverage["missing_files"]
    assert any(issue["code"] == "filing_history_incomplete" for issue in report.issues)
    assert report.history["files_fetched"] == 0


def test_sync_with_history_completes_filings_and_upgrades_availability(db):
    submissions, facts = _load(APPLE_DIR, APPLE_CIK)
    documents = load_fixture_history(APPLE_DIR, APPLE_CIK)
    assert documents, "Apple history archive fixture must exist"

    baseline = SecIngestor(db).sync_payloads(
        APPLE_CIK, submissions_payload=submissions, companyfacts_payload=facts,
        observed_at="2026-01-01T00:00:00Z",
    )
    baseline_facts = baseline.companyfacts["stats"]
    baseline_rows = baseline.filings_written

    db2 = db
    report = SecIngestor(db2).sync_payloads(
        APPLE_CIK, submissions_payload=submissions, companyfacts_payload=facts,
        history_documents=documents, observed_at="2026-01-01T00:00:00Z",
    )
    stats = report.companyfacts["stats"]
    coverage = report.history["coverage"]

    assert coverage["complete"] is True
    assert coverage["missing_files"] == []
    assert report.history["files_skipped_unchanged"] == 0
    assert report.history["files_fetched"] == len(documents)
    assert report.filings_written > baseline_rows
    assert report.filings_written == baseline_rows + sum(
        int(document.advertised["filingCount"]) for document in documents
    )
    # The point of fetching history: older facts gain exact acceptance timestamps.
    assert stats["availability_exact"] > baseline_facts["availability_exact"]
    assert stats["availability_date"] < baseline_facts["availability_date"]
    assert stats["availability_unknown"] == 0


def test_second_sync_skips_unchanged_archives_and_preserves_availability(db):
    submissions, facts = _load(APPLE_DIR, APPLE_CIK)
    documents = load_fixture_history(APPLE_DIR, APPLE_CIK)
    ingestor = SecIngestor(db)
    first = ingestor.sync_payloads(
        APPLE_CIK, submissions_payload=submissions, companyfacts_payload=facts,
        history_documents=documents, observed_at="2026-01-01T00:00:00Z",
    )
    evidence_after_first = EvidenceKernel(db).count()

    second = ingestor.sync_payloads(
        APPLE_CIK, submissions_payload=submissions, companyfacts_payload=facts,
        history_documents=documents, observed_at="2026-01-01T00:00:00Z",
    )
    assert second.history["files_skipped_unchanged"] == len(documents)
    assert second.history["filings_written"] == 0
    assert second.evidence["duplicates"] == first.evidence["duplicates"] + first.evidence["inserted"] + first.evidence["superseding"]
    assert EvidenceKernel(db).count() == evidence_after_first
    # Availability must not regress because the archives were skipped: the filing index
    # is rebuilt from storage, not from the payloads parsed in this run.
    assert second.companyfacts["stats"]["availability_exact"] == first.companyfacts["stats"]["availability_exact"]
    assert second.companyfacts["stats"]["availability_date"] == first.companyfacts["stats"]["availability_date"]
    assert second.history["coverage"]["complete"] is True


def test_changed_archive_bytes_are_reparsed(db):
    submissions, facts = _load(APPLE_DIR, APPLE_CIK)
    documents = load_fixture_history(APPLE_DIR, APPLE_CIK)
    ingestor = SecIngestor(db)
    ingestor.sync_payloads(
        APPLE_CIK, submissions_payload=submissions, companyfacts_payload=facts,
        history_documents=documents, observed_at="2026-01-01T00:00:00Z",
    )
    mutated = documents[0]
    mutated.body = mutated.body + b"\n"  # bytes changed, content identical
    report = ingestor.sync_payloads(
        APPLE_CIK, submissions_payload=submissions, companyfacts_payload=facts,
        history_documents=[mutated], observed_at="2026-01-01T00:00:00Z",
    )
    assert report.history["files_skipped_unchanged"] == 0
    assert report.history["files_fetched"] == 1
    # Re-parsing the same filings is idempotent: upsert on accession, no duplicate rows.
    from atlas.ingestion.sec_submissions import FilingRepository

    repository = FilingRepository(db)
    rows = repository.for_cik(APPLE_CIK)
    accessions = [row["accession_number"] for row in rows]
    assert len(accessions) == len(set(accessions))
