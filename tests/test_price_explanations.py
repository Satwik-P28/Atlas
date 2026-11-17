"""Price Movement Intelligence: interval semantics, return conventions and evidence time.

The failures these tests exist for are the ones that make an explanation look plausible
while being wrong: a return compounded additively, a raw price change called
performance across a split, an event used that was published after the information
cutoff, a residual presented as a cause, or a confident answer where Atlas holds no
company-specific evidence.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from atlas.core.errors import ValidationError
from atlas.entities.master import SecurityMaster
from atlas.market.actions import ActionStore, CorporateAction
from atlas.research import move_intelligence as mi
from atlas.research import prices
from atlas.terminal.api import create_app

DAY_ONE = "2025-01-02"
DAY_TWO = "2025-01-03"
DAY_THREE = "2025-01-06"


def _identity(
    db, *, ticker: str = "TST", mic: str = "XNYS", cik: str = "1000001", currency: str = "USD"
):
    master = SecurityMaster(db)
    master.ensure_venue("XNYS", "New York Stock Exchange", country="US", timezone="America/New_York")
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer_id = master.register_issuer(legal_name=f"Test {ticker} Corp", cik=cik, sic="6021")
    security_id = master.ensure_security(issuer_id, class_designation="common stock", currency=currency)
    listing_id = master.ensure_listing(security_id, mic, valid_from="2020-01-01", is_primary=True)
    master.assign_ticker(
        listing_id, ticker, valid_from="2020-01-01", confidence=1.0, status="confirmed",
        source_id="sec-edgar",
    )
    return master, issuer_id, security_id


def _rows(pairs):
    return [
        {
            "date": day,
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000,
        }
        for day, close in pairs
    ]


def _import(
    db,
    ticker: str,
    pairs,
    *,
    source: str = "Provider A",
    redistribution: str = "project_authored",
    licence: str = "Project-authored test series",
    mic: str = "XNYS",
):
    return prices.import_price_series(
        db,
        ticker=ticker,
        rows=_rows(pairs),
        source_name=source,
        licence=licence,
        redistribution=redistribution,
        adjustment_semantics="unadjusted",
        mic=mic,
    )


def _request(security_id: str, **overrides) -> mi.ExplanationRequest:
    params = {
        "security_id": security_id,
        "start_session": DAY_ONE,
        "end_session": DAY_THREE,
    }
    params.update(overrides)
    return mi.ExplanationRequest(**params)


def _business_days(start: str, end: str) -> list[str]:
    day, last, out = date.fromisoformat(start), date.fromisoformat(end), []
    while day <= last:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def _add_filing(
    db,
    *,
    issuer_id: str,
    accession: str,
    form_type: str,
    filed_date: str,
    acceptance: str | None,
    is_amendment: bool = False,
    amends: str | None = None,
    cik: str = "1000001",
):
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
            "primary.htm",
            int(is_amendment),
            amends,
            "sec-edgar",
        ),
    )


# ------------------------------------------------------------------ return maths
def test_multi_session_return_is_compounded_not_added(db):
    _, _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 110.0), (DAY_THREE, 121.0)])

    result = mi.explain_range(db, _request(security_id))
    stats = result["price_statistics"]

    assert stats["sessions"] == 3
    # 100 -> 121 is 21%; adding the two 10% daily moves would give a false 20%.
    assert stats["interval_return"] == pytest.approx(0.21)
    assert stats["start_price"] == pytest.approx(100.0)
    assert stats["end_price"] == pytest.approx(121.0)
    assert stats["basis_reconciliation"]["raw"] == pytest.approx(0.21)


def test_requested_interval_is_snapped_to_actual_sessions(db):
    _, _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])

    # 2025-01-04 is a Saturday: the nearest stored session is Monday 2025-01-06.
    result = mi.explain_range(
        db, _request(security_id, start_session="2025-01-04", end_session=DAY_THREE)
    )

    codes = {warning["code"] for warning in result["warnings"]}
    assert result["selection"]["start_session"] == DAY_THREE
    assert mi.W_RANGE_SNAPPED in codes
    assert mi.W_SINGLE_SESSION in codes
    assert result["price_statistics"]["interval_return"] == pytest.approx(0.0)
    assert result["price_statistics"]["start_observation_id"] == result["price_statistics"]["end_observation_id"]


def test_reversed_drag_direction_is_normalised_and_reported(db):
    _, _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 105.0), (DAY_THREE, 110.0)])

    result = mi.explain_range(
        db, _request(security_id, start_session=DAY_THREE, end_session=DAY_ONE)
    )

    codes = {warning["code"] for warning in result["warnings"]}
    assert mi.W_RANGE_REVERSED in codes
    assert result["selection"]["start_session"] == DAY_ONE
    assert result["selection"]["end_session"] == DAY_THREE
    assert result["price_statistics"]["interval_return"] == pytest.approx(0.10)


def test_raw_split_move_is_reconciled_against_split_adjusted_and_total_return(db):
    _, _, security_id = _identity(db)
    # A 2-for-1 split on the second session: the raw close halves, wealth does not.
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 50.0), (DAY_THREE, 50.0)])
    ActionStore(db).add(
        CorporateAction(
            security_id=security_id,
            action_type="split",
            source_id="sec-edgar",
            ex_date=DAY_TWO,
            ratio_from=Decimal("1"),
            ratio_to=Decimal("2"),
            availability_time="2025-01-01T12:00:00Z",
            availability_precision="exact",
            notes="2-for-1 split",
        )
    )

    result = mi.explain_range(db, _request(security_id))
    reconciliation = result["price_statistics"]["basis_reconciliation"]

    assert reconciliation["raw"] == pytest.approx(-0.5)
    assert reconciliation["split_adjusted"] == pytest.approx(0.0)
    assert reconciliation["total_return"] == pytest.approx(0.0)
    assert reconciliation["splits_in_window"] == 1
    # The mechanical corporate action is an explanation that must outrank any narrative.
    assert result["hypotheses"][0]["relevance"]["tier"] == 1
    # Asking for the raw basis is allowed, but it must carry the warning that the move is
    # mechanically distorted by the split.
    raw = mi.explain_range(db, _request(security_id, price_basis="price"))
    assert raw["price_statistics"]["interval_return"] == pytest.approx(-0.5)
    assert any(
        warning["code"] == "raw_basis_spans_corporate_action" for warning in raw["warnings"]
    )


def test_total_return_reinvests_a_dividend_that_sits_in_the_window(db):
    _, _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 100.0), (DAY_THREE, 100.0)])
    ActionStore(db).add(
        CorporateAction(
            security_id=security_id,
            action_type="cash_dividend",
            source_id="sec-edgar",
            ex_date=DAY_TWO,
            cash_amount=Decimal("2"),
            currency="USD",
            availability_time="2025-01-01T12:00:00Z",
        )
    )

    result = mi.explain_range(db, _request(security_id))
    reconciliation = result["price_statistics"]["basis_reconciliation"]

    assert reconciliation["raw"] == pytest.approx(0.0)
    assert reconciliation["total_return"] == pytest.approx(0.02)
    assert reconciliation["dividends_in_window"] == 1


# ---------------------------------------------------------------- time semantics
def test_historical_mode_excludes_evidence_published_after_its_cutoff(db):
    _, issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    _add_filing(
        db, issuer_id=issuer_id, accession="0001000001-25-000001", form_type="8-K",
        filed_date=DAY_TWO, acceptance="2025-01-03T21:10:00Z",
    )
    # Filed inside the window but only publicly accepted much later: not knowable at the cutoff.
    _add_filing(
        db, issuer_id=issuer_id, accession="0001000001-25-000002", form_type="8-K/A",
        filed_date=DAY_THREE, acceptance="2025-01-20T12:00:00Z", is_amendment=True,
        amends="0001000001-25-000001",
    )

    historical = mi.explain_range(
        db,
        _request(
            security_id,
            mode=mi.MODE_HISTORICAL,
            information_cutoff="2025-01-15",
        ),
    )
    accessions = {item["accession_number"] for item in historical["events"]["items"]}
    assert accessions == {"0001000001-25-000001"}
    assert historical["events"]["coverage"]["sec_filings"]["excluded_after_cutoff"] == 1
    assert any(
        warning["code"] == "evidence_filtered_by_cutoff" for warning in historical["warnings"]
    )
    assert any(warning["code"] == mi.W_PARAMETRIC_HINDSIGHT for warning in historical["warnings"])

    retrospective = mi.explain_range(
        db, _request(security_id, mode=mi.MODE_RETROSPECTIVE)
    )
    by_accession = {item["accession_number"]: item for item in retrospective["events"]["items"]}
    assert by_accession["0001000001-25-000002"]["relation"] == "subsequent"
    assert by_accession["0001000001-25-000002"]["known_at_range_end"] is False
    # Subsequent evidence is reviewed but never supports the explanation ranking.
    supporting = {
        evidence_id
        for hypothesis in retrospective["hypotheses"]
        for evidence_id in hypothesis["relevance"]["supporting_evidence"]
    }
    assert by_accession["0001000001-25-000002"]["event_id"] not in supporting
    assert retrospective["revision_check"]["status"] == "revisions_found"


def test_historical_mode_without_a_cutoff_is_refused(db):
    _, _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])

    with pytest.raises(ValidationError) as error:
        mi.explain_range(db, _request(security_id, mode=mi.MODE_HISTORICAL))
    assert error.value.context["code"] == mi.REFUSAL_MODE


def test_cutoff_before_the_interval_end_is_refused(db):
    _, _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])

    with pytest.raises(ValidationError) as error:
        mi.explain_range(
            db,
            _request(security_id, mode=mi.MODE_HISTORICAL, information_cutoff=DAY_TWO),
        )
    assert error.value.context["code"] == mi.REFUSAL_CUTOFF


def test_unsupported_timeframe_is_refused_rather_than_served_daily_bars(db):
    _, _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])

    with pytest.raises(ValidationError) as error:
        mi.explain_range(db, _request(security_id, timeframe="1m"))
    assert error.value.context["code"] == mi.REFUSAL_TIMEFRAME
    assert error.value.context["supported"] == ["1d"]


# -------------------------------------------------------------- attribution
def test_market_model_uses_only_pre_interval_sessions_and_reports_beta(db):
    _, _, security_id = _identity(db)
    _, _, benchmark_id = _identity(db, ticker="BMK", cik="1000002")
    days = _business_days("2024-09-02", DAY_THREE)
    benchmark_close, security_close = 100.0, 100.0
    pairs_security, pairs_benchmark = [], []
    for index, day in enumerate(days):
        if index:
            # Varying but deterministic returns: a constant benchmark return has no
            # identifiable slope at all, which is a different case (covered below).
            benchmark_return = 0.001 + 0.0005 * math.sin(index * 1.7)
            benchmark_close *= 1 + benchmark_return
            # Exactly twice the benchmark's daily return: beta must be 2.
            security_close *= 1 + 2 * benchmark_return
        pairs_security.append((day, security_close))
        pairs_benchmark.append((day, benchmark_close))
    _import(db, "TST", pairs_security)
    _import(db, "BMK", pairs_benchmark, source="Provider A")

    result = mi.explain_range(
        db,
        _request(
            security_id,
            start_session=days[-3],
            end_session=days[-1],
            benchmark_security_id=benchmark_id,
            estimation_sessions=60,
        ),
    )
    model = result["market_model"]

    assert model["status"] == "available"
    assert model["beta"] == pytest.approx(2.0, abs=1e-9)
    assert model["estimation"]["last_session"] < days[-3]
    # The residual is essentially zero because the security is exactly twice the benchmark
    # daily. It is not *exactly* zero: the decomposition multiplies beta by the benchmark's
    # compounded interval return, and cross terms do not vanish. That is the declared
    # limitation, so a tight-but-nonzero tolerance is the honest assertion.
    assert model["residual_return_arithmetic"] == pytest.approx(0.0, abs=5e-5)
    assert model["residual_return_arithmetic"] != 0.0
    assert result["benchmark"]["excess_return_arithmetic"] is not None
    # A residual is not rendered as a cause.
    assert any(
        "not evidence of" in limitation or "not a cause" in limitation
        for limitation in model["applicability"]
    )


def test_short_estimation_window_produces_no_beta_claim(db):
    _, _, security_id = _identity(db)
    _, _, benchmark_id = _identity(db, ticker="BMK", cik="1000002")
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    _import(db, "BMK", [(DAY_ONE, 50.0), (DAY_TWO, 50.5), (DAY_THREE, 51.0)])

    result = mi.explain_range(
        db, _request(security_id, benchmark_security_id=benchmark_id)
    )

    assert result["market_model"]["status"] == "unavailable"
    assert any(
        warning["code"] == mi.W_ESTIMATION_SHORT for warning in result["warnings"]
    )


def test_peer_universe_uses_each_peers_own_series_and_reports_availability(db):
    _, _, security_id = _identity(db)
    _, _, peer_id = _identity(db, ticker="PRX", cik="1000003")
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    _import(db, "PRX", [(DAY_ONE, 50.0), (DAY_TWO, 55.0)])

    result = mi.explain_range(db, _request(security_id, peer_security_ids=(peer_id,)))
    peer = result["peers"][0]

    assert peer["status"] == "available"
    assert peer["sessions"] == 2
    assert peer["return"] == pytest.approx(0.10)
    assert peer["comparable"] is True

    unknown = mi.explain_range(
        db, _request(security_id, peer_security_ids=("SEC-does-not-exist",))
    )
    assert unknown["peers"][0]["status"] == "unavailable"
    assert "unknown security" in unknown["peers"][0]["reason"]


def test_foreign_currency_peer_is_reported_but_not_comparable(db):
    _, _, security_id = _identity(db)
    _, _, peer_id = _identity(db, ticker="PRX", cik="1000003", currency="EUR")
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    prices.import_price_series(
        db,
        ticker="PRX",
        rows=_rows([(DAY_ONE, 50.0), (DAY_TWO, 55.0), (DAY_THREE, 54.0)]),
        source_name="Provider A",
        licence="Project-authored test series",
        redistribution="project_authored",
        adjustment_semantics="unadjusted",
        currency="EUR",
        mic="XNYS",
    )

    result = mi.explain_range(db, _request(security_id, peer_security_ids=(peer_id,)))
    assert result["peers"][0]["comparable"] is False
    assert result["peers"][0]["currency"] == "EUR"


def test_benchmark_in_another_currency_blocks_relative_statistics(db):
    _, _, security_id = _identity(db)
    _, _, benchmark_id = _identity(db, ticker="BMK", cik="1000002", currency="EUR")
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    prices.import_price_series(
        db,
        ticker="BMK",
        rows=_rows([(DAY_ONE, 50.0), (DAY_TWO, 50.5), (DAY_THREE, 51.0)]),
        source_name="Provider A",
        licence="Project-authored test series",
        redistribution="project_authored",
        adjustment_semantics="unadjusted",
        currency="EUR",
        mic="XNYS",
    )

    result = mi.explain_range(db, _request(security_id, benchmark_security_id=benchmark_id))
    assert result["market_model"]["status"] == "unavailable"
    assert result["market_model"]["reason"].startswith("currency mismatch")
    assert any(warning["code"] == mi.W_BENCHMARK_CURRENCY for warning in result["warnings"])


# ------------------------------------------------------------------- integrity
def test_no_company_evidence_produces_an_abstention_not_an_invented_cause(db):
    _, _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 96.0), (DAY_THREE, 92.0)])

    result = mi.explain_range(db, _request(security_id))

    assert result["hypotheses"]
    assert result["hypotheses"][0]["relevance"]["tier"] == 5
    assert result["hypotheses"][0]["epistemic_status"] == "hypothesized"
    assert result["hypotheses"][0]["causal_status"] == "not_identified"
    assert result["events"]["coverage"]["news_archive"]["status"] == "unavailable"
    assert any(warning["code"] == mi.W_NO_NEWS_ARCHIVE for warning in result["warnings"])
    # No hypothesis is allowed to carry a fabricated probability.
    assert all("probability" not in json_keys(hypothesis) for hypothesis in result["hypotheses"])


def test_routine_ownership_filings_are_shown_but_never_ranked_as_an_explanation(db):
    _, issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 96.0), (DAY_THREE, 92.0)])
    _add_filing(
        db, issuer_id=issuer_id, accession="0001000001-25-000010", form_type="4",
        filed_date=DAY_TWO, acceptance="2025-01-03T21:10:00Z",
    )

    result = mi.explain_range(db, _request(security_id))

    # It is a real event and belongs in the timeline...
    assert result["events"]["in_window_count"] == 1
    # ...but a Form 4 is not evidence that a 12% drop was information-driven.
    top = result["hypotheses"][0]
    assert top["relevance"]["tier"] == 5
    assert "routine" in top["statement"]
    assert top["relevance"]["inputs"]["routine_filings_not_ranked"] == 1


def json_keys(payload: dict) -> set[str]:
    keys: set[str] = set()
    stack = [payload]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            keys.update(value.keys())
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return keys


def test_identical_stored_state_reproduces_the_investigation_hash(db):
    _, issuer_id, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    _add_filing(
        db, issuer_id=issuer_id, accession="0001000001-25-000003", form_type="8-K",
        filed_date=DAY_TWO, acceptance="2025-01-03T21:10:00Z",
    )

    first = mi.explain_range(db, _request(security_id))
    second = mi.explain_range(db, _request(security_id))

    assert first["reproducibility"]["hash"] == second["reproducibility"]["hash"]
    # A new filing changes the hash: the investigation is pinned to its evidence set.
    _add_filing(
        db, issuer_id=issuer_id, accession="0001000001-25-000004", form_type="10-Q",
        filed_date=DAY_THREE, acceptance="2025-01-06T21:10:00Z",
    )
    third = mi.explain_range(db, _request(security_id))
    assert third["reproducibility"]["hash"] != first["reproducibility"]["hash"]


def test_restricted_source_blocks_export_and_says_so(db):
    _, _, security_id = _identity(db)
    _import(
        db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)],
        source="Vendor Feed", redistribution="restricted", licence="Vendor terms",
    )

    result = mi.explain_range(db, _request(security_id))

    assert result["rights"]["export_allowed"] is False
    assert result["rights"]["restricted_sources"]
    assert any(warning["code"] == mi.W_RESTRICTED_EXPORT for warning in result["warnings"])


def test_one_candle_selection_reports_a_session_not_a_return_estimate(db):
    _, _, security_id = _identity(db)
    _import(db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])

    result = mi.explain_range(db, _request(security_id, start_session=DAY_TWO, end_session=DAY_TWO))

    assert result["price_statistics"]["sessions"] == 1
    assert result["price_statistics"]["interval_return"] == pytest.approx(0.0)
    assert result["price_statistics"]["daily_volatility"] is None
    assert any(warning["code"] == mi.W_SINGLE_SESSION for warning in result["warnings"])


# ------------------------------------------------------------------------ API
def test_api_exposes_the_versioned_contract(file_db):
    _, _, security_id = _identity(file_db)
    _import(file_db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    client = TestClient(create_app(file_db.path))

    response = client.post(
        f"/api/securities/{security_id}/price-explanations",
        json={
            "start_session": DAY_ONE,
            "end_session": DAY_THREE,
            "price_basis": "split_adjusted",
            "mode": "retrospective_investigation",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schema"] == mi.CONTRACT_VERSION
    assert payload["selection"]["security_id"] == security_id
    assert payload["price_statistics"]["sessions"] == 3
    assert payload["reproducibility"]["hash"]


def test_api_refuses_unknown_security_and_unknown_fields(file_db):
    _, _, security_id = _identity(file_db)
    _import(file_db, "TST", [(DAY_ONE, 100.0), (DAY_TWO, 101.0), (DAY_THREE, 102.0)])
    client = TestClient(create_app(file_db.path))

    missing = client.post(
        "/api/securities/SEC-does-not-exist/price-explanations",
        json={"start_session": DAY_ONE, "end_session": DAY_THREE},
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "unknown_entity"

    typo = client.post(
        f"/api/securities/{security_id}/price-explanations",
        json={"start_session": DAY_ONE, "end_session": DAY_THREE, "information_cutof": "2025-01-03"},
    )
    assert typo.status_code == 422
    assert typo.json()["error"]["code"] == "invalid_request"
