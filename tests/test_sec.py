"""SEC ingestion: submissions, XBRL facts, normalisation, client policy, idempotency."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from atlas.core.errors import ParseError, SecPolicyError, ValidationError
from atlas.evidence.kernel import EvidenceKernel
from atlas.ingestion.sec_client import SecClient, TokenBucket, validate_user_agent
from atlas.ingestion.sec_companyfacts import parse_companyfacts
from atlas.ingestion.sec_submissions import FilingRepository, parse_submissions
from atlas.ingestion.sec_sync import SecIngestor

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
SEC_DIR = FIXTURES / "sec"
RESTATEMENT_DIR = FIXTURES / "sec_restatement"
APPLE_CIK = "0000320193"
RESTATEMENT_CIK = "0001999999"


@pytest.fixture(scope="module")
def apple_payloads():
    submissions = json.loads((SEC_DIR / "submissions_CIK0000320193.json").read_text())
    facts = json.loads((SEC_DIR / "companyfacts_CIK0000320193.json").read_text())
    return submissions, facts


@pytest.fixture(scope="module")
def restatement_payloads():
    submissions = json.loads((RESTATEMENT_DIR / "submissions.json").read_text())
    facts = json.loads((RESTATEMENT_DIR / "companyfacts.json").read_text())
    return submissions, facts


# --------------------------------------------------------------------------- #
# Submissions
# --------------------------------------------------------------------------- #
def test_parse_submissions_extracts_issuer_and_filing_metadata(apple_payloads):
    submissions, _ = apple_payloads
    result = parse_submissions(submissions)
    assert result.cik == APPLE_CIK
    assert result.legal_name == "Apple Inc."
    assert "AAPL" in result.tickers
    assert len(result.filings) >= 100
    assert all(filing.accession_number for filing in result.filings)
    assert any(filing.acceptance_datetime for filing in result.filings)
    # The payload lists older history in separate files; Atlas reports rather than hides it.
    assert result.additional_files
    assert "history archive" in result.additional_files[0]["note"]


def test_parse_submissions_rejects_payload_without_identity():
    with pytest.raises(ParseError):
        parse_submissions({"facts": {}})
    with pytest.raises(ParseError):
        parse_submissions({"cik": 1})


def test_filing_repository_roundtrip(db, restatement_payloads):
    submissions, _ = restatement_payloads
    parsed = parse_submissions(submissions)
    repository = FilingRepository(db)
    repository.upsert_many(parsed.filings, issuer_id=None, source_id="sec-edgar")
    stored = repository.get("0001999999-24-000009")
    assert stored["form_type"] == "10-Q/A"
    assert stored["is_amendment"] == 1
    assert stored["acceptance_datetime"] == "2024-08-15T20:31:44Z"
    assert len(repository.amendments(RESTATEMENT_CIK)) == 1


# --------------------------------------------------------------------------- #
# Company facts
# --------------------------------------------------------------------------- #
def test_parse_companyfacts_maps_canonical_concepts(apple_payloads):
    submissions, facts = apple_payloads
    filing_index = parse_submissions(submissions).filing_index
    result = parse_companyfacts(
        facts,
        issuer_id="ISS-CIK0000320193",
        source_id="sec-edgar",
        source_url="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        filings=filing_index,
    )
    assert result.records
    concepts = {record.concept for record in result.records}
    assert {"revenue", "assets", "net_income", "operating_cash_flow", "capex"} <= concepts
    assert all(record.unit for record in result.records)
    assert all(record.source_concept for record in result.records)
    assert all(record.taxonomy in {"us-gaap", "dei"} for record in result.records)
    stats = result.stats
    assert stats["availability_exact"] > 0  # acceptance timestamps upgraded precision
    assert stats["availability_unknown"] == 0
    assert stats["observations_deduplicated"] >= 0
    # Both annual and quarterly duration facts are present.
    ends = {record.period_end for record in result.records if record.period_type == "duration"}
    assert len(ends) > 10
    assert any(record.period_type == "instant" for record in result.records)


def test_parse_companyfacts_preserves_source_concept_and_unit(apple_payloads):
    submissions, facts = apple_payloads
    result = parse_companyfacts(
        facts,
        issuer_id="ISS-CIK0000320193",
        source_id="sec-edgar",
        source_url="https://example/companyfacts",
        filings=parse_submissions(submissions).filing_index,
    )
    revenue = [record for record in result.records if record.concept == "revenue"][0]
    assert revenue.source_concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert revenue.unit == "USD"
    assert revenue.currency == "USD"
    assert revenue.verification == "source_primary"
    assert revenue.quality == "verified"
    eps = [record for record in result.records if record.concept == "eps_diluted"]
    if eps:
        assert all(record.unit == "USD/shares" for record in eps)


def test_restatement_payload_keeps_currencies_separate(restatement_payloads):
    submissions, facts = restatement_payloads
    result = parse_companyfacts(
        facts,
        issuer_id="ISS-CIK0001999999",
        source_id="sec-edgar",
        source_url="fixture://restatement/companyfacts.json",
        filings=parse_submissions(submissions).filing_index,
    )
    revenue = [record for record in result.records if record.concept == "revenue"]
    usd = sorted([r for r in revenue if r.unit == "USD"], key=lambda r: r.availability_time)
    eur = [r for r in revenue if r.unit == "EUR"]

    assert [record.value_numeric for record in usd] == ["100000000", "90000000"]
    assert [record.revision_kind for record in usd] == ["original", "amendment"]
    assert all(record.availability_precision == "exact" for record in usd)
    # A different currency is a different economic quantity: retained, never merged.
    assert len(eur) == 1 and eur[0].currency == "EUR"
    assert result.stats["multi_currency_concepts"]["revenue"] == ["EUR", "USD"]
    assert any(issue["code"] == "multi_currency_concept" for issue in result.issues)
    # A unit of the wrong *kind* (shares for a monetary concept) is rejected outright.
    assert result.stats["observations_skipped_unit_mismatch"] >= 1
    assert any(issue["code"] == "unit_kind_mismatch" for issue in result.issues)


def test_companyfacts_rejects_malformed_payload():
    with pytest.raises(ParseError):
        parse_companyfacts({}, issuer_id="ISS-CIK1", source_id="sec-edgar", source_url="x")


def test_availability_falls_back_to_date_when_acceptance_missing():
    payload = {
        "cik": 1,
        "entityName": "Fallback Corp",
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            {"end": "2024-03-31", "val": 1000, "accn": "A-1", "form": "10-Q", "filed": "2024-05-01"}
                        ]
                    }
                }
            }
        },
    }
    result = parse_companyfacts(
        payload, issuer_id="ISS-CIK0000000001", source_id="sec-edgar", source_url="x"
    )
    record = result.records[0]
    assert record.availability_precision == "date"
    assert record.availability_time == "2024-05-01T23:59:59Z"
    assert record.availability_basis == "sec_companyfacts.filed_date_end_of_day_utc"


def test_observation_without_filed_date_gets_unknown_availability():
    payload = {
        "cik": 1,
        "entityName": "Undated Corp",
        "facts": {
            "us-gaap": {
                "Assets": {"units": {"USD": [{"end": "2024-03-31", "val": 1000, "accn": "A-1"}]}}
            }
        },
    }
    result = parse_companyfacts(payload, issuer_id="ISS-CIK0000000001", source_id="sec-edgar", source_url="x")
    assert result.records[0].availability_precision == "unknown"
    assert result.records[0].availability_time is None


def test_magnitude_outflow_negative_value_is_flagged_not_flipped():
    payload = {
        "cik": 1,
        "entityName": "Negative Capex Corp",
        "facts": {
            "us-gaap": {
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "units": {
                        "USD": [
                            {
                                "start": "2024-01-01",
                                "end": "2024-03-31",
                                "val": -500,
                                "accn": "A-1",
                                "form": "10-Q",
                                "filed": "2024-05-01",
                            }
                        ]
                    }
                }
            }
        },
    }
    result = parse_companyfacts(payload, issuer_id="ISS-CIK0000000001", source_id="sec-edgar", source_url="x")
    record = result.records[0]
    assert record.value_numeric == "-500"  # reported sign preserved
    assert record.quality == "suspect"
    assert record.derivation_kind == "normalized_source_observation"
    assert any(issue["code"] == "negative_outflow_value" for issue in result.issues)


def test_duplicate_observations_in_one_filing_are_deduplicated():
    observation = {
        "start": "2024-01-01", "end": "2024-03-31", "val": 100, "accn": "A-1",
        "form": "10-Q", "filed": "2024-05-01",
    }
    payload = {
        "cik": 1,
        "entityName": "Duplicate Corp",
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": [observation, dict(observation)]}}}},
    }
    result = parse_companyfacts(payload, issuer_id="ISS-CIK0000000001", source_id="sec-edgar", source_url="x")
    assert len(result.records) == 1
    assert result.stats["observations_deduplicated"] == 1


def test_conflicting_values_in_one_filing_are_suspect():
    base = {"start": "2024-01-01", "end": "2024-03-31", "accn": "A-1", "form": "10-Q", "filed": "2024-05-01"}
    payload = {
        "cik": 1,
        "entityName": "Contradiction Corp",
        "facts": {"us-gaap": {"Revenues": {"units": {"USD": [dict(base, val=100), dict(base, val=101)]}}}},
    }
    result = parse_companyfacts(payload, issuer_id="ISS-CIK0000000001", source_id="sec-edgar", source_url="x")
    assert len(result.records) == 1
    assert result.records[0].quality == "suspect"
    assert any(issue["code"] == "conflicting_values_same_filing" for issue in result.issues)


def test_unmapped_tags_are_reported_not_guessed():
    payload = {
        "cik": 1,
        "entityName": "Unmapped Corp",
        "facts": {"us-gaap": {"SomeBrandNewElement": {"units": {"USD": [{"end": "2024-03-31", "val": 1}]}}}},
    }
    result = parse_companyfacts(payload, issuer_id="ISS-CIK0000000001", source_id="sec-edgar", source_url="x")
    assert result.records == []
    assert "us-gaap:SomeBrandNewElement" in result.unmapped_tags


# --------------------------------------------------------------------------- #
# Sync orchestration
# --------------------------------------------------------------------------- #
def test_sync_from_fixtures_then_again_is_idempotent(db, apple_payloads):
    submissions, facts = apple_payloads
    ingestor = SecIngestor(db)
    first = ingestor.sync_payloads(
        APPLE_CIK, submissions_payload=submissions, companyfacts_payload=facts
    )
    kernel = EvidenceKernel(db)
    count_after_first = kernel.count()
    assert count_after_first == first.evidence["written"]
    assert count_after_first > 50
    assert first.filings_written >= 100
    assert first.issuer_id == "ISS-CIK0000320193"
    assert first.securities and first.securities[0]["ticker"] == "AAPL"
    assert first.securities[0]["status"] == "probable"  # share-class inference is not certain

    second = ingestor.sync_payloads(
        APPLE_CIK, submissions_payload=submissions, companyfacts_payload=facts
    )
    assert second.evidence["inserted"] == 0
    assert second.evidence["duplicates"] == count_after_first
    assert kernel.count() == count_after_first


def test_sync_preserves_history_when_source_value_is_corrected(db, restatement_payloads):
    submissions, facts = restatement_payloads
    ingestor = SecIngestor(db)
    ingestor.sync_payloads(RESTATEMENT_CIK, submissions_payload=submissions, companyfacts_payload=facts)
    kernel = EvidenceKernel(db)
    before = [r for r in kernel.history("ISS-CIK0001999999", "revenue") if r.unit == "USD"]
    assert len(before) == 2

    corrected = copy.deepcopy(facts)
    for observation in corrected["facts"]["us-gaap"][
        "RevenueFromContractWithCustomerExcludingAssessedTax"
    ]["units"]["USD"]:
        if observation["accn"] == "0001999999-24-000009":
            observation["val"] = 89000000
    ingestor.sync_payloads(RESTATEMENT_CIK, submissions_payload=submissions, companyfacts_payload=corrected)
    after = [r for r in kernel.history("ISS-CIK0001999999", "revenue") if r.unit == "USD"]
    assert len(after) == 3  # original, first restatement, corrected restatement
    assert [record.value_numeric for record in after] == ["100000000", "90000000", "89000000"]
    # The as-of answer before the restatement is still the original number.
    early = kernel.as_of("ISS-CIK0001999999", "2024-06-01T00:00:00Z", concepts=["revenue"])
    assert next(fact for fact in early.facts if fact.unit == "USD").value == "100000000"


def test_sync_registers_raw_documents_for_provenance(db):
    from atlas.ingestion.sec_sync import register_fixture_documents

    submissions_doc, facts_doc = register_fixture_documents(db, SEC_DIR, APPLE_CIK)
    assert submissions_doc and facts_doc
    row = db.query_one("SELECT * FROM raw_document WHERE doc_id = ?", (facts_doc,))
    assert row["byte_size"] > 100_000
    assert row["url"].startswith("fixture://")


# --------------------------------------------------------------------------- #
# Client policy and behaviour
# --------------------------------------------------------------------------- #
def test_user_agent_policy_is_enforced():
    with pytest.raises(SecPolicyError):
        validate_user_agent(None)
    with pytest.raises(SecPolicyError):
        validate_user_agent("AtlasQuant/0.1")
    assert validate_user_agent("AtlasQuant/0.1 research@example.com")


def test_client_refuses_non_sec_hosts():
    client = SecClient(user_agent="Atlas/0.1 test@example.com", transport=lambda request, timeout: (200, {}, b"{}"))
    with pytest.raises(ValidationError):
        client.get("https://example.com/data.json")


def test_client_caches_with_etag(db):
    calls = []

    def transport(request, timeout):
        calls.append(request)
        if len(calls) == 1:
            return 200, {"ETag": '"v1"', "Content-Type": "application/json"}, b'{"ok": true}'
        return 304, {}, b""

    client = SecClient(user_agent="Atlas/0.1 test@example.com", db=db, transport=transport)
    url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    first = client.get(url)
    assert first.status == 200 and first.from_cache is False and first.doc_id
    second = client.get(url)
    assert second.status == 304 and second.from_cache is True
    assert second.body == first.body
    conditional = {key.lower() for key in calls[1].headers}
    assert "if-none-match" in conditional


def test_client_retries_server_errors_with_backoff(db):
    responses = [503, 502, 200]
    sleeps: list[float] = []

    def transport(request, timeout):
        status = responses.pop(0)
        return status, {}, b'{"ok": true}' if status == 200 else b""

    client = SecClient(
        user_agent="Atlas/0.1 test@example.com",
        db=db,
        transport=transport,
        sleep=sleeps.append,
        jitter=lambda: 0.0,
    )
    result = client.get("https://data.sec.gov/submissions/CIK0000320193.json")
    assert result.status == 200
    assert result.attempts == 3
    assert len(sleeps) == 2
    assert sleeps[0] < sleeps[1]  # exponential


def test_client_surfaces_policy_rejection(db):
    client = SecClient(
        user_agent="Atlas/0.1 test@example.com",
        db=db,
        transport=lambda request, timeout: (403, {}, b""),
    )
    with pytest.raises(SecPolicyError):
        client.get("https://data.sec.gov/submissions/CIK0000320193.json")


def test_rate_limiter_blocks_beyond_rate():
    clock = [0.0]
    sleeps: list[float] = []

    def now():
        return clock[0]

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    bucket = TokenBucket(2.0, capacity=1.0, clock=now, sleep=sleep)
    bucket.acquire()
    bucket.acquire()
    assert sleeps and sleeps[0] == pytest.approx(0.5)
