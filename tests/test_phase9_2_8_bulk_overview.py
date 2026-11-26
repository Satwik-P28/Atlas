"""Phase 9.2.8: the bulk market overview must equal the scalar canonical contract.

The performance change is only acceptable if it is a *change of execution plan*, not of
meaning. Every test here compares two documents produced from the same database by:

* ``market_overview(projection="scalar")`` — the per-security reference loop, which calls
  ``select_price``/``select_series``/``series_changes`` once per security; and
* ``market_overview(projection="bulk")`` — the set-based plan in
  :mod:`atlas.terminal.market_projection`.

Equality is exact on everything the contract exposes: security and venue identity, the
selected provider, session identity, revision, observation id and content hash, the
one-day and one-year changes with the dates they used, the sparkline order, source status,
missing-session counts, exclusions and limitations. Nothing is compared with a tolerance,
because both paths run the same arithmetic over the same observations; a float tolerance
would hide exactly the provenance drift this suite exists to catch.

The scenarios cover the twenty cases Phase 9.2.8 requires, plus generated combinations and
an explicit statement-count assertion so the plan cannot quietly become linear again.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from atlas.entities.master import SecurityMaster
from atlas.market import evidence
from atlas.market.actions import ActionStore, CorporateAction
from atlas.market.bars import BarStore
from atlas.market.calendar import TradingCalendar
from atlas.storage.db import Database
from atlas.storage.sources import ensure_default_sources
from atlas.terminal import market_projection, read_models

AS_OF = "2025-06-30"
DAY_ONE = "2025-06-02"
DAY_TWO = "2025-06-03"
DAY_THREE = "2025-06-04"


# ----------------------------------------------------------------------- helpers
class CountingDatabase(Database):
    """Counts executed statements exactly once (``query`` delegates to ``execute``)."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.statements = 0

    def reset(self) -> None:
        self.statements = 0

    def execute(self, sql, params=()):  # type: ignore[override]
        self.statements += 1
        return super().execute(sql, params)


def _source(
    db: Database,
    source_id: str,
    *,
    kind: str = "market_data",
    redistribution: str = "restricted",
    name: str | None = None,
) -> str:
    db.execute(
        "INSERT OR IGNORE INTO source (source_id, name, kind, homepage, licence, redistribution, notes, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (source_id, name or source_id, kind, None, "Synthetic test terms", redistribution, "test fixture", AS_OF + "T00:00:00Z"),
    )
    return source_id


def _security(db: Database, index: int, *, mic: str = "XNYS", ticker: str | None = None, klass: str = "common stock"):
    master = SecurityMaster(db)
    master.ensure_venue("XNYS", "New York Stock Exchange", country="US", timezone="America/New_York")
    master.ensure_venue("XNAS", "Nasdaq", country="US", timezone="America/New_York")
    issuer = master.register_issuer(legal_name=f"Projection Issuer {index:03d}", cik=f"{9000000 + index}")
    security = master.ensure_security(issuer, class_designation=klass, currency="USD")
    listing = master.ensure_listing(security, mic, valid_from="2000-01-01", is_primary=True)
    master.assign_ticker(
        listing,
        ticker if ticker is not None else f"P{index:03d}",
        valid_from="2000-01-01",
        confidence=1.0,
        status="confirmed",
        source_id="sec-edgar",
    )
    return master, security


def _bar(
    db: Database,
    security_id: str,
    session: str,
    close: float,
    *,
    source_id: str,
    mic: str = "XNYS",
    volume: float | None = 1000.0,
) -> None:
    bars = BarStore(db)
    bars.ingest(
        [
            evidence.MarketObservation(
                security_id=security_id,
                mic=mic,
                interval="1d",
                session=f"{session}T21:00:00Z",
                revision_seq=1,
                supersedes_seq=None,
                currency="USD",
                open=Decimal(str(close - 0.5)),
                high=Decimal(str(close + 0.5)),
                low=Decimal(str(close - 1.0)),
                close=Decimal(str(close)),
                volume=None if volume is None else Decimal(str(volume)),
                adjustment="raw",
                source_id=source_id,
                source_name=None,
                dataset=None,
                licence=None,
                redistribution=None,
                source_kind=None,
                observed_at=f"{session}T22:00:00Z",
                ingested_at=f"{session}T22:00:00Z",
            ).to_bar()
        ],
        observed_at=f"{session}T22:00:00Z",
    )


def _overview(db: Database, plan: str, as_of: str = AS_OF) -> dict:
    payload = read_models.market_overview(db, projection=plan, as_of=as_of)
    return {key: value for key, value in payload.items() if key != "as_of"}


def _assert_equivalent(db: Database, as_of: str = AS_OF) -> dict:
    scalar = _overview(db, "scalar", as_of)
    bulk = _overview(db, "bulk", as_of)
    assert bulk["count"] == scalar["count"]
    assert bulk["items"] == scalar["items"]
    assert bulk == scalar
    return scalar


def _business_days(start: str, end: str) -> list[str]:
    day, last, out = date.fromisoformat(start), date.fromisoformat(end), []
    while day <= last:
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def _history(db, security_id: str, pairs, *, source_id: str, mic: str = "XNYS") -> None:
    for session, close in pairs:
        _bar(db, security_id, session, close, source_id=source_id, mic=mic)


# ------------------------------------------------------------------ 1: baseline
def test_one_provider_without_corrections(db):
    _source(db, "vendor-a")
    _, security = _security(db, 1)
    _history(db, security, [(DAY_ONE, 10.0), (DAY_TWO, 11.0), (DAY_THREE, 12.0)], source_id="vendor-a")

    payload = _assert_equivalent(db)
    assert payload["count"] == 1
    item = payload["items"][0]
    assert item["last_close"] == 12.0
    assert item["sessions"] == 3
    assert item["series_policy"] == "single_provider_held_constant"


# ------------------------------------------------- 2: two disagreeing providers
def test_two_disagreeing_providers_choose_one_and_report_the_other(db):
    _source(db, "vendor-a")
    _source(db, "vendor-b")
    _, security = _security(db, 1)
    _history(db, security, [(DAY_ONE, 10.0), (DAY_TWO, 11.0)], source_id="vendor-a")
    _history(db, security, [(DAY_ONE, 99.0), (DAY_TWO, 98.0)], source_id="vendor-b")

    payload = _assert_equivalent(db)
    item = payload["items"][0]
    # The canonical ordering is session desc, revision desc, source id asc, so 'vendor-a'
    # wins and the series never mixes the two.
    assert item["last_close"] == 11.0
    assert item["sessions"] == 2
    assert any("excluded" in note for note in item["series_limitations"])


# ------------------------------------------------------- 3: revision chains
def test_provider_revision_chain_uses_the_newest_revision_only(db):
    _source(db, "vendor-a")
    _, security = _security(db, 1)
    _history(db, security, [(DAY_ONE, 10.0), (DAY_TWO, 11.0)], source_id="vendor-a")
    # A provider correction on the newest session becomes revision 2.
    _bar(db, security, DAY_TWO, 12.5, source_id="vendor-a")

    payload = _assert_equivalent(db)
    item = payload["items"][0]
    assert item["last_close"] == 12.5
    assert any("revision" in note for note in item["series_limitations"])


# ------------------------------------------------------------- 4: second venue
def test_second_venue_is_separate_and_never_mixed(db):
    _source(db, "vendor-a")
    master, security = _security(db, 1, mic="XNYS")
    second = master.ensure_listing(security, "XNAS", valid_from="2000-01-01")
    master.assign_ticker(second, "P001N", valid_from="2000-01-01", confidence=1.0, status="confirmed", source_id="sec-edgar")
    _history(db, security, [(DAY_ONE, 10.0), (DAY_TWO, 11.0)], source_id="vendor-a", mic="XNYS")
    _history(db, security, [(DAY_ONE, 50.0), (DAY_TWO, 55.0)], source_id="vendor-a", mic="XNAS")

    payload = _assert_equivalent(db)
    item = payload["items"][0]
    assert item["mic"] == "XNYS"
    assert item["last_close"] == 11.0


# ------------------------------------------- 5: incomplete historical coverage
def test_incomplete_history_reports_missing_sessions(db):
    _source(db, "vendor-a")
    _, security = _security(db, 1)
    TradingCalendar(db).build("XNYS", DAY_ONE, "2025-06-13")
    _history(db, security, [(DAY_ONE, 10.0), ("2025-06-05", 11.0)], source_id="vendor-a")

    payload = _assert_equivalent(db)
    item = payload["items"][0]
    assert item["sessions"] == 2
    # The overview reports the sessions it actually has and refuses a one-year change
    # whose comparison date predates the history; it never pads the series.
    assert item["change_1y"] is None
    assert item["change_1y_target"] == "2024-06-05"
    assert any("one provider" in note for note in item["series_limitations"])


# ------------------------------------------------------- 6: security classes
def test_distinct_security_classes_from_one_issuer(db):
    _source(db, "vendor-a")
    master, common = _security(db, 1, ticker="PC", klass="common stock")
    issuer = master.security(common)["issuer_id"]
    preferred = master.ensure_security(issuer, class_designation="class A", currency="USD")
    listing = master.ensure_listing(preferred, "XNYS", valid_from="2000-01-01")
    master.assign_ticker(listing, "PA", valid_from="2000-01-01", confidence=1.0, status="confirmed", source_id="sec-edgar")
    _history(db, common, [(DAY_ONE, 10.0)], source_id="vendor-a")
    _history(db, preferred, [(DAY_ONE, 20.0)], source_id="vendor-a")

    payload = _assert_equivalent(db)
    assert payload["count"] == 2
    assert [item["ticker"] for item in payload["items"]] == ["PA", "PC"]


# --------------------------------------------------------------- 7: a split
def test_split_action_changes_the_split_adjusted_change_identically(db):
    _source(db, "vendor-a")
    _, security = _security(db, 1)
    days = _business_days("2024-06-03", "2025-06-06")
    _history(db, security, [(day, 400.0 - index * 0.5) for index, day in enumerate(days)], source_id="vendor-a")
    ActionStore(db).add(
        CorporateAction(
            security_id=security,
            action_type="split",
            source_id="vendor-a",
            ex_date="2025-05-15",
            ratio_from=Decimal("1"),
            ratio_to=Decimal("4"),
        )
    )

    payload = _assert_equivalent(db)
    item = payload["items"][0]
    assert item["change_basis"] == "split_adjusted"
    assert item["change_1d"] is not None


# ------------------------------------------------------------ 8: a dividend
def test_dividend_action_is_used_by_both_plans(db):
    _source(db, "vendor-a")
    _, security = _security(db, 1)
    days = _business_days("2024-06-03", "2025-06-06")
    _history(db, security, [(day, 100.0 + index * 0.1) for index, day in enumerate(days)], source_id="vendor-a")
    ActionStore(db).add(
        CorporateAction(
            security_id=security,
            action_type="cash_dividend",
            source_id="vendor-a",
            ex_date="2025-05-01",
            cash_amount=Decimal("0.25"),
            currency="USD",
        )
    )

    _assert_equivalent(db)


# --------------------------------------------------------------- 9: a holiday
def test_calendar_holiday_is_counted_identically(db):
    _source(db, "vendor-a")
    _, security = _security(db, 1)
    TradingCalendar(db).build("XNYS", "2024-12-20", "2025-01-10")
    _history(
        db,
        security,
        [("2024-12-24", 10.0), ("2024-12-26", 11.0), ("2025-01-02", 12.0)],
        source_id="vendor-a",
    )

    payload = _assert_equivalent(db, as_of="2025-01-10")
    item = payload["items"][0]
    assert item["sessions"] == 3


# -------------------------------------------------- 10: no previous session
def test_single_session_has_no_one_day_change(db):
    _source(db, "vendor-a")
    _, security = _security(db, 1)
    _history(db, security, [(DAY_ONE, 10.0)], source_id="vendor-a")

    payload = _assert_equivalent(db)
    item = payload["items"][0]
    assert item["change_1d"] is None
    assert item["change_1d_dates"] is None


# ------------------------------------------------ 11: no one-year history
def test_short_history_has_no_one_year_change(db):
    _source(db, "vendor-a")
    _, security = _security(db, 1)
    _history(db, security, [(DAY_ONE, 10.0), (DAY_TWO, 11.0)], source_id="vendor-a")

    payload = _assert_equivalent(db)
    item = payload["items"][0]
    assert item["change_1y"] is None
    assert item["change_1y_dates"] is None
    assert item["change_1y_target"] == "2024-06-03"


# -------------------------------------------------- 12: historical cutoff
def test_historical_cutoff_excludes_later_sessions(db):
    _source(db, "vendor-a")
    _, security = _security(db, 1)
    _history(db, security, [(DAY_ONE, 10.0), (DAY_TWO, 11.0), ("2025-07-15", 99.0)], source_id="vendor-a")

    payload = _assert_equivalent(db)
    assert payload["items"][0]["last_close"] == 11.0
    assert payload["items"][0]["last_bar_date"] == DAY_TWO


# ------------------------------------------------- 13: restricted source rights
def test_restricted_vendor_rights_are_reported_identically(db):
    _source(db, "restricted-vendor", redistribution="restricted")
    _, security = _security(db, 1)
    _history(db, security, [(DAY_ONE, 10.0), (DAY_TWO, 11.0)], source_id="restricted-vendor")

    payload = _assert_equivalent(db)
    assert payload["items"][0]["data_status"] == "reported"
    sources = {row["source_id"]: row for row in payload["sources"]}
    assert sources["restricted-vendor"]["redistribution"] == "restricted"


# ------------------------------------------------------ 14: synthetic sources
def test_synthetic_source_is_labelled_synthetic(db):
    _source(db, "synthetic-feed", kind="synthetic")
    _, security = _security(db, 1)
    _history(db, security, [(DAY_ONE, 10.0), (DAY_TWO, 11.0)], source_id="synthetic-feed")

    payload = _assert_equivalent(db)
    assert payload["data_status"] == "synthetic"
    assert payload["items"][0]["data_status"] == "synthetic"


# --------------------------------------------- 15: missing corporate actions
def test_security_without_actions_matches(db):
    _source(db, "vendor-a")
    _, first = _security(db, 1)
    _, second = _security(db, 2)
    _history(db, first, [(DAY_ONE, 10.0), (DAY_TWO, 11.0)], source_id="vendor-a")
    _history(db, second, [(DAY_ONE, 20.0), (DAY_TWO, 19.0)], source_id="vendor-a")
    ActionStore(db).add(
        CorporateAction(
            security_id=first,
            action_type="split",
            source_id="vendor-a",
            ex_date="2025-01-15",
            ratio_from=Decimal("1"),
            ratio_to=Decimal("2"),
        )
    )

    payload = _assert_equivalent(db)
    assert payload["count"] == 2


# ----------------------------------------------------------- 16: large batch
def test_forty_securities_match_item_for_item(db):
    _source(db, "vendor-a")
    _source(db, "vendor-b")
    days = _business_days("2025-01-02", "2025-03-28")
    for index in range(40):
        _, security = _security(db, index)
        base = 20.0 + index
        _history(db, security, [(day, base + offset * 0.1) for offset, day in enumerate(days)], source_id="vendor-a")
        if index % 5 == 0:
            _history(db, security, [(day, base + offset * 0.1 + 1.0) for offset, day in enumerate(days)], source_id="vendor-b")

    payload = _assert_equivalent(db)
    assert payload["count"] == 40


# ------------------------------------------------------ 17: empty universe
def test_empty_universe_returns_the_same_envelope(db):
    scalar = _overview(db, "scalar")
    bulk = _overview(db, "bulk")
    assert bulk == scalar
    assert bulk["items"] == []
    assert bulk["count"] == 0


# --------------------------------------------------- 18: stable ordering
def test_ordering_is_ticker_ascending_with_unregistered_last(db):
    _source(db, "vendor-a")
    _, first = _security(db, 1, ticker="ZED")
    _security(db, 2, ticker="AAA")
    master, third = _security(db, 3, ticker="MID")
    # A security with no ticker at all must sort first in both plans.
    bare_issuer = master.register_issuer(legal_name="Unlisted Issuer", cik="9999999")
    bare = master.ensure_security(bare_issuer, class_designation="common stock", currency="USD")
    master.ensure_listing(bare, "XNYS", valid_from="2000-01-01", is_primary=True)
    for security_id in (first, third, bare):
        _history(db, security_id, [(DAY_ONE, 10.0), (DAY_TWO, 11.0)], source_id="vendor-a")

    payload = _assert_equivalent(db)
    tickers = [item["ticker"] for item in payload["items"]]
    assert tickers == sorted(tickers, key=lambda value: value or "")


# ------------------------------------------- 19: source-selection ties
def test_equal_providers_break_ties_by_source_id(db):
    _source(db, "aaa-vendor")
    _source(db, "zzz-vendor")
    _, security = _security(db, 1)
    for provider in ("aaa-vendor", "zzz-vendor"):
        _history(db, security, [(DAY_ONE, 10.0), (DAY_TWO, 11.0)], source_id=provider)

    payload = _assert_equivalent(db)
    series = evidence.select_series(db, security, mic="XNYS", start="2025-05-01", end=AS_OF)
    assert series.source_id == "aaa-vendor"
    assert payload["items"][0]["price_observation_id"] == series.points[-1].observation_id


# -------------------------------------- 20: exact observation identities
def test_observation_identity_matches_the_canonical_selection(db):
    _source(db, "vendor-a")
    _source(db, "vendor-b")
    _, security = _security(db, 1)
    _history(db, security, [(DAY_ONE, 10.0), (DAY_TWO, 11.0)], source_id="vendor-a")
    _history(db, security, [(DAY_ONE, 10.0), (DAY_TWO, 13.0)], source_id="vendor-b")
    _bar(db, security, DAY_TWO, 12.0, source_id="vendor-a")

    payload = _assert_equivalent(db)
    series = evidence.select_series(
        db, security, mic="XNYS", start="2025-05-01", end=AS_OF,
        anchor=evidence.latest_observation(db, security, mic="XNYS", as_of=AS_OF),
    )
    item = payload["items"][0]
    assert item["price_observation_id"] == series.points[-1].observation_id
    assert item["sparkline"] == [float(point.close) for point in series.points[-30:]]
    assert item["change_basis"] == "split_adjusted"


# ------------------------------------- exactness of the no-action shortcut
def test_action_free_split_adjusted_change_equals_the_raw_change(db):
    """With no corporate action the split factor is 1, so both bases must agree exactly.

    ``series_changes`` skips the adjustment pass in that case. This test pins the
    equivalence the shortcut depends on: identical floats, identical reported closes.
    """
    _source(db, "vendor-a")
    _, security = _security(db, 1)
    days = _business_days("2024-06-03", "2025-06-06")
    _history(db, security, [(day, 100.0 + index * 0.37) for index, day in enumerate(days)], source_id="vendor-a")
    series = evidence.select_series(db, security, mic="XNYS", start="2024-06-01", end=AS_OF)

    adjusted = evidence.series_changes(series, [], basis="split_adjusted")
    raw = evidence.series_changes(series, [], basis="price")
    assert adjusted.one_day == raw.one_day
    assert adjusted.one_year == raw.one_year
    assert adjusted.one_day_from["close"] == raw.one_day_from["close"]
    assert adjusted.one_year_from["close"] == raw.one_year_from["close"]
    # The bases stay distinguishable in their labels even when the numbers coincide.
    assert adjusted.label != raw.label


# --------------------------------------------- statement-count boundedness
def _counted(path) -> CountingDatabase:
    database = CountingDatabase(path)
    database.migrate()
    ensure_default_sources(database)
    return database


def test_statement_count_is_constant_not_linear(tmp_path):
    counts = {}
    for size in (3, 24):
        database = _counted(tmp_path / f"count-{size}.db")
        try:
            _source(database, "vendor-a")
            for index in range(size):
                _, security = _security(database, index)
                _history(
                    database,
                    security,
                    [(DAY_ONE, 10.0 + index), (DAY_TWO, 11.0 + index), (DAY_THREE, 12.0 + index)],
                    source_id="vendor-a",
                )
            database.reset()
            read_models.market_overview(database, projection="bulk", as_of=AS_OF)
            bulk_statements = database.statements
            database.reset()
            read_models.market_overview(database, projection="scalar", as_of=AS_OF)
            scalar_statements = database.statements
        finally:
            database.close()
        counts[size] = (bulk_statements, scalar_statements)

    # The bulk plan executes the same handful of statements for 3 and for 24 securities.
    assert counts[3][0] == counts[24][0] <= market_projection.PROJECTION_QUERIES
    # The path it replaces grows with the universe, which is the defect being removed.
    assert counts[24][1] > counts[3][1]
    # The scalar path executes about twelve statements per security.
    assert counts[24][1] >= 10 * 24


# ------------------------------------------------------ generated scenarios
@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    securities=st.integers(min_value=0, max_value=4),
    providers=st.lists(st.sampled_from(["vendor-a", "vendor-b", "vendor-c"]), min_size=1, max_size=3, unique=True),
    sessions=st.integers(min_value=0, max_value=5),
    revisions=st.integers(min_value=0, max_value=2),
    with_split=st.booleans(),
    with_dividend=st.booleans(),
    second_venue=st.booleans(),
    cutoff=st.sampled_from([AS_OF, DAY_TWO, "2024-12-31"]),
)
def test_generated_scenarios_are_equivalent(
    db, securities, providers, sessions, revisions, with_split, with_dividend, second_venue, cutoff
):
    for provider in providers:
        _source(db, provider, kind="market_data")
    TradingCalendar(db).build("XNYS", "2024-01-02", "2025-06-30")
    days = _business_days(DAY_ONE, "2025-06-13")[:sessions]
    for index in range(securities):
        master, security = _security(db, index)
        if second_venue:
            master.ensure_listing(security, "XNAS", valid_from="2000-01-01")
        for offset, provider in enumerate(providers):
            _history(
                db,
                security,
                [(day, 10.0 + index + offset + position) for position, day in enumerate(days)],
                source_id=provider,
            )
        if days and revisions:
            for step in range(revisions):
                _bar(db, security, days[-1], 20.0 + index + step, source_id=providers[0])
        if with_split:
            ActionStore(db).add(
                CorporateAction(
                    security_id=security,
                    action_type="split",
                    source_id=providers[0],
                    ex_date="2025-03-03",
                    ratio_from=Decimal("1"),
                    ratio_to=Decimal("2"),
                )
            )
        if with_dividend:
            ActionStore(db).add(
                CorporateAction(
                    security_id=security,
                    action_type="cash_dividend",
                    source_id=providers[0],
                    ex_date="2025-04-01",
                    cash_amount=Decimal("0.10"),
                    currency="USD",
                )
            )

    _assert_equivalent(db, as_of=cutoff)


# ---------------------------------------------------------- plan dispatch
def test_unknown_projection_plan_is_rejected(db):
    with pytest.raises(ValueError):
        read_models.market_overview(db, projection="magic")


def test_projection_version_is_declared():
    assert market_projection.PROJECTION_VERSION == "atlas.market_overview.bulk.v1"
    assert set(market_projection.PLANS) == {"bulk", "scalar"}
