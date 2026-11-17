"""Price Movement Intelligence: the deterministic engine behind "Explain This Move".

The feature answers a narrow question with evidence rather than narrative:

    Given a security and a selected interval of trading sessions, what did the price
    actually do, what contemporaneous evidence did Atlas hold, and which explanations
    remain unproven?

Design rules this module enforces:

* **One series, one provider.** The interval is built with
  :func:`atlas.market.evidence.select_series`, so a return is never computed across a
  provider switch. Every boundary session, price and revision is reported by id.
* **Three bases are reconciled, never conflated.** Raw, split-adjusted and total-return
  changes are each computed and labelled. The requested basis selects the statistics;
  the other two are reported so a reader can see how much of a move is mechanical.
* **Facts and hypotheses are different objects.** ``observations`` contains only what the
  data shows. ``hypotheses`` carries ``epistemic_status``, ``causal_status`` and a
  documented relevance tier. No hypothesis carries a probability, because Atlas has not
  identified a causal design for it.
* **Time is explicit.** In ``historical_reconstruction`` mode every event must have been
  publicly available at or before the information cutoff. In
  ``retrospective_investigation`` mode later amendments and analyses are shown but are
  labelled as subsequent evidence and never used to explain the move.
* **Absence is a result.** When Atlas holds no company-specific evidence, the response
  says so. It does not manufacture a headline, and it does not treat a residual as a
  cause.
* **Reproducible.** The response carries a SHA-256 over the normalised request, the
  selected observation ids, the corporate-action ids and the filing ids it used.

Only daily (``1d``) observations are supported. Atlas stores no intraday bars; a request
for another timeframe is refused rather than silently served a daily series.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..core.errors import UnknownEntity, ValidationError
from ..core.temporal import iso_date, parse_date
from ..entities.master import SecurityMaster
from ..market import evidence
from ..market.actions import ActionStore, SPLIT_TYPES, CorporateAction
from ..market.adjust import split_adjust, total_return
from ..market.bars import Bar
from ..market.calendar import TradingCalendar
from ..storage.db import Database

ENGINE_NAME = "atlas.price_explanation.engine"
ENGINE_VERSION = "1.0.0"
CONTRACT_VERSION = "atlas.price_explanation.v1"

MODE_HISTORICAL = "historical_reconstruction"
MODE_RETROSPECTIVE = "retrospective_investigation"
MODES = (MODE_HISTORICAL, MODE_RETROSPECTIVE)

SUPPORTED_TIMEFRAMES = ("1d",)
DEFAULT_TIMEZONE = "America/New_York"
MAX_HORIZON_SESSIONS = 10_000
DEFAULT_ESTIMATION_SESSIONS = 120
MIN_MARKET_MODEL_SESSIONS = 30
MAX_PEERS = 10

#: Right classes whose bytes may be exported in a portable artefact. Mirrors
#: ``atlas.market.evidence.REDISTRIBUTABLE``.
REDISTRIBUTABLE = evidence.REDISTRIBUTABLE

# ------------------------------------------------------------------ warning codes
W_RANGE_REVERSED = "range_reversed"
W_RANGE_SNAPPED = "range_snapped_to_nearest_session"
W_SINGLE_SESSION = "single_session_interval"
W_MISSING_SESSIONS = "missing_sessions_in_window"
W_NO_NEWS_ARCHIVE = "news_archive_unavailable"
W_NO_ANALYST_DATA = "analyst_consensus_unavailable"
W_NO_BENCHMARK = "benchmark_not_requested"
W_BENCHMARK_UNALIGNED = "benchmark_sessions_unaligned"
W_BENCHMARK_CURRENCY = "benchmark_currency_mismatch"
W_ESTIMATION_SHORT = "estimation_window_too_short"
W_SUBSEQUENT_EVIDENCE = "subsequent_evidence_excluded"
W_UNKNOWN_AVAILABILITY = "evidence_availability_unknown"
W_RESTRICTED_EXPORT = "restricted_source_not_exportable"
W_PARAMETRIC_HINDSIGHT = "parametric_hindsight_disclosed"
W_PROVIDER_VINTAGE = "provider_vintage_not_proven"
W_NO_COMPANY_EVIDENCE = "no_company_specific_evidence"
W_REVISION_FOUND = "subsequent_revision_found"
W_PEER_LIMIT = "peer_limit_applied"

REFUSAL_TIMEFRAME = "unsupported_timeframe"
REFUSAL_CUTOFF = "information_cutoff_precedes_range"
REFUSAL_MODE = "historical_mode_requires_cutoff"
REFUSAL_EMPTY = "no_observations_in_range"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _warning(code: str, message: str, **context: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if context:
        payload["context"] = context
    return payload


@dataclass(frozen=True, slots=True)
class ExplanationRequest:
    """The typed input of a price-movement investigation.

    ``start_session``/``end_session`` are trading-session dates (``YYYY-MM-DD``). They
    are resolved to stored sessions inside the engine, and the resolution is reported.
    """

    security_id: str
    start_session: str
    end_session: str
    timeframe: str = "1d"
    timezone: str = DEFAULT_TIMEZONE
    price_basis: str = "split_adjusted"
    mode: str = MODE_RETROSPECTIVE
    information_cutoff: str | None = None
    benchmark_security_id: str | None = None
    peer_security_ids: tuple[str, ...] = ()
    estimation_sessions: int = DEFAULT_ESTIMATION_SESSIONS
    evidence_limit: int = 50


@dataclass(slots=True)
class _Resolved:
    security: dict[str, Any]
    mic: str
    issuer: dict[str, Any]
    series: evidence.MarketSeriesSelection
    points: list[evidence.MarketObservation]
    actions: list[CorporateAction]
    requested_start: str
    requested_end: str
    start_session: str
    end_session: str
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _primary_mic(db: Database, master: SecurityMaster, security_id: str) -> str:
    rows = master.listings(security_id)
    if not rows:
        raise ValidationError(
            "security has no listing; market data cannot be resolved", security_id=security_id
        )
    primary = [row for row in rows if row["is_primary"]]
    chosen = (primary or rows)[0]
    return str(chosen["mic"]).upper()


def _ticker(db: Database, security_id: str, as_of: str | None = None) -> str | None:
    """The ticker in force at ``as_of``, through the security master's own resolution."""
    current = SecurityMaster(db).current_ticker(security_id, as_of=as_of)
    return current.get("ticker") if current else None


def _validate(request: ExplanationRequest) -> tuple[str, str, str | None]:
    if request.timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValidationError(
            "Atlas stores daily observations only; this timeframe is not supported",
            code=REFUSAL_TIMEFRAME,
            requested=request.timeframe,
            supported=list(SUPPORTED_TIMEFRAMES),
        )
    if request.mode not in MODES:
        raise ValidationError(
            "unknown investigation mode", requested=request.mode, supported=list(MODES)
        )
    if request.price_basis not in evidence.RETURN_BASES:
        raise ValidationError(
            "unknown return basis",
            requested=request.price_basis,
            supported=list(evidence.RETURN_BASES),
        )
    try:
        ZoneInfo(request.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError("unknown timezone", timezone=request.timezone) from exc
    if request.estimation_sessions < MIN_MARKET_MODEL_SESSIONS:
        raise ValidationError(
            "the market-model estimation window must contain at least "
            f"{MIN_MARKET_MODEL_SESSIONS} sessions",
            estimation_sessions=request.estimation_sessions,
        )
    if request.estimation_sessions > MAX_HORIZON_SESSIONS:
        raise ValidationError(
            "estimation window is unreasonably large",
            estimation_sessions=request.estimation_sessions,
        )
    if request.evidence_limit < 1 or request.evidence_limit > 200:
        raise ValidationError("evidence_limit must be within [1, 200]", evidence_limit=request.evidence_limit)
    start = iso_date(parse_date(request.start_session))
    end = iso_date(parse_date(request.end_session))
    if request.mode == MODE_HISTORICAL and not request.information_cutoff:
        raise ValidationError(
            "historical reconstruction requires an explicit information cutoff; "
            "otherwise it would be a retrospective investigation wearing a different label",
            code=REFUSAL_MODE,
        )
    cutoff = iso_date(parse_date(request.information_cutoff)) if request.information_cutoff else None
    return start, end, cutoff


def _resolve(db: Database, request: ExplanationRequest) -> _Resolved:
    """Pin the requested interval to actual stored sessions of one provider."""
    start, end, cutoff = _validate(request)
    warnings: list[dict[str, Any]] = []
    if start > end:
        start, end = end, start
        warnings.append(
            _warning(
                W_RANGE_REVERSED,
                "the requested interval was reversed; Atlas normalised it to an ascending range",
                requested_start=request.start_session,
                requested_end=request.end_session,
            )
        )
    if cutoff is not None and cutoff < end:
        raise ValidationError(
            "the information cutoff precedes the interval end; a historical reconstruction "
            "cannot know the closing price of a session that had not finished by its cutoff",
            code=REFUSAL_CUTOFF,
            information_cutoff=cutoff,
            end_session=end,
        )

    master = SecurityMaster(db)
    security = master.security(request.security_id)
    if security is None:
        raise UnknownEntity("unknown security", security_id=request.security_id)
    issuer = master.issuer(security["issuer_id"]) or {}
    mic = _primary_mic(db, master, request.security_id)

    # The series selection fixes the provider at the request's end date. One provider is
    # then held constant, and competing providers stay stored rather than spliced in.
    series = evidence.select_series(db, request.security_id, mic=mic, start=start, end=end)
    points = list(series.points)
    if not points:
        raise ValidationError(
            "no stored observation exists inside the requested interval",
            code=REFUSAL_EMPTY,
            missing_status=series.missing_status,
            security_id=request.security_id,
            mic=mic,
            requested=[start, end],
            series_limitations=list(series.limitations),
        )

    start_session = points[0].session_date
    end_session = points[-1].session_date
    resolved_start, resolved_end = start_session, end_session
    if resolved_start != start or resolved_end != end:
        calendar = TradingCalendar(db)
        try:
            calendar.ensure_range(mic, start, end)
            requested_non_session = [
                day
                for day in (start, end)
                if not calendar.is_session(mic, day)
            ]
        except Exception:  # a calendar is optional metadata, never a reason to fail
            requested_non_session = []
        warnings.append(
            _warning(
                W_RANGE_SNAPPED,
                "the requested boundary dates were aligned to the nearest stored sessions",
                requested=[start, end],
                resolved=[start_session, end_session],
                requested_non_session_dates=requested_non_session,
            )
        )
    if series.missing_sessions:
        warnings.append(
            _warning(
                W_MISSING_SESSIONS,
                "the venue calendar traded on sessions the selected provider does not cover; "
                "they are reported, never interpolated",
                missing_sessions=series.missing_sessions,
            )
        )
    if len(points) == 1:
        warnings.append(
            _warning(
                W_SINGLE_SESSION,
                "the interval contains one stored session; a return needs two observations "
                "and is therefore reported as zero with this limitation, not inferred",
                session=start_session,
            )
        )
    warnings.append(
        _warning(
            W_PROVIDER_VINTAGE,
            "the series is the provider's current statement about these sessions; Atlas "
            "preserves its own revisions but cannot prove which vendor revision was "
            "available on a past date",
            source_id=series.source_id,
        )
    )

    actions = ActionStore(db).list(
        request.security_id, knowledge_as_of=cutoff if request.mode == MODE_HISTORICAL else None
    )
    return _Resolved(
        security=security,
        mic=mic,
        issuer=issuer,
        series=series,
        points=points,
        actions=actions,
        requested_start=start,
        requested_end=end,
        start_session=resolved_start,
        end_session=resolved_end,
        warnings=warnings,
    )


# --------------------------------------------------------------------- statistics
def _basis_closes(
    bars: Sequence[Bar], actions: Sequence[CorporateAction], basis: str
) -> list[Decimal]:
    if not bars:
        return []
    if basis == "price":
        return [bar.close for bar in bars]
    if basis == "split_adjusted":
        return [bar.close for bar in split_adjust(bars, actions, include_dividends=False).bars]
    index = total_return(bars, actions).total_return_index
    return [Decimal(value) for _, value in index]


def _compound(closes: Sequence[Decimal]) -> float:
    if len(closes) < 2:
        return 0.0
    first, last = closes[0], closes[-1]
    if first == 0:
        return 0.0
    return float(last / first - 1)


def _daily_returns(closes: Sequence[Decimal]) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for previous, current in zip(closes, closes[1:]):
        if previous == 0:
            continue
        out.append(("", float(current / previous - 1)))
    return out


def _stdev(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _max_drawdown(closes: Sequence[Decimal]) -> float:
    peak: Decimal | None = None
    worst = 0.0
    for close in closes:
        if peak is None or close > peak:
            peak = close
        if peak and peak != 0:
            worst = min(worst, float(close / peak - 1))
    return worst


def _ols(y: Sequence[float], x: Sequence[float]) -> dict[str, Any] | None:
    n = len(y)
    if n < 2 or n != len(x):
        return None
    mean_y, mean_x = sum(y) / n, sum(x) / n
    var_x = sum((value - mean_x) ** 2 for value in x)
    # A benchmark whose returns are effectively constant has no identifiable slope. The
    # relative threshold matters: floating-point noise around a constant return leaves a
    # variance near 1e-38, and dividing by it produced a confident-looking nonsense beta.
    if var_x <= 1e-24 * max(1.0, mean_x * mean_x):
        return None
    cov = sum((a - mean_y) * (b - mean_x) for a, b in zip(y, x))
    beta = cov / var_x
    alpha = mean_y - beta * mean_x
    total = sum((value - mean_y) ** 2 for value in y)
    residual = sum((a - (alpha + beta * b)) ** 2 for a, b in zip(y, x))
    r_squared = None if total == 0 else max(0.0, min(1.0, 1 - residual / total))
    return {
        "alpha_daily": alpha,
        "beta": beta,
        "r_squared": r_squared,
        "observations": n,
    }


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# ----------------------------------------------------------------------- evidence
#: Forms that can carry a material company-specific disclosure. Routine administrative
#: filings (Form 4 ownership reports, Form 144 notices, annual-meeting receipts) are shown
#: in the timeline but are never ranked as an explanation of a price move.
MATERIAL_FORMS = frozenset(
    {
        "8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A", "20-F", "20-F/A",
        "40-F", "6-K", "S-1", "S-1/A", "S-3", "S-4", "DEF 14A", "DEFM14A",
        "SC 13D", "SC 13D/A", "SC TO-T", "SC TO-I", "NT 10-K", "NT 10-Q",
    }
)

_FORM_LABELS = {
    "8-K": "Current report",
    "10-Q": "Quarterly report",
    "10-K": "Annual report",
    "10-K/A": "Amended annual report",
    "10-Q/A": "Amended quarterly report",
    "8-K/A": "Amended current report",
    "S-1": "Registration statement",
    "DEF 14A": "Proxy statement",
}


def _filing_events(
    db: Database,
    *,
    issuer_id: str,
    start: str,
    end: str,
    mode: str,
    cutoff: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Filings inside the interval, with availability and relation to the window."""
    rows = db.query(
        "SELECT * FROM filing WHERE issuer_id=? ORDER BY filed_date, accession_number",
        (issuer_id,),
    )
    in_window: list[dict[str, Any]] = []
    after_window: list[dict[str, Any]] = []
    subsequent: list[dict[str, Any]] = []
    excluded_after_cutoff = 0
    before_window = 0
    in_window_accessions: set[str] = set()

    def _item(row: Any, availability: str, precision: str) -> dict[str, Any]:
        return {
            "event_id": f"FIL-{row['filing_id']}",
            "kind": "sec_filing",
            "form_type": row["form_type"],
            "form_label": _FORM_LABELS.get(row["form_type"], row["form_type"]),
            "title": f"{row['form_type']} filed",
            "date": row["filed_date"],
            "availability_time": availability,
            "availability_precision": precision,
            "period_of_report": row["period_of_report"],
            "accession_number": row["accession_number"],
            "is_amendment": bool(row["is_amendment"]),
            "amends_accession": row["amends_accession"],
            "source_id": row["source_id"],
            "source_url": None,
            "epistemic_status": "observed",
        }

    # A filing is public when it was *accepted*, not when its calendar date says it was
    # filed. Classifying by publication time is what stops a document accepted after the
    # interval from being presented as a contemporaneous event.
    pending: list[tuple[dict[str, Any], str]] = []
    for row in rows:
        availability = row["acceptance_datetime"] or row["filed_date"]
        if not availability:
            continue
        precision = "exact" if row["acceptance_datetime"] else "date"
        available_date = iso_date(availability)
        item = _item(row, availability, precision)
        if available_date < start:
            before_window += 1
            continue
        if available_date <= end:
            in_window_accessions.add(row["accession_number"])
            if mode == MODE_HISTORICAL and cutoff and available_date > cutoff:
                excluded_after_cutoff += 1
                continue
            item["relation"] = "in_window"
            item["known_at_range_end"] = True
            in_window.append(item)
            continue
        pending.append((item, available_date))

    for item, available_date in pending:
        is_revision_of_window = bool(
            item["is_amendment"] and item["amends_accession"] in in_window_accessions
        )
        if mode == MODE_HISTORICAL:
            # Knowable by the cutoff, but published after the move: context, never an
            # explanation of the interval.
            if cutoff and available_date <= cutoff:
                item["relation"] = "after_window"
                item["known_at_range_end"] = False
                after_window.append(item)
            else:
                excluded_after_cutoff += 1
        elif is_revision_of_window:
            item["kind"] = "sec_filing_amendment"
            item["title"] = f"{item['form_type']} amending {item['amends_accession']}"
            item["relation"] = "subsequent"
            item["known_at_range_end"] = False
            subsequent.append(item)

    coverage = {
        "filings_total_for_issuer": len(rows),
        "in_window": len(in_window),
        "after_window": len(after_window),
        "subsequent": len(subsequent),
        "before_window": before_window,
        "excluded_after_cutoff": excluded_after_cutoff,
        "excluded_unknown_availability": 0,
    }
    items = sorted(
        in_window + after_window + subsequent, key=lambda item: (item["date"], item["event_id"])
    )[:limit]
    return items, coverage


def _action_events(
    actions: Sequence[CorporateAction],
    *,
    start: str,
    end: str,
    mode: str,
    cutoff: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, Any]] = []
    excluded_after_cutoff = 0
    excluded_unknown = 0
    for action in actions:
        event_date = action.ex_date or action.effective_date
        if not event_date or not (start <= event_date <= end):
            continue
        if mode == MODE_HISTORICAL:
            if action.availability_time is None:
                excluded_unknown += 1
                continue
            if cutoff and iso_date(action.availability_time) > cutoff:
                excluded_after_cutoff += 1
                continue
        items.append(
            {
                "event_id": f"ACT-{action.action_id}",
                "kind": "corporate_action",
                "action_type": action.action_type,
                "title": action.action_type.replace("_", " ").title(),
                "date": event_date,
                "availability_time": action.availability_time,
                "availability_precision": action.availability_precision,
                "status": action.status,
                "ratio_from": str(action.ratio_from) if action.ratio_from is not None else None,
                "ratio_to": str(action.ratio_to) if action.ratio_to is not None else None,
                "cash_amount": str(action.cash_amount) if action.cash_amount is not None else None,
                "currency": action.currency,
                "computable": action.action_type in SPLIT_TYPES
                or action.action_type == "cash_dividend",
                "source_id": action.source_id,
                "evidence_id": action.evidence_id,
                "epistemic_status": "observed",
                "relation": "in_window",
                "known_at_range_end": (
                    action.availability_time is not None and iso_date(action.availability_time) <= end
                ),
            }
        )
    return items, {
        "in_window": len(items),
        "excluded_after_cutoff": excluded_after_cutoff,
        "excluded_unknown_availability": excluded_unknown,
    }


def _source_rights(db: Database, source_ids: Sequence[str]) -> dict[str, Any]:
    if not source_ids:
        return {"export_allowed": False, "sources": [], "restricted_sources": []}
    rows = db.query(
        "SELECT source_id, name, licence, redistribution, kind FROM source WHERE source_id IN ("
        + ",".join("?" for _ in source_ids)
        + ") ORDER BY source_id",
        list(source_ids),
    )
    sources = [
        {
            "source_id": row["source_id"],
            "name": row["name"],
            "licence": row["licence"],
            "redistribution": row["redistribution"],
            "kind": row["kind"],
        }
        for row in rows
    ]
    restricted = [
        row["source_id"] for row in sources if (row["redistribution"] or "") not in REDISTRIBUTABLE
    ]
    return {
        "export_allowed": not restricted,
        "sources": sources,
        "restricted_sources": restricted,
    }


# --------------------------------------------------------------------- hypotheses
def _hypothesis(
    *,
    statement: str,
    tier: int,
    basis: str,
    supporting: Sequence[str],
    contradicting: Sequence[str] = (),
    inputs: Mapping[str, Any] | None = None,
    limitations: Sequence[str] = (),
    causal_status: str = "not_identified",
) -> dict[str, Any]:
    payload = {
        "statement": statement,
        "epistemic_status": "hypothesized",
        "causal_status": causal_status,
        "relevance": {
            "tier": tier,
            "basis": basis,
            "supporting_evidence": list(supporting),
            "contradicting_evidence": list(contradicting),
            "inputs": dict(inputs or {}),
        },
        "limitations": list(limitations),
    }
    payload["hypothesis_id"] = "HYP-" + _sha256(payload)[:16]
    return payload


# ------------------------------------------------------------------------- engine
def explain_range(db: Database, request: ExplanationRequest) -> dict[str, Any]:
    """Explain one selected interval. Deterministic for identical stored state."""
    resolved = _resolve(db, request)
    warnings = list(resolved.warnings)
    points = resolved.points
    bars = [point.to_bar() for point in points]
    start, end = resolved.start_session, resolved.end_session
    cutoff = iso_date(parse_date(request.information_cutoff)) if request.information_cutoff else None

    currency = points[0].currency
    if any(point.currency != currency for point in points):
        raise ValidationError(
            "the selected interval mixes currencies; Atlas refuses to compute a return across them",
            security_id=request.security_id,
            currencies=sorted({point.currency for point in points}),
        )

    # --- the three bases over exactly the same sessions -------------------------
    bases: dict[str, list[Decimal]] = {
        basis: _basis_closes(bars, resolved.actions, basis)
        for basis in evidence.RETURN_BASES
    }
    returns = {basis: _compound(closes) for basis, closes in bases.items()}
    requested_basis = request.price_basis
    chosen = bases[requested_basis]
    chosen_returns = [value for _, value in _daily_returns(chosen)]

    split_count = sum(1 for action in resolved.actions if action.action_type in SPLIT_TYPES and action.ex_date and start <= action.ex_date <= end)
    dividend_count = sum(
        1
        for action in resolved.actions
        if action.action_type == "cash_dividend" and action.ex_date and start <= action.ex_date <= end
    )
    basis_note = evidence.RETURN_LABELS[requested_basis]
    if split_count and requested_basis == "price":
        warnings.append(
            _warning(
                "raw_basis_spans_corporate_action",
                "the raw basis spans a recorded split; the raw change is mechanical in part "
                "and is not a shareholder return",
                splits=split_count,
            )
        )

    start_close, end_close = chosen[0], chosen[-1]
    volatility = _stdev(chosen_returns)

    # --- overnight versus intraday (split-adjusted opens) -----------------------
    adjusted = split_adjust(bars, resolved.actions, include_dividends=False)
    overnight = 1.0
    intraday = 1.0
    overnight_sessions = 0
    intraday_sessions = 0
    for index, bar in enumerate(adjusted.bars):
        if index == 0:
            continue
        previous = adjusted.bars[index - 1]
        if previous.close != 0:
            overnight *= float(bar.open / previous.close)
            overnight_sessions += 1
        if bar.open != 0:
            intraday *= float(bar.close / bar.open)
            intraday_sessions += 1

    # --- volume against a trailing median --------------------------------------
    context_start = (parse_date(start) - timedelta(days=request.estimation_sessions * 3)).isoformat()
    context = evidence.select_series(
        db,
        request.security_id,
        mic=resolved.mic,
        start=context_start,
        end=end,
        anchor=evidence.select_price(db, request.security_id, end),
    )
    context_points = [point for point in context.points if point.session_date < start]
    window_volumes = [float(point.volume) for point in points if point.volume is not None]
    context_volumes = [float(point.volume) for point in context_points if point.volume is not None]
    volume_median = _median(context_volumes)
    volume_ratio = (
        (sum(window_volumes) / len(window_volumes)) / volume_median
        if window_volumes and volume_median
        else None
    )

    price_statistics = {
        "requested_basis": requested_basis,
        "basis_label": basis_note,
        "currency": currency,
        "start_session": start,
        "end_session": end,
        "sessions": len(points),
        "calendar_days": (parse_date(end) - parse_date(start)).days + 1,
        "start_price": float(start_close),
        "end_price": float(end_close),
        "absolute_change": float(end_close - start_close),
        "interval_return": returns[requested_basis],
        "start_observation_id": points[0].observation_id,
        "end_observation_id": points[-1].observation_id,
        "start_revision_seq": points[0].revision_seq,
        "end_revision_seq": points[-1].revision_seq,
        "daily_volatility": volatility,
        "annualized_volatility": volatility * math.sqrt(252) if volatility is not None else None,
        "annualization": "sample standard deviation of daily returns x sqrt(252)" if volatility is not None else None,
        "max_drawdown": _max_drawdown(chosen),
        "best_session": _extreme_session(points, chosen, best=True),
        "worst_session": _extreme_session(points, chosen, best=False),
        "overnight_compounded": overnight - 1 if overnight_sessions else None,
        "intraday_compounded": intraday - 1 if intraday_sessions else None,
        "gap_sessions": overnight_sessions,
        "gap_note": (
            "overnight/intraday split uses split-adjusted opens and closes; the product of the "
            "two components telescopes from the session before the window, so it is a "
            "description of where the move occurred, not an additive decomposition"
            if overnight_sessions
            else "an overnight/intraday split needs a prior session close and an open per session"
        ),
        "volume": {
            "sessions_with_volume": len(window_volumes),
            "total": sum(window_volumes) if window_volumes else None,
            "average": (sum(window_volumes) / len(window_volumes)) if window_volumes else None,
            "trailing_median": volume_median,
            "average_to_trailing_median": volume_ratio,
            "context_sessions": len(context_points),
            "note": (
                "the trailing median covers sessions strictly before the selected interval"
                if volume_median is not None
                else "no trailing volume history is stored, so no anomaly ratio is claimed"
            ),
        },
        "basis_reconciliation": {
            "raw": returns["price"],
            "split_adjusted": returns["split_adjusted"],
            "total_return": returns["total_return"],
            "splits_in_window": split_count,
            "dividends_in_window": dividend_count,
            "note": (
                "the three figures are computed over the same sessions and are not "
                "interchangeable; total_return is an index level change, not a price change"
            ),
        },
    }

    # --- benchmark, peers, market model ----------------------------------------
    benchmark, market_model = _benchmark_block(
        db,
        request=request,
        resolved=resolved,
        security_return=returns[requested_basis],
        warnings=warnings,
    )
    peers = _peer_block(db, request=request, resolved=resolved, warnings=warnings)

    # --- evidence --------------------------------------------------------------
    filing_items, filing_coverage = _filing_events(
        db,
        issuer_id=resolved.security["issuer_id"],
        start=start,
        end=end,
        mode=request.mode,
        cutoff=cutoff,
        limit=request.evidence_limit,
    )
    action_items, action_coverage = _action_events(
        resolved.actions, start=start, end=end, mode=request.mode, cutoff=cutoff
    )
    events = sorted(filing_items + action_items, key=lambda item: (item["date"], item["event_id"]))
    in_window_events = [item for item in events if item.get("relation") == "in_window"]
    subsequent_events = [item for item in events if item.get("relation") == "subsequent"]
    if subsequent_events:
        warnings.append(
            _warning(
                W_SUBSEQUENT_EVIDENCE,
                "evidence published after the interval is shown for review only and is "
                "excluded from the explanation ranking",
                count=len(subsequent_events),
            )
        )
    if filing_coverage["excluded_after_cutoff"] or action_coverage["excluded_after_cutoff"]:
        warnings.append(
            _warning(
                "evidence_filtered_by_cutoff",
                "records not publicly available at the information cutoff were excluded",
                filings=filing_coverage["excluded_after_cutoff"],
                corporate_actions=action_coverage["excluded_after_cutoff"],
            )
        )
    if action_coverage["excluded_unknown_availability"]:
        warnings.append(
            _warning(
                W_UNKNOWN_AVAILABILITY,
                "corporate actions with no recorded availability were excluded from the "
                "historical reconstruction",
                count=action_coverage["excluded_unknown_availability"],
            )
        )
    warnings.append(
        _warning(
            W_NO_NEWS_ARCHIVE,
            "Atlas holds no licensed news archive or press-release feed. The timeline is "
            "SEC filings and corporate actions only; absence of a headline is not evidence "
            "that no news existed.",
        )
    )
    warnings.append(
        _warning(
            W_NO_ANALYST_DATA,
            "no analyst-consensus or estimate-revision history is licensed in this deployment, "
            "so Atlas cannot test an expectations-based explanation.",
        )
    )
    if request.mode == MODE_HISTORICAL:
        warnings.append(
            _warning(
                W_PARAMETRIC_HINDSIGHT,
                "document retrieval can be cutoff-filtered, but a language model's pretraining "
                "may already contain later events. Any future AI narrative must disclose this "
                "and cannot be certified leakage-free.",
            )
        )

    coverage = {
        "sec_filings": filing_coverage,
        "corporate_actions": action_coverage,
        "news_archive": {
            "status": "unavailable",
            "reason": "no licensed news archive is present in this deployment",
        },
        "analyst_consensus": {
            "status": "unavailable",
            "reason": "no licensed consensus or estimate-revision history is present",
        },
        "macro_releases": {
            "status": "unavailable",
            "reason": "no point-in-time macroeconomic release calendar is linked to this security",
        },
        "price_series": resolved.series.summary(),
    }

    hypotheses, observations = _interpret(
        resolved=resolved,
        request=request,
        returns=returns,
        price_statistics=price_statistics,
        events=in_window_events,
        market_model=market_model,
        benchmark=benchmark,
        volume_ratio=volume_ratio,
    )

    source_ids = sorted(
        {point.source_id for point in points}
        | {item["source_id"] for item in events if item.get("source_id")}
        | ({benchmark["source_id"]} if benchmark.get("source_id") else set())
    )
    rights = _source_rights(db, source_ids)
    if not rights["export_allowed"]:
        warnings.append(
            _warning(
                W_RESTRICTED_EXPORT,
                "at least one cited source is restricted; derived statistics may be inspected "
                "locally but the resolved observation values may not be redistributed",
                restricted_sources=rights["restricted_sources"],
            )
        )

    revision_check = _revision_check(db, request.security_id, end, len(subsequent_events))
    if revision_check["subsequent_revisions"]:
        warnings.append(
            _warning(
                W_REVISION_FOUND,
                "later evidence revises or amends something in this interval; reopen the "
                "investigation in retrospective mode to see it",
                count=revision_check["subsequent_revisions"],
            )
        )

    components = {
        "engine": {"name": ENGINE_NAME, "version": ENGINE_VERSION},
        "schema": CONTRACT_VERSION,
        "request": _normalised_request(request, resolved),
        "observations": [point.observation_id for point in points],
        "actions": [action.action_id for action in resolved.actions],
        "events": [item["event_id"] for item in events],
        "peers": [peer["security_id"] for peer in peers],
    }
    reproducibility = {
        "hash_algorithm": "sha256",
        "hash": _sha256(components),
        "components": components,
        "note": (
            "identical stored observations, revisions and evidence reproduce this hash; any "
            "provider correction or new filing changes it"
        ),
    }

    ticker = _ticker(db, request.security_id, as_of=end)
    return {
        "schema": CONTRACT_VERSION,
        "engine": {"name": ENGINE_NAME, "version": ENGINE_VERSION},
        "request": _normalised_request(request, resolved),
        "selection": {
            "security_id": request.security_id,
            "issuer_id": resolved.security["issuer_id"],
            "legal_name": resolved.issuer.get("legal_name"),
            "ticker": ticker,
            "mic": resolved.mic,
            "timeframe": request.timeframe,
            "timezone": request.timezone,
            "requested_start": resolved.requested_start,
            "requested_end": resolved.requested_end,
            "start_session": start,
            "end_session": end,
            "sessions": len(points),
            "series": resolved.series.summary(),
            "start_observation": points[0].identity(),
            "end_observation": points[-1].identity(),
        },
        "price_statistics": price_statistics,
        "benchmark": benchmark,
        "peers": peers,
        "market_model": market_model,
        "events": {
            "items": events,
            "in_window_count": len(in_window_events),
            "subsequent_count": len(subsequent_events),
            "coverage": coverage,
        },
        "observations": observations,
        "hypotheses": hypotheses,
        "revision_check": revision_check,
        "rights": rights,
        "warnings": warnings,
        "refusals": [],
        "reproducibility": reproducibility,
        "limitations": [
            "daily observations only; Atlas stores no intraday bars",
            "a statistical residual is not a proven issuer-specific cause",
            "no news, consensus or macro-release source is licensed here, so the event "
            "timeline is incomplete by construction",
            "the provider's past vintage is not archived; a session's stored revision may "
            "have been published after that session",
        ],
    }


def _extreme_session(
    points: Sequence[evidence.MarketObservation], closes: Sequence[Decimal], *, best: bool
) -> dict[str, Any] | None:
    if len(closes) < 2:
        return None
    pick: tuple[int, float] | None = None
    for index in range(1, len(closes)):
        previous, current = closes[index - 1], closes[index]
        if previous == 0:
            continue
        change = float(current / previous - 1)
        if pick is None or (change > pick[1] if best else change < pick[1]):
            pick = (index, change)
    if pick is None:
        return None
    index, change = pick
    return {
        "session": points[index].session_date,
        "return": change,
        "observation_id": points[index].observation_id,
    }


def _normalised_request(
    request: ExplanationRequest, resolved: _Resolved
) -> dict[str, Any]:
    return {
        "security_id": request.security_id,
        "requested_start": resolved.requested_start,
        "requested_end": resolved.requested_end,
        "resolved_start": resolved.start_session,
        "resolved_end": resolved.end_session,
        "timeframe": request.timeframe,
        "timezone": request.timezone,
        "price_basis": request.price_basis,
        "mode": request.mode,
        "information_cutoff": (
            iso_date(parse_date(request.information_cutoff))
            if request.information_cutoff
            else None
        ),
        "benchmark_security_id": request.benchmark_security_id,
        "peer_security_ids": list(request.peer_security_ids),
        "estimation_sessions": request.estimation_sessions,
    }


def _benchmark_block(
    db: Database,
    *,
    request: ExplanationRequest,
    resolved: _Resolved,
    security_return: float,
    warnings: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    unavailable = {
        "status": "unavailable",
        "security_id": request.benchmark_security_id,
        "reason": None,
        "source_id": None,
    }
    empty_model = {"status": "unavailable", "reason": None}
    if not request.benchmark_security_id:
        warnings.append(
            _warning(
                W_NO_BENCHMARK,
                "no benchmark was requested, so no relative or market-model statistic is claimed",
            )
        )
        unavailable["reason"] = "no benchmark_security_id was supplied"
        empty_model["reason"] = "no benchmark was supplied"
        return unavailable, empty_model
    if request.benchmark_security_id == request.security_id:
        raise ValidationError(
            "a security cannot be its own benchmark", security_id=request.security_id
        )

    master = SecurityMaster(db)
    benchmark_security = master.security(request.benchmark_security_id)
    if benchmark_security is None:
        warnings.append(
            _warning(
                "benchmark_not_found",
                "the requested benchmark is not stored; no relative statistic is claimed",
                benchmark_security_id=request.benchmark_security_id,
            )
        )
        unavailable["reason"] = "unknown benchmark security"
        empty_model["reason"] = "unknown benchmark security"
        return unavailable, empty_model

    try:
        benchmark_mic = _primary_mic(db, master, request.benchmark_security_id)
    except ValidationError:
        unavailable["reason"] = "benchmark has no listing"
        empty_model["reason"] = "benchmark has no listing"
        return unavailable, empty_model

    context_start = (
        parse_date(resolved.start_session) - timedelta(days=request.estimation_sessions * 3)
    ).isoformat()
    benchmark_series = evidence.select_series(
        db,
        request.benchmark_security_id,
        mic=benchmark_mic,
        start=context_start,
        end=resolved.end_session,
    )
    benchmark_actions = ActionStore(db).list(
        request.benchmark_security_id,
        knowledge_as_of=(
            iso_date(parse_date(request.information_cutoff))
            if request.mode == MODE_HISTORICAL and request.information_cutoff
            else None
        ),
    )
    if not benchmark_series.points:
        warnings.append(
            _warning(
                "benchmark_series_empty",
                "the benchmark has no stored observations in this window; no relative "
                "statistic is claimed",
                benchmark_security_id=request.benchmark_security_id,
            )
        )
        unavailable["reason"] = "benchmark series is empty"
        empty_model["reason"] = "benchmark series is empty"
        return unavailable, empty_model

    benchmark_currency = benchmark_series.points[-1].currency
    window_points = [
        point
        for point in benchmark_series.points
        if resolved.start_session <= point.session_date <= resolved.end_session
    ]
    benchmark_basis = _basis_closes(
        [point.to_bar() for point in window_points], benchmark_actions, request.price_basis
    )
    benchmark_return = _compound(benchmark_basis)
    benchmark_block = {
        "status": "available",
        "security_id": request.benchmark_security_id,
        "ticker": _ticker(db, request.benchmark_security_id, as_of=resolved.end_session),
        "mic": benchmark_mic,
        "source_id": benchmark_series.source_id,
        "currency": benchmark_currency,
        "sessions": len(window_points),
        "first_session": window_points[0].session_date if window_points else None,
        "last_session": window_points[-1].session_date if window_points else None,
        "return": benchmark_return,
        "basis": request.price_basis,
        "basis_label": evidence.RETURN_LABELS[request.price_basis],
        "reason": None,
        "note": (
            "the benchmark is measured on its own stored series; if its sessions differ from "
            "the security's, the comparison uses each series over the same date bounds"
        ),
    }

    # Alignment for the market model: intersection of observed sessions, strictly before
    # the event window, so no in-window return estimates the model that scores it.
    security_context = evidence.select_series(
        db,
        request.security_id,
        mic=resolved.mic,
        start=context_start,
        end=resolved.end_session,
        anchor=evidence.select_price(db, request.security_id, resolved.end_session),
    )
    by_date_security = {
        point.session_date: point for point in security_context.points
        if point.session_date < resolved.start_session
    }
    benchmark_before = {
        point.session_date: point
        for point in benchmark_series.points
        if point.session_date < resolved.start_session
    }
    common = sorted(set(by_date_security) & set(benchmark_before))
    aligned_security = [by_date_security[day] for day in common]
    aligned_benchmark = [benchmark_before[day] for day in common]
    security_closes = _basis_closes(
        [point.to_bar() for point in aligned_security], resolved.actions, request.price_basis
    )
    benchmark_closes = _basis_closes(
        [point.to_bar() for point in aligned_benchmark], benchmark_actions, request.price_basis
    )
    y = [value for _, value in _daily_returns(security_closes)]
    x = [value for _, value in _daily_returns(benchmark_closes)]
    usable = min(len(y), len(x), request.estimation_sessions)
    y, x = y[-usable:], x[-usable:]
    dates = common[1:][-usable:] if len(common) > 1 else []

    security_currency = resolved.points[0].currency
    if benchmark_currency != security_currency:
        warnings.append(
            _warning(
                W_BENCHMARK_CURRENCY,
                "the benchmark trades in a different currency; no excess return or beta is "
                "computed without an explicit FX convention",
                security_currency=security_currency,
                benchmark_currency=benchmark_currency,
            )
        )
        return benchmark_block, {
            "status": "unavailable",
            "reason": "currency mismatch between security and benchmark",
        }

    excess = security_return - benchmark_return
    benchmark_block["excess_return_arithmetic"] = excess
    benchmark_block["excess_note"] = (
        "a simple difference between two interval returns, not a compounded attribution"
    )

    if usable < MIN_MARKET_MODEL_SESSIONS:
        warnings.append(
            _warning(
                W_ESTIMATION_SHORT,
                "too few aligned pre-interval sessions estimate the market model; no beta or "
                "residual is claimed",
                aligned_sessions=usable,
                required=MIN_MARKET_MODEL_SESSIONS,
            )
        )
        return benchmark_block, {
            "status": "unavailable",
            "reason": "insufficient aligned sessions before the interval",
            "aligned_sessions": usable,
        }

    fit = _ols(y, x)
    if fit is None:
        return benchmark_block, {
            "status": "unavailable",
            "reason": "benchmark returns have no variance in the estimation window",
            "aligned_sessions": usable,
        }
    if usable < len(common) - 1:
        warnings.append(
            _warning(
                W_BENCHMARK_UNALIGNED,
                "the estimation window was truncated to the requested length; aligned "
                "sessions beyond it were not used",
                aligned_available=len(common) - 1,
                used=usable,
            )
        )
    market_component = fit["beta"] * benchmark_return
    return benchmark_block, {
        "status": "available",
        "model": "single-factor market model (OLS on daily simple returns)",
        "basis": request.price_basis,
        "estimation": {
            "sessions": fit["observations"],
            "first_session": dates[0] if dates else None,
            "last_session": dates[-1] if dates else None,
            "window_rule": "aligned sessions strictly before the selected interval, "
            "most recent sessions up to estimation_sessions",
            "aligned_available": max(0, len(common) - 1),
        },
        "alpha_daily": fit["alpha_daily"],
        "beta": fit["beta"],
        "r_squared": fit["r_squared"],
        "benchmark_return": benchmark_return,
        "market_component_of_return": market_component,
        "residual_return_arithmetic": security_return - market_component,
        "applicability": [
            "the coefficients describe co-movement in the estimation window, not a stable law",
            "the residual is what this one-factor model does not explain; it is not evidence of "
            "an issuer-specific cause",
            "a beta estimated on one benchmark does not identify sector or style exposures",
            "arithmetic decomposition does not compound exactly over multiple sessions",
        ],
    }


def _peer_block(
    db: Database,
    *,
    request: ExplanationRequest,
    resolved: _Resolved,
    warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Window returns for an explicitly supplied peer universe.

    Each peer is measured on its own stored series over the same date bounds. No peer is
    silently substituted, and a different currency is reported as not comparable rather
    than converted without an FX convention.
    """
    if not request.peer_security_ids:
        return []
    if len(request.peer_security_ids) > MAX_PEERS:
        warnings.append(
            _warning(
                W_PEER_LIMIT,
                f"only the first {MAX_PEERS} peer security ids are evaluated",
                requested=len(request.peer_security_ids),
                limit=MAX_PEERS,
            )
        )
    master = SecurityMaster(db)
    cutoff = (
        iso_date(parse_date(request.information_cutoff))
        if request.mode == MODE_HISTORICAL and request.information_cutoff
        else None
    )
    currency = resolved.points[0].currency
    items: list[dict[str, Any]] = []
    for peer_id in list(dict.fromkeys(request.peer_security_ids))[:MAX_PEERS]:
        if peer_id == request.security_id:
            items.append(
                {
                    "security_id": peer_id,
                    "status": "unavailable",
                    "reason": "the selected security is not its own peer",
                    "comparable": False,
                }
            )
            continue
        security = master.security(peer_id)
        if security is None:
            items.append(
                {
                    "security_id": peer_id,
                    "status": "unavailable",
                    "reason": "unknown security",
                    "comparable": False,
                }
            )
            continue
        try:
            mic = _primary_mic(db, master, peer_id)
        except ValidationError:
            items.append(
                {
                    "security_id": peer_id,
                    "status": "unavailable",
                    "reason": "peer has no listing",
                    "comparable": False,
                }
            )
            continue
        series = evidence.select_series(
            db, peer_id, mic=mic, start=resolved.start_session, end=resolved.end_session
        )
        if not series.points:
            items.append(
                {
                    "security_id": peer_id,
                    "ticker": _ticker(db, peer_id, as_of=resolved.end_session),
                    "status": "unavailable",
                    "reason": "no peer observations in this window",
                    "comparable": False,
                }
            )
            continue
        actions = ActionStore(db).list(peer_id, knowledge_as_of=cutoff)
        closes = _basis_closes([point.to_bar() for point in series.points], actions, request.price_basis)
        peer_currency = series.points[0].currency
        same_currency = peer_currency == currency
        items.append(
            {
                "security_id": peer_id,
                "ticker": _ticker(db, peer_id, as_of=resolved.end_session),
                "status": "available",
                "mic": mic,
                "source_id": series.source_id,
                "currency": peer_currency,
                "sessions": len(series.points),
                "first_session": series.points[0].session_date,
                "last_session": series.points[-1].session_date,
                "return": _compound(closes) if closes else None,
                "basis": request.price_basis,
                "comparable": same_currency,
                "reason": None if same_currency else "peer trades in a different currency",
            }
        )
    return items


def _revision_check(
    db: Database, security_id: str, end: str, subsequent_events: int
) -> dict[str, Any]:
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM corporate_action WHERE security_id=? AND supersedes IS NOT NULL "
        "AND observed_at > ?",
        (security_id, end),
    )
    corrected_after = int(row["n"] or 0) if row is not None else 0
    return {
        "subsequent_revisions": subsequent_events + corrected_after,
        "amending_filings": subsequent_events,
        "corrected_corporate_actions": corrected_after,
        "status": "revisions_found" if (subsequent_events + corrected_after) else "no_revisions_found",
    }


def _interpret(
    *,
    resolved: _Resolved,
    request: ExplanationRequest,
    returns: Mapping[str, float],
    price_statistics: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    market_model: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    volume_ratio: float | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate confirmed observations from competing, unproven explanations."""
    total = returns[request.price_basis]
    observations: list[dict[str, Any]] = [
        {
            "observation_id": "OBS-interval-return",
            "statement": (
                f"The {request.price_basis} change from {resolved.start_session} to "
                f"{resolved.end_session} is {total:.6f}."
            ),
            "value": total,
            "unit": "ratio",
            "evidence": [
                resolved.points[0].observation_id,
                resolved.points[-1].observation_id,
            ],
            "derivation": "last selected close / first selected close - 1 on the declared basis",
        },
        {
            "observation_id": "OBS-session-count",
            "statement": (
                f"{price_statistics['sessions']} stored session(s) fall inside the interval; "
                f"the venue calendar reports {resolved.series.missing_sessions if resolved.series.missing_sessions is not None else 'unknown'} missing session(s)."
            ),
            "value": price_statistics["sessions"],
            "unit": "sessions",
            "evidence": list(resolved.series.observation_ids()),
            "derivation": "canonical series selection (one provider, one revision per session)",
        },
    ]
    if market_model.get("status") == "available":
        observations.append(
            {
                "observation_id": "OBS-market-model",
                "statement": (
                    f"Over the estimation window the security's daily returns had a beta of "
                    f"{market_model['beta']:.4f} and R-squared of "
                    f"{(market_model['r_squared'] if market_model['r_squared'] is not None else float('nan')):.4f} "
                    "against the selected benchmark."
                ),
                "value": market_model["beta"],
                "unit": "beta",
                "evidence": list(resolved.series.observation_ids()),
                "derivation": "OLS of aligned daily simple returns before the interval",
            }
        )

    hypotheses: list[dict[str, Any]] = []
    filing_events = [item for item in events if item["kind"] == "sec_filing"]
    action_events = [item for item in events if item["kind"] == "corporate_action"]
    material_filings = [
        item for item in filing_events if str(item.get("form_type")) in MATERIAL_FORMS
    ]
    routine_filings = len(filing_events) - len(material_filings)

    if material_filings:
        forms = sorted({str(item["form_type"]) for item in material_filings})
        hypotheses.append(
            _hypothesis(
                statement=(
                    "A reported disclosure was published during the interval "
                    f"({', '.join(forms)}). The move may reflect how that disclosure changed "
                    "expectations, but Atlas has not measured an expectations revision."
                ),
                tier=2,
                basis="a material SEC disclosure was published inside the selected interval",
                supporting=[item["event_id"] for item in material_filings],
                inputs={
                    "forms": forms,
                    "count": len(material_filings),
                    "routine_filings_not_ranked": routine_filings,
                },
                limitations=[
                    "publication inside the interval does not establish that the filing moved the price",
                    "Atlas holds no consensus history, so the surprise component is unmeasured",
                    "an 8-K may describe an event that occurred before the interval",
                ],
            )
        )

    mechanical = [
        item
        for item in action_events
        if item["action_type"] in SPLIT_TYPES or item["action_type"] == "cash_dividend"
    ]
    if mechanical:
        hypotheses.append(
            _hypothesis(
                statement=(
                    "Part of the raw price change is mechanical: the interval contains "
                    + ", ".join(sorted({str(item['action_type']) for item in mechanical}))
                    + ". Compare the split-adjusted and total-return bases before treating the "
                    "raw change as performance."
                ),
                tier=1,
                basis="a corporate action with a computable, arithmetic price effect has an ex-date inside the interval; this outranks any narrative because the effect is certain",
                supporting=[item["event_id"] for item in mechanical],
                inputs={
                    "raw_return": returns["price"],
                    "split_adjusted_return": returns["split_adjusted"],
                    "total_return": returns["total_return"],
                },
                limitations=["the action explains a basis change, not the economic direction of the move"],
            )
        )

    if market_model.get("status") == "available" and total != 0:
        component = float(market_model["market_component_of_return"])
        residual = float(market_model["residual_return_arithmetic"])
        explained_share = component / total
        if explained_share >= 0.5:
            statement = (
                "Most of the interval's change is consistent with benchmark co-movement: "
                f"beta {market_model['beta']:.3f} times the benchmark's {benchmark.get('return', 0.0):.4f} "
                f"return accounts for {component:.4f} of the {total:.4f} move. The remaining "
                f"{residual:.4f} is unexplained by this model."
            )
            basis = "the market-model component has the same sign and at least half the magnitude of the move"
        else:
            statement = (
                "A company-specific component remains after market adjustment: of the "
                f"{total:.4f} move, beta times the benchmark explains {component:.4f}, leaving "
                f"{residual:.4f}. A company-specific event is plausible but not identified."
            )
            basis = "the market-model residual is larger than the explained component"
        hypotheses.append(
            _hypothesis(
                statement=statement,
                tier=3,
                basis=basis,
                supporting=list(resolved.series.observation_ids()[-3:]),
                inputs={
                    "beta": market_model["beta"],
                    "benchmark_return": benchmark.get("return"),
                    "market_component": component,
                    "residual": residual,
                    "explained_share_of_total": explained_share,
                },
                limitations=[
                    "one benchmark and one factor do not identify sector, style or idiosyncratic exposure",
                    "the residual is not a cause; it is what the model does not explain",
                    "beta instability and estimation error are not propagated into this arithmetic decomposition",
                ],
            )
        )

    if volume_ratio is not None and volume_ratio >= 2.0:
        hypotheses.append(
            _hypothesis(
                statement=(
                    f"Trading volume in the interval averaged {volume_ratio:.2f} times its "
                    "trailing median. Unusual participation is consistent with a "
                    "information-driven repricing, but volume does not identify the information."
                ),
                tier=4,
                basis="mean window volume is at least twice the trailing median",
                supporting=list(resolved.series.observation_ids()[-3:]),
                inputs={"average_to_trailing_median": volume_ratio},
                limitations=[
                    "volume can rise for index rebalancing, option expiry or liquidity reasons",
                    "no order-book or participant data is stored",
                ],
            )
        )

    if not material_filings and not mechanical:
        statement = (
            "No material company-specific SEC disclosure or corporate action inside this "
            "interval is stored. Atlas cannot explain the move from its sources and abstains "
            "rather than inferring a cause."
        )
        if routine_filings:
            statement += (
                f" {routine_filings} routine filing(s) (for example Form 4 ownership reports or "
                "Form 144 notices) are present but are not evidence of a repricing."
            )
        hypotheses.append(
            _hypothesis(
                statement=statement,
                tier=5,
                basis="no material in-window disclosure or corporate action is present in the store",
                supporting=[],
                inputs={"routine_filings_not_ranked": routine_filings},
                limitations=[
                    "absence of stored evidence is not absence of news",
                    "routine administrative filings are not treated as explanations",
                    "the news archive, consensus history and macro-release calendar are not licensed here",
                ],
            )
        )

    hypotheses.sort(key=lambda item: (item["relevance"]["tier"], item["hypothesis_id"]))
    for rank, hypothesis in enumerate(hypotheses, start=1):
        hypothesis["rank"] = rank
    return hypotheses, observations


__all__ = [
    "CONTRACT_VERSION",
    "ENGINE_NAME",
    "ENGINE_VERSION",
    "MODES",
    "MODE_HISTORICAL",
    "MODE_RETROSPECTIVE",
    "SUPPORTED_TIMEFRAMES",
    "ExplanationRequest",
    "explain_range",
]
