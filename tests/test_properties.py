"""Property-based tests for invariants that must hold for every input."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from atlas.core.temporal import iso, parse_iso
from atlas.core.units import canonical_decimal, parse_decimal
from atlas.market.actions import ActionType, CorporateAction
from atlas.market.adjust import split_adjust, split_factor_for
from atlas.market.bars import Bar


@settings(max_examples=80)
@given(
    st.decimals(
        min_value=Decimal("-1e15"),
        max_value=Decimal("1e15"),
        allow_nan=False,
        allow_infinity=False,
        places=8,
    )
)
def test_decimal_survives_canonical_storage(value):
    text = canonical_decimal(value)
    assert parse_decimal(text) == value
    # Storing twice must be stable (idempotent ingestion depends on this).
    assert canonical_decimal(text) == text


@settings(max_examples=40)
@given(st.datetimes(min_value=datetime(1990, 1, 1), max_value=datetime(2035, 1, 1), timezones=st.just(timezone.utc)))
def test_timestamps_survive_canonical_storage(moment):
    text = iso(moment)
    assert text.endswith("Z")
    assert parse_iso(text).replace(microsecond=0) == moment.replace(microsecond=0)
    assert iso(parse_iso(text)) == text


def _bar(price: Decimal, session: str = "2020-01-02") -> Bar:
    return Bar(
        security_id="SEC-property",
        mic="XNAS",
        ts_utc=f"{session}T20:00:00Z",
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("1000"),
        currency="USD",
        source_id="atlas-synthetic",
    )


@settings(max_examples=50)
@given(
    st.decimals(min_value=Decimal("0.01"), max_value=Decimal("10000"), places=4),
    st.integers(min_value=1, max_value=20),
    st.integers(min_value=1, max_value=20),
)
def test_split_factor_converts_pre_and_post_split_prices(price, ratio_to, ratio_from):
    assume(ratio_to != ratio_from)
    action_type = ActionType.SPLIT.value if ratio_to > ratio_from else ActionType.REVERSE_SPLIT.value
    action = CorporateAction(
        security_id="SEC-property",
        action_type=action_type,
        source_id="atlas-synthetic",
        ex_date="2020-01-03",
        ratio_from=Decimal(ratio_from),
        ratio_to=Decimal(ratio_to),
    )
    bars = [_bar(price, "2020-01-02"), _bar(price, "2020-01-03")]
    series = split_adjust(bars, [action])
    # Pre-split prices are normalised; the ex-date bar is untouched. Decimal division is
    # not always exact, so compare within a tolerance far tighter than a cent.
    assert series.bars[0].close == bars[0].close / series.bars[0].split_factor
    assert abs(series.bars[0].close * series.bars[0].split_factor - bars[0].close) <= bars[0].close * Decimal("1e-20")
    assert series.bars[1].close == bars[1].close
    assert series.bars[1].split_factor == Decimal(1)
    expected = Decimal(ratio_to) / Decimal(ratio_from)
    assert split_factor_for("2020-01-02", [action]) == expected


@settings(max_examples=30)
@given(st.lists(st.dates(min_value=date(2020, 1, 1), max_value=date(2020, 12, 31)), min_size=2, max_size=6, unique=True))
def test_adjustment_of_multiple_splits_is_monotone_in_factor(sessions):
    sessions = sorted(sessions)
    bars = [_bar(Decimal("100"), session.isoformat()) for session in sessions]
    actions = [
        CorporateAction(
            security_id="SEC-property",
            action_type=ActionType.SPLIT.value,
            source_id="atlas-synthetic",
            ex_date=sessions[-1].isoformat(),
            ratio_from=Decimal(1),
            ratio_to=Decimal(2),
        )
    ]
    series = split_adjust(bars, actions)
    factors = [bar.split_factor for bar in series.bars]
    # Factor is non-increasing over time: splits only renormalise the past.
    assert factors == sorted(factors, reverse=True)
    assert factors[-1] == Decimal(1)
