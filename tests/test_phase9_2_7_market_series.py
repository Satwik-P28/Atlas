"""Phase 9.2.7: one canonical market series, and changes computed on it.

The failure these tests exist for is a *series* that contains more than one provider's
statement about the same session, or a change computed across two incompatible
observations. A chart can look perfectly reasonable while doing that, so the assertions
here are on meaning — which session, which provider, which revision, which basis — and
they are checked independently for the Markets overview, the chart and the historical
issuer metrics.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from atlas.entities.master import SecurityMaster
from atlas.market import evidence
from atlas.market.actions import ActionStore, ActionType, CorporateAction
from atlas.market.calendar import TradingCalendar
from atlas.research import prices
from atlas.terminal import read_models
from atlas.terminal.api import create_app

DAY_ONE = "2025-01-02"
DAY_TWO = "2025-01-03"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "openapi_phase9_2_7.json"


# ----------------------------------------------------------------------- helpers
def _identity(db, *, ticker: str = "TST", mic: str = "XNYS"):
    master = SecurityMaster(db)
    master.ensure_venue("XNYS", "New York Stock Exchange", country="US", timezone="America/New_York")
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer = master.register_issuer(legal_name="Test Bank", cik="1000001", sic="6021")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, mic, valid_from="2020-01-01", is_primary=True)
    master.assign_ticker(
        listing, ticker, valid_from="2020-01-01", confidence=1.0, status="confirmed",
        source_id="sec-edgar",
    )
    return master, issuer, security, listing


def _rows(pairs):
    return [
        {
            "date": day,
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 1.0,
            "close": close,
            "volume": 1000,
        }
        for day, close in pairs
    ]


def _import(
    db,
    pairs,
    *,
    source: str = "Provider A",
    redistribution: str = "restricted",
    licence: str = "Vendor terms",
    mic: str | None = None,
    ticker: str = "TST",
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


def _issuer_id(issuer) -> str:
    return issuer if isinstance(issuer, str) else issuer["issuer_id"]


def _business_days(start: str, end: str) -> list[str]:
    day, last, out = date.fromisoformat(start), date.fromisoformat(end), []
    while day <= last:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def _series(db, security, *, start="2025-01-01", end="2025-01-10", **kwargs):
    return evidence.select_series(db, security, mic="XNYS", start=start, end=end, **kwargs)


# ------------------------------------------------- one observation per session
def test_two_providers_on_one_session_produce_one_series_point(db):
    _, _, security, _ = _identity(db)
    first = _import(db, [(DAY_ONE, 10.0), (DAY_TWO, 11.0)], source="Provider A")
    second = _import(db, [(DAY_ONE, 12.0), (DAY_TWO, 13.0)], source="Provider B")

    series = _series(db, security)
    assert series.sessions == 2
    assert len({point.session_date for point in series.points}) == 2
    assert series.policy == "single_provider_held_constant"
    assert series.source_id == min(
        first["source"]["source_id"], second["source"]["source_id"]
    )
    # The rejected provider is reported, never interpolated into the series.
    assert series.excluded_providers == tuple(
        sorted({first["source"]["source_id"], second["source"]["source_id"]} - {series.source_id})
    )
    assert any("excluded" in note for note in series.limitations)


def test_one_day_change_uses_the_previous_distinct_session_of_the_same_provider(db):
    _, _, security, _ = _identity(db)
    first = _import(db, [(DAY_ONE, 100.0), (DAY_TWO, 110.0)], source="Provider A")
    _import(db, [(DAY_ONE, 200.0), (DAY_TWO, 200.0)], source="Provider B")

    series = _series(db, security, source_id=first["source"]["source_id"])
    assert series.points[-1].source_id == series.points[-2].source_id
    change = evidence.series_changes(series, [], basis="price")
    assert change.one_day == pytest.approx(0.10)
    assert change.one_day_from["session_date"] == DAY_ONE
    assert change.one_day_to["session_date"] == DAY_TWO
    assert change.one_day_from["source_id"] == change.one_day_to["source_id"]
    # Both sessions used the same provider, so the change is that provider's own move.
    assert change.one_day != pytest.approx(0.0)


def test_series_never_splices_a_second_provider_into_a_gap(db):
    _, _, security, _ = _identity(db)
    first = _import(db, [(DAY_ONE, 100.0)], source="Provider A")
    second = _import(db, [(DAY_TWO, 120.0)], source="Provider B")

    series = _series(db, security)
    assert series.sessions == 1
    chosen = min(first["source"]["source_id"], second["source"]["source_id"])
    assert series.source_id == chosen
    assert series.points[0].session_date == DAY_ONE if chosen == first["source"]["source_id"] else DAY_TWO
    assert set(series.excluded_providers) == {
        first["source"]["source_id"], second["source"]["source_id"]
    } - {chosen}


def test_explicit_source_holds_one_provider_and_states_the_policy(db):
    _, _, security, _ = _identity(db)
    _import(db, [(DAY_ONE, 100.0), (DAY_TWO, 110.0)], source="Provider A")
    second = _import(db, [(DAY_ONE, 200.0), (DAY_TWO, 220.0)], source="Provider B")
    chosen = second["source"]["source_id"]

    series = _series(db, security, source_id=chosen)
    assert series.policy == "explicit_source"
    assert series.requested_source_id == chosen
    assert series.source_id == chosen
    assert all(point.source_id == chosen for point in series.points)


def test_second_venue_is_never_mixed_into_the_series(db):
    master, _, security, _ = _identity(db)
    second_listing = master.ensure_listing(security, "XNAS", valid_from="2020-01-01")
    master.assign_ticker(
        second_listing, "TSN", valid_from="2020-01-01", confidence=1.0, status="confirmed",
        source_id="sec-edgar",
    )
    _import(db, [(DAY_ONE, 100.0), (DAY_TWO, 101.0)], source="Provider A", mic="XNYS")
    _import(
        db, [(DAY_ONE, 200.0), (DAY_TWO, 202.0)], source="Provider A", mic="XNAS", ticker="TSN"
    )

    series = _series(db, security)
    assert series.mic == "XNYS"
    assert all(point.mic == "XNYS" for point in series.points)
    assert [float(point.close) for point in series.points] == [100.0, 101.0]


# --------------------------------------------------------- return conventions
def test_short_series_refuses_to_invent_a_one_year_change(db):
    _, _, security, _ = _identity(db)
    _import(db, [(DAY_ONE, 100.0), (DAY_TWO, 101.0)], source="Provider A")

    change = evidence.series_changes(_series(db, security), [], basis="price")
    assert change.one_year is None
    assert change.one_year_target == "2024-01-03"
    assert any("does not reach" in note for note in change.limitations)


def test_one_year_change_uses_the_session_at_or_before_the_calendar_date(db):
    _, _, security, _ = _identity(db)
    days = _business_days("2023-12-28", "2024-12-31")
    _import(db, [(day, 100.0 + index * 0.1) for index, day in enumerate(days)], source="Provider A")

    series = _series(db, security, start="2023-12-01", end="2024-12-31")
    change = evidence.series_changes(series, [], basis="price")
    assert change.one_year is not None
    assert change.one_year_target == "2023-12-31"
    assert change.one_year_from["session_date"] <= "2023-12-31"
    assert change.one_year_span_days is not None and change.one_year_span_days >= 365
    expected = (
        float(series.points[-1].close) / change.one_year_from["close"] - 1
    )
    assert change.one_year == pytest.approx(expected)


def test_split_adjustment_is_applied_to_the_change_and_labelled(db):
    _, _, security, _ = _identity(db)
    _import(db, [("2024-01-02", 100.0), ("2024-01-03", 50.0)], source="Provider A")
    ActionStore(db).add(
        CorporateAction(
            security_id=security,
            action_type=ActionType.SPLIT.value,
            source_id="atlas-synthetic",
            ex_date="2024-01-03",
            ratio_from=Decimal(1),
            ratio_to=Decimal(2),
        )
    )
    actions = ActionStore(db).list(security, computable_only=True)
    series = _series(db, security, start="2024-01-01", end="2024-01-05")

    raw = evidence.series_changes(series, actions, basis="price")
    adjusted = evidence.series_changes(series, actions, basis="split_adjusted")
    assert raw.one_day == pytest.approx(-0.5)
    assert adjusted.one_day == pytest.approx(0.0)
    assert raw.basis == "price" and adjusted.basis == "split_adjusted"
    assert any("corporate action" in note for note in raw.limitations)
    assert "not reinvested" in adjusted.label


def test_dividend_income_is_only_in_the_total_return_basis(db):
    _, _, security, _ = _identity(db)
    _import(db, [("2024-01-02", 100.0), ("2024-01-03", 100.0)], source="Provider A")
    ActionStore(db).add(
        CorporateAction(
            security_id=security,
            action_type=ActionType.CASH_DIVIDEND.value,
            source_id="atlas-synthetic",
            ex_date="2024-01-03",
            cash_amount=Decimal("5"),
            currency="USD",
        )
    )
    actions = ActionStore(db).list(security, computable_only=True)
    series = _series(db, security, start="2024-01-01", end="2024-01-05")

    price = evidence.series_changes(series, actions, basis="price")
    adjusted = evidence.series_changes(series, actions, basis="split_adjusted")
    total = evidence.series_changes(series, actions, basis="total_return")
    assert price.one_day == pytest.approx(0.0)
    assert adjusted.one_day == pytest.approx(0.0)
    assert total.one_day == pytest.approx(0.05)
    assert "dividends reinvested" in total.label


def test_unknown_return_basis_is_rejected(db):
    _, _, security, _ = _identity(db)
    _import(db, [(DAY_ONE, 100.0)], source="Provider A")
    with pytest.raises(evidence.PolicyError):
        evidence.series_changes(_series(db, security), [], basis="adjusted_close")


def test_holiday_gap_is_reported_and_not_filled(db):
    _, _, security, _ = _identity(db)
    TradingCalendar(db).build("XNYS", "2024-01-02", "2024-01-05")
    _import(db, [("2024-01-02", 100.0), ("2024-01-05", 102.0)], source="Provider A")

    series = _series(db, security, start="2024-01-02", end="2024-01-05")
    assert series.sessions == 2
    assert series.coverage["requested_sessions"] == 4
    assert series.missing_sessions == 2
    assert any(point.session_date == "2024-01-03" for point in series.points) is False


# ------------------------------------------------------------- corrections/pins
def test_correction_advances_the_series_and_the_pin_still_replays(db):
    _, _, security, _ = _identity(db)
    _import(db, [(DAY_ONE, 100.0), (DAY_TWO, 105.0)], source="Provider A")
    original = prices.price_on_or_before(db, security, DAY_TWO)
    pin = original["pin"]

    _import(db, [(DAY_TWO, 150.0)], source="Provider A")
    series = _series(db, security)
    assert float(series.points[-1].close) == 150.0
    assert series.points[-1].revision_seq == 2

    replay = prices.price_for_pin(db, pin)
    assert replay["status"] == "exact"
    assert replay["price"]["close"] == 105.0


def test_restricted_series_is_not_exportable(db):
    _, _, security, _ = _identity(db)
    _import(db, [(DAY_ONE, 100.0)], source="Provider A", redistribution="restricted")
    assert _series(db, security).export_allowed is False

    _, _, permitted, _ = _identity(db, ticker="TS2")
    _import(db, [(DAY_ONE, 100.0)], source="Provider A", redistribution="permitted", ticker="TS2")
    assert _series(db, permitted).export_allowed is True


# ----------------------------------------------------- overview/chart agreement
def test_markets_overview_and_chart_resolve_the_same_observation(db):
    _, issuer, security, _ = _identity(db)
    _import(db, [(DAY_ONE, 100.0), (DAY_TWO, 110.0)], source="Provider A")

    overview = read_models.market_overview(db)
    item = next(row for row in overview["items"] if row["security_id"] == security)
    selection = evidence.select_price(db, security, "2999-12-31", mic="XNYS")
    assert item["price_observation_id"] == selection.observation.observation_id
    assert item["last_close"] == float(selection.observation.close)
    assert item["last_bar_date"] == selection.observation.session_date
    assert item["sessions"] == 2
    assert item["change_basis"] == "split_adjusted"
    assert item["change_1d"] == pytest.approx(0.10)
    assert item["sparkline"] == [100.0, 110.0]
    assert item["series_policy"] == "single_provider_held_constant"

    chart = read_models.market_series(db, security, range_key="MAX")
    assert [bar["date"] for bar in chart["bars"]] == [DAY_ONE, DAY_TWO]
    assert chart["bars"][-1]["close"] == item["last_close"]
    assert chart["series"]["source_id"] == selection.observation.source_id
    assert chart["last_bar"]["source_id"] == selection.observation.source_id

    metrics = read_models.issuer_metrics(db, _issuer_id(issuer))
    assert metrics["price_observation_id"] == item["price_observation_id"]


# ------------------------------------------------------------ historical cutoff
def test_historical_metrics_cannot_use_a_price_after_the_cutoff(db):
    _, issuer, security, _ = _identity(db)
    _import(db, [("2024-06-28", 100.0), ("2024-07-01", 120.0)], source="Provider A")

    current = read_models.issuer_metrics(db, _issuer_id(issuer))
    assert current["market_basis"] == "current_market"
    assert current["price"] == 120.0
    assert current["price_as_of"] == "2024-07-01"

    historical = read_models.issuer_metrics(
        db, _issuer_id(issuer), as_of="2024-06-30T00:00:00Z"
    )
    assert historical["market_basis"] == "point_in_time"
    assert historical["market_cutoff"] == "2024-06-30"
    assert historical["price"] == 100.0
    assert historical["price_as_of"] == "2024-06-28"
    assert any("point-in-time" in note for note in historical["notes"])

    empty = read_models.issuer_metrics(db, _issuer_id(issuer), as_of="2024-06-01T00:00:00Z")
    assert empty["price"] is None
    assert empty["price_observation_id"] is None


def test_corrected_price_does_not_enter_an_earlier_point_in_time_run(db):
    _, issuer, security, _ = _identity(db)
    _import(db, [("2024-06-28", 100.0)], source="Provider A")
    before = read_models.issuer_metrics(db, _issuer_id(issuer), as_of="2024-06-30T00:00:00Z")

    _import(db, [("2024-06-28", 130.0)], source="Provider A")
    after = read_models.issuer_metrics(db, _issuer_id(issuer), as_of="2024-06-30T00:00:00Z")
    # The corrected revision is what Atlas stores now; the response must say that the
    # vendor vintage on the cutoff date is not reconstructable.
    assert after["price"] == 130.0
    assert after["price_observation_id"] != before["price_observation_id"]
    assert any("vendor vintage is not" in note for note in after["notes"])


# --------------------------------------------------------- API contract check
def _project(schema: dict) -> dict:
    return {
        "openapi": schema["openapi"],
        "info": schema["info"],
        "paths": {
            path: {
                method: {
                    "operationId": op.get("operationId"),
                    "tags": op.get("tags"),
                    "parameters": [
                        {key: parameter.get(key) for key in ("name", "in", "required", "schema")}
                        for parameter in op.get("parameters", [])
                    ],
                    "requestBody": op.get("requestBody"),
                    "responses": op.get("responses"),
                }
                for method, op in sorted(methods.items())
            }
            for path, methods in sorted(schema["paths"].items())
        },
    }


def test_openapi_contract_is_unchanged():
    expected = json.loads(FIXTURE.read_text())
    app = create_app("var/does-not-exist.db")
    current = _project(app.openapi())
    assert current == expected
    assert sum(len(methods) for methods in current["paths"].values()) == 139
