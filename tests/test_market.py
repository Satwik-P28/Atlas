"""Market data: calendars, immutable bars, corporate actions, adjustment mathematics."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from atlas.core.errors import UnsupportedActionError, ValidationError
from atlas.core.temporal import availability_from_instant
from atlas.market.actions import ActionStore, ActionType, CorporateAction
from atlas.market.adjust import split_adjust, split_factor_for, total_return, verify_split_continuity
from atlas.market.bars import ADJUSTMENT_SPLIT, Bar, BarStore
from atlas.market.calendar import (
    TradingCalendar,
    us_equity_early_closes,
    us_equity_holidays,
)
from atlas.storage.quality import list_issues

SOURCE = "atlas-synthetic"


def _bar(security_id: str, session: str, close: str, **overrides) -> Bar:
    values = {
        "security_id": security_id,
        "mic": "XNAS",
        "ts_utc": f"{session}T20:00:00Z",
        "open": Decimal(close),
        "high": Decimal(close),
        "low": Decimal(close),
        "close": Decimal(close),
        "volume": Decimal("1000"),
        "currency": "USD",
        "source_id": SOURCE,
    }
    values.update(overrides)
    return Bar(**values)


def _split(security_id: str, session: str, ratio_to: int, ratio_from: int = 1, **overrides) -> CorporateAction:
    values = {
        "security_id": security_id,
        "action_type": ActionType.SPLIT.value if ratio_to > ratio_from else ActionType.REVERSE_SPLIT.value,
        "source_id": SOURCE,
        "ex_date": session,
        "ratio_from": Decimal(ratio_from),
        "ratio_to": Decimal(ratio_to),
    }
    values.update(overrides)
    return CorporateAction(**values)


# --------------------------------------------------------------------------- #
# Calendar
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "year,holiday",
    [
        (2020, "2020-01-01"),  # New Year
        (2020, "2020-01-20"),  # MLK
        (2020, "2020-02-17"),  # Washington's Birthday
        (2020, "2020-04-10"),  # Good Friday
        (2020, "2020-05-25"),  # Memorial Day
        (2020, "2020-07-03"),  # Independence Day observed (4 July was Saturday)
        (2020, "2020-09-07"),  # Labor Day
        (2020, "2020-11-26"),  # Thanksgiving
        (2020, "2020-12-25"),  # Christmas
        (2021, "2021-07-05"),  # Independence Day observed (4 July Sunday)
        (2021, "2021-12-24"),  # Christmas observed (25 December Saturday)
        (2022, "2022-06-20"),  # Juneteenth observed (19 June Sunday)
    ],
)
def test_us_equity_holidays(year, holiday):
    assert date.fromisoformat(holiday) in us_equity_holidays(year)


def test_juneteenth_only_from_2022():
    assert date(2021, 6, 18) not in us_equity_holidays(2021)
    assert date(2023, 6, 19) in us_equity_holidays(2023)


def test_early_closes_are_declared():
    early = us_equity_early_closes(2020)
    assert date(2020, 11, 27) in early  # day after Thanksgiving
    assert date(2020, 12, 24) in early
    assert date(2020, 11, 26) not in early  # a full holiday, not a short session


def test_calendar_sessions_are_utc_and_respect_early_close(db):
    calendar = TradingCalendar(db)
    calendar.build("XNYS", "2020-11-25", "2020-11-30")
    sessions = calendar.sessions("XNYS", "2020-11-25", "2020-11-30")
    assert [s.session_date for s in sessions] == ["2020-11-25", "2020-11-27", "2020-11-30"]
    normal = sessions[0]
    assert normal.open_ts == "2020-11-25T14:30:00Z"  # 09:30 EST
    assert normal.close_ts == "2020-11-25T21:00:00Z"  # 16:00 EST
    early = sessions[1]
    assert early.is_early_close is True
    assert early.close_ts == "2020-11-27T18:00:00Z"  # 13:00 EST


def test_calendar_handles_daylight_saving(db):
    calendar = TradingCalendar(db)
    calendar.build("XNYS", "2020-03-06", "2020-03-10")
    before = calendar.sessions("XNYS", "2020-03-06", "2020-03-06")[0]
    after = calendar.sessions("XNYS", "2020-03-10", "2020-03-10")[0]
    assert before.open_ts == "2020-03-06T14:30:00Z"  # EST
    assert after.open_ts == "2020-03-10T13:30:00Z"  # EDT


def test_missing_sessions_report_gaps(db):
    calendar = TradingCalendar(db)
    calendar.build("XNYS", "2020-08-31", "2020-09-04")
    missing = calendar.missing_sessions("XNYS", {"2020-08-31", "2020-09-02"}, "2020-08-31", "2020-09-04")
    assert missing == ["2020-09-01", "2020-09-03", "2020-09-04"]


def test_previous_and_next_session(db):
    calendar = TradingCalendar(db)
    calendar.build("XNYS", "2020-08-28", "2020-09-02")
    assert calendar.previous_session("XNYS", "2020-08-31") == "2020-08-28"
    assert calendar.next_session("XNYS", "2020-08-28") == "2020-08-31"
    assert calendar.previous_session("XNYS", "2020-08-28") is None


# --------------------------------------------------------------------------- #
# Bars
# --------------------------------------------------------------------------- #
def test_bars_are_immutable_and_revisions_append(db, apple_security):
    store = BarStore(db)
    first = store.ingest([_bar(apple_security, "2020-08-28", "499.23")])
    assert first.inserted == 1
    duplicate = store.ingest([_bar(apple_security, "2020-08-28", "499.23")])
    assert duplicate.duplicates == 1

    revised = store.ingest([_bar(apple_security, "2020-08-28", "500.00")])
    assert revised.revisions == 1

    revisions = store.revisions(apple_security, "XNAS", "2020-08-28T20:00:00Z")
    assert [bar.close for bar in revisions] == [Decimal("499.23"), Decimal("500.00")]
    assert revisions[1].supersedes_bar == 1
    assert revisions[0].close == Decimal("499.23")  # original untouched

    latest = store.query(apple_security, "XNAS", "2020-08-01", "2020-09-01")
    assert len(latest) == 1 and latest[0].close == Decimal("500.00")
    all_rows = store.query(apple_security, "XNAS", "2020-08-01", "2020-09-01", include_superseded=True)
    assert len(all_rows) == 2
    assert any(issue["code"] == "provider_revision" for issue in list_issues(db, scope="market_bar"))


def test_adjusted_bars_cannot_be_ingested(db, apple_security):
    store = BarStore(db)
    with pytest.raises(ValidationError):
        store.ingest([_bar(apple_security, "2020-08-28", "100", adjustment_status=ADJUSTMENT_SPLIT)])


def test_negative_volume_is_flagged_not_corrected(db, apple_security):
    store = BarStore(db)
    store.ingest([_bar(apple_security, "2020-08-28", "100", volume=Decimal("-5"))])
    stored = store.query(apple_security, "XNAS", "2020-08-01", "2020-09-01")[0]
    assert stored.volume == Decimal("-5")
    assert "negative_volume" in stored.quality_flags
    assert any(issue["code"] == "negative_volume" for issue in list_issues(db, scope="market_bar"))


def test_invalid_ohlc_is_flagged(db, apple_security, calendar):
    store = BarStore(db)
    calendar.build("XNAS", "2020-08-28", "2020-08-28")
    store.ingest([_bar(apple_security, "2020-08-28", "100", high=Decimal("95"), low=Decimal("90"))])
    findings = store.validate(apple_security, "XNAS", calendar=calendar)
    codes = {finding["code"] for finding in findings}
    assert "high_below_other_prices" in codes


def test_bar_on_non_session_day_is_flagged(db, apple_security, calendar):
    store = BarStore(db)
    calendar.build("XNAS", "2020-08-28", "2020-08-31")
    store.ingest([_bar(apple_security, "2020-08-29", "100")])  # Saturday
    findings = store.validate(apple_security, "XNAS", calendar=calendar)
    assert any(finding["code"] == "bar_outside_calendar" for finding in findings)


def test_missing_sessions_are_reported(db, apple_security, calendar):
    store = BarStore(db)
    calendar.build("XNAS", "2020-08-31", "2020-09-04")
    store.ingest([_bar(apple_security, "2020-08-31", "100"), _bar(apple_security, "2020-09-02", "101")])
    findings = store.validate(apple_security, "XNAS", calendar=calendar)
    assert any(finding["code"] == "missing_sessions" for finding in findings)


def test_suspicious_move_is_flagged_unless_an_action_explains_it(db, apple_security):
    store = BarStore(db)
    store.ingest([_bar(apple_security, "2020-08-28", "499.23"), _bar(apple_security, "2020-08-31", "129.04")])
    unexplained = store.validate(apple_security, "XNAS")
    assert any(finding["code"] == "suspicious_price_move" for finding in unexplained)
    explained = store.validate(apple_security, "XNAS", known_action_dates={"2020-08-31"})
    assert any(finding["code"] == "large_move_with_corporate_action" for finding in explained)
    assert not any(finding["code"] == "suspicious_price_move" for finding in explained)


# --------------------------------------------------------------------------- #
# Corporate actions
# --------------------------------------------------------------------------- #
def test_split_requires_consistent_direction(db, apple_security):
    store = ActionStore(db)
    # A "split" that reduces the share count is a type error, not a silent reverse split.
    with pytest.raises(ValidationError):
        store.add(
            _split(apple_security, "2020-08-31", ratio_to=1, ratio_from=4, action_type=ActionType.SPLIT.value)
        )
    with pytest.raises(ValidationError):
        store.add(_split(apple_security, "2020-08-31", ratio_to=4, ratio_from=4))


def test_dividend_requires_amount_and_currency(db, apple_security):
    store = ActionStore(db)
    with pytest.raises(ValidationError):
        store.add(
            CorporateAction(
                security_id=apple_security,
                action_type=ActionType.CASH_DIVIDEND.value,
                source_id=SOURCE,
                ex_date="2020-09-01",
                cash_amount=Decimal("0.205"),
            )
        )
    with pytest.raises(ValidationError):
        store.add(
            CorporateAction(
                security_id=apple_security,
                action_type=ActionType.CASH_DIVIDEND.value,
                source_id=SOURCE,
                ex_date="2020-09-01",
                currency="USD",
            )
        )


def test_ticker_change_action_requires_new_ticker(db, apple_security):
    store = ActionStore(db)
    with pytest.raises(ValidationError):
        store.add(
            CorporateAction(
                security_id=apple_security,
                action_type=ActionType.TICKER_CHANGE.value,
                source_id=SOURCE,
                effective_date="2022-06-09",
            )
        )


def test_action_correction_is_append_only(db, apple_security):
    store = ActionStore(db)
    original_id = store.add(_split(apple_security, "2020-08-31", ratio_to=4))
    corrected = _split(apple_security, "2020-08-31", ratio_to=5, status="corrected")
    new_id = store.correct(original_id, corrected, reason="source errata: ratio was 5-for-1")
    assert store.get(original_id) is not None
    assert store.get(new_id).supersedes == original_id
    assert [action.action_id for action in store.list(apple_security)] == [new_id]
    assert len(store.list(apple_security, include_superseded=True)) == 2


def test_knowledge_filter_excludes_later_actions(db, apple_security):
    store = ActionStore(db)
    store.add(
        _split(apple_security, "2020-08-31", ratio_to=4),
        availability=availability_from_instant("2021-01-15T00:00:00Z", "test"),
    )
    assert store.list(apple_security, knowledge_as_of="2020-12-31") == []
    assert len(store.list(apple_security, knowledge_as_of="2021-06-01")) == 1


def test_declared_but_unimplemented_actions_are_recorded_not_computed(db, apple_security):
    store = ActionStore(db)
    merger = CorporateAction(
        security_id=apple_security,
        action_type=ActionType.MERGER.value,
        source_id=SOURCE,
        effective_date="2024-01-01",
        terms={"acquirer": "DEMO"},
        status="announced",
    )
    action_id = store.add(merger)
    coverage = store.coverage(apple_security)
    assert "merger" in coverage["declared_not_computed"]
    assert "merger" not in coverage["computable_types"]
    assert store.get(action_id).action_type == "merger"
    bars = [_bar(apple_security, "2020-08-28", "100")]
    with pytest.raises(UnsupportedActionError):
        split_adjust(bars, [store.get(action_id)])


# --------------------------------------------------------------------------- #
# Adjustment mathematics
# --------------------------------------------------------------------------- #
def test_split_adjustment_is_mathematically_correct(db, apple_security):
    bars = [
        _bar(apple_security, "2020-08-28", "499.23", volume=Decimal("1000")),
        _bar(apple_security, "2020-08-31", "129.04", volume=Decimal("4000")),
        _bar(apple_security, "2020-09-01", "134.18", volume=Decimal("3500")),
    ]
    action = _split(apple_security, "2020-08-31", ratio_to=4)
    series = split_adjust(bars, [action])
    assert series.reference_date == "2020-09-01"
    # Pre-split closes are divided by 4; the ex-date and later bars are unchanged.
    assert series.bars[0].close == Decimal("124.8075")
    assert series.bars[0].volume == Decimal("4000")
    assert series.bars[1].close == Decimal("129.04")
    assert series.bars[2].close == Decimal("134.18")
    assert [bar.split_factor for bar in series.bars] == [Decimal("4"), Decimal("1"), Decimal("1")]
    # Raw closes preserved, adjusted series consistent with factor.
    for raw, adjusted in zip(bars, series.bars):
        assert adjusted.close * adjusted.split_factor == raw.close
    assert verify_split_continuity(bars, series) == []


def test_reverse_split_multiplies_prices(db, apple_security):
    bars = [_bar(apple_security, "2020-08-28", "0.50"), _bar(apple_security, "2020-08-31", "5.00")]
    action = _split(apple_security, "2020-08-31", ratio_to=1, ratio_from=10)
    series = split_adjust(bars, [action])
    assert series.bars[0].close == Decimal("5.00")
    assert series.bars[0].split_factor == Decimal("0.1")
    assert series.bars[1].close == Decimal("5.00")


def test_split_factor_is_cumulative_across_multiple_splits(db, apple_security):
    splits = [
        _split(apple_security, "2020-08-31", ratio_to=4),
        _split(apple_security, "2022-06-06", ratio_to=2),
    ]
    assert split_factor_for("2020-08-01", splits) == Decimal("8")
    assert split_factor_for("2020-08-31", splits) == Decimal("2")
    assert split_factor_for("2022-06-06", splits) == Decimal("1")


def test_adjustment_never_applied_twice(db, apple_security):
    already = _bar(apple_security, "2020-08-28", "100", adjustment_status=ADJUSTMENT_SPLIT)
    with pytest.raises(ValidationError):
        split_adjust([already], [])


def test_knowledge_filter_withholds_unannounced_splits(db, apple_security):
    bars = [_bar(apple_security, "2020-08-28", "499.23"), _bar(apple_security, "2020-08-31", "129.04")]
    action = _split(apple_security, "2020-08-31", ratio_to=4,
                    availability_time="2021-01-15T00:00:00Z", availability_precision="exact")
    censored = split_adjust(bars, [action], knowledge_as_of="2020-08-30")
    assert censored.bars[0].split_factor == Decimal("1")
    assert censored.bars[0].close == Decimal("499.23")
    assert len(censored.actions_withheld) == 1
    known = split_adjust(bars, [action], knowledge_as_of="2021-06-01")
    assert known.bars[0].split_factor == Decimal("4")


def test_total_return_index_reinvests_dividends(db, apple_security):
    bars = [_bar(apple_security, "2020-09-01", "100"), _bar(apple_security, "2020-09-02", "110"),
            _bar(apple_security, "2020-09-03", "110")]
    dividend = CorporateAction(
        security_id=apple_security,
        action_type=ActionType.CASH_DIVIDEND.value,
        source_id=SOURCE,
        ex_date="2020-09-02",
        cash_amount=Decimal("5"),
        currency="USD",
    )
    series = total_return(bars, [dividend])
    index = dict(series.total_return_index)
    assert index["2020-09-01"] == "1"
    assert index["2020-09-02"] == "1.15"  # (110 + 5) / 100
    assert index["2020-09-03"] == "1.15"  # 110 / 110
    assert series.adjustment_status == "total_return_adjusted"
    # The split-adjusted closes remain prices, not total-return values.
    assert series.bars[1].close == Decimal("110")


def test_total_return_combines_with_split(db, apple_security):
    bars = [_bar(apple_security, "2020-08-28", "400"), _bar(apple_security, "2020-08-31", "100"),
            _bar(apple_security, "2020-09-01", "101")]
    split = _split(apple_security, "2020-08-31", ratio_to=4)
    dividend = CorporateAction(
        security_id=apple_security,
        action_type=ActionType.CASH_DIVIDEND.value,
        source_id=SOURCE,
        ex_date="2020-09-01",
        cash_amount=Decimal("1"),
        currency="USD",
    )
    series = total_return(bars, [split, dividend])
    index = dict(series.total_return_index)
    # 2020-08-28 adjusted close = 100; 08-31 = 100 (no move); 09-01 = (101 + 1) / 100
    assert index["2020-08-31"] == "1"
    assert index["2020-09-01"] == "1.02"


def test_split_adjustment_of_benchmark_values_matches_manual_calculation(db, apple_security):
    """Reference calculation performed by hand, independent of the implementation."""
    raw_close = Decimal("499.23")
    factor = Decimal(4)
    assert raw_close / factor == Decimal("124.8075")
    bars = [_bar(apple_security, "2020-08-28", str(raw_close)), _bar(apple_security, "2020-08-31", "129.04")]
    series = split_adjust(bars, [_split(apple_security, "2020-08-31", ratio_to=4)])
    assert series.bars[0].close == Decimal("124.8075")
    # Continuity: the overnight move should be the economic move, not a 4x jump.
    move = (series.bars[1].close - series.bars[0].close) / series.bars[0].close
    raw_move = (Decimal("129.04") - raw_close) / raw_close
    assert abs(move) < Decimal("0.05")
    assert abs(raw_move) > Decimal("0.5")
