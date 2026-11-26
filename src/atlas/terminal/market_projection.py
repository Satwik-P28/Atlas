"""Bulk market-overview projection.

Phase 9.2.7 measured the overview at 666 ms for 100 securities and 7,585 ms for 1,000,
executing roughly 24 statements per security (about 24,004 for the 1,000-security page).
Nothing in that cost was financial: the loop called the canonical per-security contract
eleven or so times, so every security paid for its own identity lookup, provider
selection, series query, calendar query, corporate-action query and source-status query.

This module is **not** a second pricing policy. It is a set-based execution plan for the
same contract, and its correctness definition is differential: for any database, the
overview it produces must equal, item for item, what the per-security scalar path in
:func:`atlas.terminal.read_models.market_overview_scalar` produces. Everything that
decides *which* observation represents a price still lives in
:mod:`atlas.market.evidence`:

* the winning anchor is chosen by ``select_price``'s ordering
  (session desc, revision desc, source asc, mic asc) over latest-revision rows;
* the series provider is the anchor's provider, held constant over the window;
* each session keeps the provider's newest revision, and no provider is ever spliced;
* returns are computed by the same :func:`atlas.market.evidence.series_changes` over the
  same :class:`MarketSeriesSelection`, so the arithmetic, basis and reported dates cannot
  drift;
* observation identity and content hashes come from the same ``MarketObservation``.

The statement count is bounded by a small constant (:data:`PROJECTION_QUERIES`),
independent of the number of securities, and the plan never omits a security or a
calculation to gain speed.

Query plan, in order:

1. universe: securities, issuer name, default venue and current ticker (one statement);
2. anchors: the winning observation per (security, venue) (one statement);
3. computable corporate actions plus correction chains (two statements);
4. excluded providers: the competing providers per (security, venue) (one statement);
5. trading calendar for the union window (one statement);
6. source kinds for the per-item ``data_status`` (one statement);
7. series points: sessions of the winning providers, streamed in security order (one
   statement);
8. source catalogue for the response's source list (one statement).

Two properties are deliberate and measured:

* **Index-friendly bounds.** ``substr(ts_utc, 1, 10) BETWEEN a AND b`` cannot use the
  ``(security_id, mic, interval, ts_utc)`` index because the column is wrapped in a
  function. Stored timestamps are canonical ``YYYY-MM-DDTHH:MM:SSZ`` text, so the same
  range is expressed as ``ts_utc BETWEEN a||T00:00:00Z AND b||T23:59:59Z``, which is
  index-usable and selects exactly the rows the canonical contract selects.
* **Streaming, not materialisation.** The points query is consumed cursor-row by
  cursor-row in ``security_id`` order and one security's item is built as soon as its rows
  end, so peak memory is one security's window rather than the whole universe's.
* **Revision resolution in Python.** ``_LATEST_REVISION_SQL`` is a correlated subquery;
  running it once per candidate row dominated the fetch. The same rule (keep the maximum
  ``revision_seq`` per security/venue/session/provider) is applied while streaming, which
  transfers only the rare revision rows and resolves them with the identical ordering.

The union window is ``[min(anchor date) - 400 days, today]``; a security whose own 400-day
window starts later is filtered to exactly the range ``select_series`` would have queried,
so a stale security cannot widen another's series.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any, Iterable, Mapping, Sequence

from ..core.temporal import iso, iso_date, parse_date, utcnow
from ..market.actions import COMPUTABLE_ACTION_TYPES, CorporateAction
from ..market.evidence import (
    MISSING_FILTERED,
    NO_CUTOFF,
    SERIES_POLICY_VERSION,
    MarketSeriesSelection,
    _row_observation,
    series_changes,
)
from ..storage.db import Database

#: Version of this execution plan. Changing it changes performance, never semantics.
PROJECTION_VERSION = "atlas.market_overview.bulk.v1"

#: The one-year comparison plus a buffer for sessions, matching the scalar read model.
OVERVIEW_WINDOW_DAYS = 400

#: Fixed number of statements this plan executes for any universe size. Optional steps are
#: skipped, never repeated per security.
PROJECTION_QUERIES = 9

PLAN_BULK = "bulk"
PLAN_SCALAR = "scalar"
PLANS = (PLAN_BULK, PLAN_SCALAR)

TERMINAL_SCHEMA = "atlas.terminal.v1"

#: The same label mapping ``read_models._source_status`` uses; kept here so the bulk plan
#: cannot drift from it without a test failing.
_SOURCE_STATUS = {
    "synthetic": "synthetic",
    "sec_edgar": "reported",
    "csv_import": "imported",
    "market_data": "reported",
}


def _status_for(kind: str | None) -> str:
    if kind is None:
        return "unknown"
    return _SOURCE_STATUS.get(kind, kind)


def _day_start(day: str) -> str:
    """First stored instant of a calendar day (canonical UTC text)."""
    return f"{day}T00:00:00Z"


def _day_end(day: str) -> str:
    """Last stored instant of a calendar day (canonical UTC text)."""
    return f"{day}T23:59:59Z"


def _universe(db: Database, today: str) -> list[Any]:
    """Every security with its issuer name, default venue and current ticker.

    ``_default_mic`` picks the first primary listing in ``(valid_from, mic)`` order and
    falls back to the earliest listing; the correlated subquery orders by
    ``is_primary DESC`` first, which selects the same row.
    """
    rows = db.query(
        "SELECT s.security_id, s.issuer_id, s.currency, i.legal_name, "
        "(SELECT l.mic FROM listing l WHERE l.security_id = s.security_id "
        " ORDER BY l.is_primary DESC, l.valid_from, l.mic LIMIT 1) AS mic, "
        "(SELECT ta.ticker FROM ticker_assignment ta "
        " JOIN listing l2 ON l2.listing_id = ta.listing_id "
        " WHERE l2.security_id = s.security_id AND ta.status != 'retracted' "
        " AND ta.valid_from <= ? AND (ta.valid_to IS NULL OR ta.valid_to >= ?) "
        " ORDER BY l2.is_primary DESC, ta.valid_from DESC, ta.ticker LIMIT 1) AS ticker "
        "FROM security s LEFT JOIN issuer i ON i.issuer_id = s.issuer_id "
        "ORDER BY s.security_id",
        (today, today),
    )
    return [row for row in rows if row["mic"] is not None]


#: The winning observation per (security, venue) at or before the cutoff.
#:
#: ``MAX(ts_utc)`` is answered from the bar index, so the correlated revision check only
#: touches the handful of rows stored for each security's latest session. The final choice
#: among those rows is made in Python with the exact ``select_price`` ordering, which
#: keeps one definition of "latest session" rather than a second one in SQL.
_ANCHOR_SQL = (
    "SELECT b.security_id, b.mic, b.ts_utc, b.revision_seq, b.source_id FROM bar b "
    "JOIN (SELECT security_id, mic, MAX(ts_utc) AS ts_utc FROM bar "
    "      WHERE interval = '1d' AND ts_utc <= ? "
    "      GROUP BY security_id, mic) newest "
    "  ON newest.security_id = b.security_id AND newest.mic = b.mic "
    " AND newest.ts_utc = b.ts_utc "
    "WHERE b.interval = '1d' AND b.revision_seq = ("
    "  SELECT MAX(b2.revision_seq) FROM bar b2 WHERE b2.security_id = b.security_id "
    "  AND b2.mic = b.mic AND b2.interval = b.interval AND b2.ts_utc = b.ts_utc "
    "  AND b2.source_id = b.source_id)"
)


def _anchors(db: Database, today: str, wanted: set[tuple[str, str]]) -> dict[tuple[str, str], Any]:
    """Resolve one anchor observation per requested (security, venue)."""
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for row in db.query(_ANCHOR_SQL, (_day_end(today),)):
        key = (row["security_id"], str(row["mic"]).upper())
        if key in wanted:
            grouped[key].append(row)
    anchors: dict[tuple[str, str], Any] = {}
    for key, rows in grouped.items():
        # select_price orders by ts_utc DESC, revision_seq DESC, source_id ASC, mic ASC.
        latest = max(rows, key=lambda row: (row["ts_utc"], row["revision_seq"]))
        tied = [
            row
            for row in rows
            if (row["ts_utc"], row["revision_seq"]) == (latest["ts_utc"], latest["revision_seq"])
        ]
        anchors[key] = min(tied, key=lambda row: (row["source_id"], str(row["mic"])))
    return anchors


_SERIES_COLUMNS = (
    "b.security_id, b.mic, b.interval, b.ts_utc, b.revision_seq, b.supersedes_bar, "
    "b.currency, b.open, b.high, b.low, b.close, b.volume, b.adjustment_status, "
    "b.source_id, b.observed_at, b.ingested_at, s.name, s.licence, s.redistribution, "
    "s.kind AS source_kind"
)


def _placeholders(values: Sequence[Any]) -> str:
    return ",".join("?" for _ in values)


def _iter_series_rows(
    db: Database,
    providers: Sequence[str],
    mics: Sequence[str],
    start: str,
    end: str,
) -> Iterable[Any]:
    """Stream the winning providers' observations over the union window.

    Rows arrive in ``(security_id, ts_utc, revision_seq)`` order. The caller keeps the
    highest revision per session, which is exactly what ``_LATEST_REVISION_SQL`` selects,
    without paying for a correlated subquery per row.
    """
    if not providers or not mics:
        return iter(())
    sql = (
        f"SELECT {_SERIES_COLUMNS} FROM bar b "
        "LEFT JOIN source s ON s.source_id = b.source_id "
        "WHERE b.interval = '1d' "
        f"AND b.mic IN ({_placeholders(mics)}) "
        f"AND b.source_id IN ({_placeholders(providers)}) "
        "AND b.ts_utc BETWEEN ? AND ? "
        "ORDER BY b.security_id, b.ts_utc, b.revision_seq"
    )
    params: list[Any] = [str(mic).upper() for mic in mics]
    params.extend(providers)
    params.extend([_day_start(start), _day_end(end)])
    return iter(db.execute(sql, params))


def _excluded_providers(
    db: Database, mics: Sequence[str], start: str, end: str
) -> dict[tuple[str, str], set[str]]:
    """Every provider with observations in the window, per (security, venue).

    ``select_series`` reports the competing providers it declined to splice; the bulk plan
    must report exactly the same set, so this is a separate cheap projection rather than
    a filter on the selected points.
    """
    if not mics:
        return {}
    rows = db.query(
        "SELECT security_id, mic, source_id FROM bar "
        "WHERE interval = '1d' "
        f"AND mic IN ({_placeholders(mics)}) "
        "AND ts_utc BETWEEN ? AND ? "
        "GROUP BY security_id, mic, source_id",
        [str(mic).upper() for mic in mics] + [_day_start(start), _day_end(end)],
    )
    seen: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        seen[(row["security_id"], str(row["mic"]).upper())].add(row["source_id"])
    return seen


def _calendar_index(
    db: Database, mics: Sequence[str], start: str, end: str
) -> dict[str, list[str]] | None:
    """Stored sessions per venue over the union window.

    ``None`` means the calendar is unavailable; ``select_series`` treats a missing calendar
    as absent metadata (``missing_sessions`` stays ``None``) rather than as a failure.
    """
    if not mics:
        return {}
    try:
        rows = db.query(
            "SELECT mic, session_date FROM trading_session "
            f"WHERE mic IN ({_placeholders(mics)}) AND session_date BETWEEN ? AND ? "
            "ORDER BY mic, session_date",
            [str(mic).upper() for mic in mics] + [start, end],
        )
    except Exception:  # a calendar is optional metadata, never a reason to fail a series
        return None
    index: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        index[str(row["mic"]).upper()].append(row["session_date"])
    return dict(index)


def _actions_by_security(db: Database) -> dict[str, list[CorporateAction]]:
    """Computable corporate actions, with correction chains resolved once."""
    types = sorted(COMPUTABLE_ACTION_TYPES)
    rows = db.query(
        "SELECT * FROM corporate_action "
        f"WHERE action_type IN ({_placeholders(types)}) "
        "ORDER BY security_id, COALESCE(ex_date, effective_date, '9999-12-31'), action_id",
        types,
    )
    superseded = {
        row["supersedes"]
        for row in db.query(
            "SELECT supersedes FROM corporate_action WHERE supersedes IS NOT NULL"
        )
    }
    grouped: dict[str, list[CorporateAction]] = defaultdict(list)
    for row in rows:
        if row["action_id"] in superseded:
            continue
        grouped[row["security_id"]].append(CorporateAction.from_row(row))
    return dict(grouped)


def _series_for(
    *,
    security_id: str,
    mic: str,
    provider: str,
    start_text: str,
    end_text: str,
    observations: Iterable[Any],
    excluded: Sequence[str],
    calendar: Mapping[str, Sequence[str]] | None,
) -> MarketSeriesSelection:
    """Assemble the canonical series record from already-selected rows."""
    points = tuple(observations)
    missing: int | None = None
    requested: int | None = None
    if calendar is not None:
        sessions = [day for day in calendar.get(mic, []) if start_text <= day <= end_text]
        if sessions:
            requested = len(sessions)
            observed = {point.session_date for point in points}
            missing = len([day for day in sessions if day not in observed])

    revisions = sum(1 for point in points if point.revision_seq > 1)
    limitations: list[str] = [
        f"one provider ({provider}) is held constant across the window; "
        "competing providers are stored but never spliced into this series",
        "the series is a raw provider statement: vendor historical availability is not proven, "
        "so a price dated before the cutoff may have been revised afterwards",
    ]
    if revisions:
        limitations.append(
            f"{revisions} session(s) use a provider revision; earlier revisions remain stored "
            "and are replayable by pin"
        )
    if excluded:
        limitations.append(
            f"{len(excluded)} other provider(s) hold observations in this window and are excluded: "
            + ", ".join(excluded)
        )
    coverage = {
        "sessions": len(points),
        "first_session": points[0].session_date if points else None,
        "last_session": points[-1].session_date if points else None,
        "requested_sessions": requested,
        "missing_sessions": missing,
        "providers": [provider],
        "excluded_providers": list(excluded),
        "revisions": revisions,
    }
    return MarketSeriesSelection(
        policy_version=SERIES_POLICY_VERSION,
        security_id=security_id,
        mic=mic,
        interval="1d",
        start=start_text,
        end=end_text,
        information_cutoff=None if end_text >= NO_CUTOFF else end_text,
        policy="single_provider_held_constant",
        points=points,
        requested_source_id=None,
        excluded_providers=tuple(excluded),
        coverage=coverage,
        missing_sessions=missing,
        limitations=tuple(limitations),
        missing_status=None if points else MISSING_FILTERED,
    )


def _sources(db: Database) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT source_id, name, kind, licence, redistribution FROM source ORDER BY source_id"
    )
    return [{key: row[key] for key in row.keys()} for row in rows]


def _item_for(
    *,
    security: Mapping[str, Any],
    window: tuple[str, str],
    provider: str,
    rows: Sequence[Any],
    excluded_index: Mapping[tuple[str, str], set[str]],
    calendar: Mapping[str, Sequence[str]] | None,
    actions: Sequence[CorporateAction],
    status_by_source: Mapping[str, str],
) -> dict[str, Any] | None:
    """Build one overview item from the streamed rows of a single security."""
    security_id = security["security_id"]
    mic = str(security["mic"]).upper()
    start_text, end_text = window

    # The same selection the per-security series query performs: one venue, one provider,
    # latest revision per session, inside this security's own window.
    chosen: dict[str, Any] = {}
    for row in rows:
        if str(row["mic"]).upper() != mic or row["source_id"] != provider:
            continue
        session = str(row["ts_utc"])[:10]
        if session < start_text or session > end_text:
            continue
        current = chosen.get(session)
        if current is None or row["revision_seq"] > current["revision_seq"]:
            chosen[session] = row
    if not chosen:
        return None
    points = tuple(_row_observation(chosen[session]) for session in sorted(chosen))

    excluded = tuple(
        sorted(
            source_id
            for source_id in excluded_index.get((security_id, mic), set())
            if source_id != provider
        )
    )
    series = _series_for(
        security_id=security_id,
        mic=mic,
        provider=provider,
        start_text=start_text,
        end_text=end_text,
        observations=points,
        excluded=excluded,
        calendar=calendar,
    )
    change = series_changes(series, actions)
    latest = series.points[-1]
    return {
        "security_id": security_id,
        "issuer_id": security["issuer_id"],
        "legal_name": security["legal_name"],
        "ticker": security["ticker"],
        "mic": mic,
        "last_close": float(latest.close),
        "last_bar_date": latest.session_date,
        "change_1d": change.one_day,
        "change_1y": change.one_year,
        "change_basis": change.basis,
        "change_1d_dates": (
            [change.one_day_from["session_date"], change.one_day_to["session_date"]]
            if change.one_day_from and change.one_day_to else None
        ),
        "change_1y_dates": (
            [change.one_year_from["session_date"], change.one_year_to["session_date"]]
            if change.one_year_from and change.one_year_to else None
        ),
        "change_1y_target": change.one_year_target,
        "change_1y_span_days": change.one_year_span_days,
        "volume": float(latest.volume) if latest.volume is not None else None,
        "sparkline": [float(point.close) for point in series.points[-30:]],
        "sessions": series.sessions,
        "data_status": status_by_source.get(latest.source_id, "unknown"),
        "currency": security["currency"],
        "price_observation_id": latest.observation_id,
        "series_policy": series.policy,
        "series_limitations": list(series.limitations),
        "issuer_metrics": None,
    }


def _bulk_overview(db: Database, as_of: str | None) -> dict[str, Any]:
    today = str(as_of or iso_date(utcnow()))[:10]
    universe = _universe(db, today)
    requested = {(row["security_id"], str(row["mic"]).upper()) for row in universe}
    anchors = _anchors(db, today, requested) if requested else {}

    windows: dict[str, tuple[str, str]] = {}
    providers_by_security: dict[str, str] = {}
    for row in universe:
        security_id = row["security_id"]
        anchor = anchors.get((security_id, str(row["mic"]).upper()))
        if anchor is None:
            continue
        anchor_date = str(anchor["ts_utc"])[:10]
        windows[security_id] = (
            (parse_date(anchor_date) - timedelta(days=OVERVIEW_WINDOW_DAYS)).isoformat(),
            today,
        )
        providers_by_security[security_id] = anchor["source_id"]

    providers = sorted(set(providers_by_security.values()))
    mics = sorted({str(row["mic"]).upper() for row in universe if row["security_id"] in windows})
    union_start = min((window[0] for window in windows.values()), default=today)

    # Every helper query runs before the streaming points query starts, so the open cursor
    # is the only statement in flight while rows are consumed.
    excluded_index = _excluded_providers(db, mics, union_start, today) if windows else {}
    calendar = _calendar_index(db, mics, union_start, today) if windows else {}
    actions = _actions_by_security(db) if windows else {}
    status_by_source = (
        {
            row["source_id"]: _status_for(row["kind"])
            for row in db.query("SELECT source_id, kind FROM source")
        } if windows else {}
    )

    by_id = {row["security_id"]: row for row in universe}
    items: list[dict[str, Any]] = []

    def flush(security_id: str, rows: Sequence[Any]) -> None:
        security = by_id.get(security_id)
        provider = providers_by_security.get(security_id)
        if security is None or provider is None:
            return
        item = _item_for(
            security=security,
            window=windows[security_id],
            provider=provider,
            rows=rows,
            excluded_index=excluded_index,
            calendar=calendar,
            actions=actions.get(security_id, []),
            status_by_source=status_by_source,
        )
        if item is not None:
            items.append(item)

    if windows:
        current: str | None = None
        bucket: list[Any] = []
        for row in _iter_series_rows(db, providers, mics, union_start, today):
            security_id = row["security_id"]
            if security_id != current:
                if current is not None:
                    flush(current, bucket)
                current, bucket = security_id, []
            bucket.append(row)
        if current is not None:
            flush(current, bucket)

    items.sort(key=lambda item: item["ticker"] or "")
    sources = _sources(db)
    return {
        "items": items,
        "count": len(items),
        "as_of": iso(utcnow()),
        "data_status": "synthetic" if any(item["data_status"] == "synthetic" for item in items) else "reported",
        "sources": sources,
        "schema": TERMINAL_SCHEMA,
        "notes": [
            "Prices are end-of-day observations. Freshness is the last stored session, not a live quote."
        ],
    }


def overview(db: Database, *, plan: str = PLAN_BULK, as_of: str | None = None) -> dict[str, Any]:
    """The market overview under a chosen execution plan.

    ``plan="scalar"`` runs the per-security reference path; ``plan="bulk"`` runs this
    module's set-based plan. Both must return the same document, which
    ``tests/test_phase9_2_8_bulk_overview.py`` asserts differentially.
    """
    if plan == PLAN_SCALAR:
        from . import read_models

        return read_models.market_overview_scalar(db, as_of=as_of)
    if plan != PLAN_BULK:
        raise ValueError(f"unknown market-overview projection plan {plan!r}; supported are {list(PLANS)}")
    return _bulk_overview(db, as_of)


__all__ = [
    "PLANS",
    "PLAN_BULK",
    "PLAN_SCALAR",
    "PROJECTION_VERSION",
    "PROJECTION_QUERIES",
    "OVERVIEW_WINDOW_DAYS",
    "overview",
]
