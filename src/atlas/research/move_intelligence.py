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
from ..core.temporal import (
    availability_from_date,
    iso_date,
    parse_date,
    parse_iso,
)
from ..entities.master import SecurityMaster
from ..market import evidence
from . import filing_evidence as fe
from ..market.actions import ActionStore, SPLIT_TYPES, CorporateAction
from ..market.adjust import split_adjust, total_return
from ..market.bars import Bar
from ..market.calendar import TradingCalendar
from ..storage.db import Database

ENGINE_NAME = "atlas.price_explanation.engine"
ENGINE_VERSION = "3.0.0"
CONTRACT_VERSION = "atlas.price_explanation.v3"

MODE_HISTORICAL = "historical_reconstruction"
MODE_RETROSPECTIVE = "retrospective_investigation"
MODES = (MODE_HISTORICAL, MODE_RETROSPECTIVE)

SUPPORTED_TIMEFRAMES = ("1d",)
RETURN_CONVENTIONS = ("interval_close_to_close", "single_session_close_to_close")
RETURN_CONVENTION_AUTO = "auto"
CALCULATION_VERSION = "atlas.price_explanation.calculation.v3"
MARKET_MODEL_VERSION = "atlas.price_explanation.market_model.v2"
#: The availability policy this engine applies to every publication time. It is the
#: Temporal Evidence Kernel's policy, referenced rather than re-implemented.
AVAILABILITY_POLICY = "atlas.temporal_evidence.availability.v1"
ANNUALIZATION_SESSIONS = 252
#: Minimum share of the security's window sessions a benchmark must cover before a
#: relative statistic is claimed. Below this, the comparison is refused, not shrunk.
MIN_BENCHMARK_COVERAGE = 0.5
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
W_SINGLE_SESSION_PREVIOUS = "single_session_uses_previous_session"
W_SINGLE_SESSION_UNAVAILABLE = "single_session_previous_unavailable"
W_MISSING_SESSIONS = "missing_sessions_in_window"
W_NO_NEWS_ARCHIVE = "news_archive_unavailable"
W_NO_ANALYST_DATA = "analyst_consensus_unavailable"
W_NO_BENCHMARK = "benchmark_not_requested"
W_BENCHMARK_UNALIGNED = "benchmark_sessions_unaligned"
W_BENCHMARK_CURRENCY = "benchmark_currency_mismatch"
W_ESTIMATION_SHORT = "estimation_window_too_short"
W_SUBSEQUENT_EVIDENCE = "subsequent_evidence_excluded"
W_UNKNOWN_AVAILABILITY = "evidence_availability_unknown"
W_UNKNOWN_FILING_AVAILABILITY = "filing_availability_unknown"
W_MODELLED_FILING_AVAILABILITY = "filing_availability_modelled_bound"
W_DOCUMENT_NOT_INGESTED = "original_document_not_ingested"
W_DOCUMENT_NOT_AT_CUTOFF = "document_not_available_at_cutoff"
W_TIMEZONE_SHIFT = "publication_local_date_differs"
W_AFTER_FINAL_CLOSE = "filing_after_final_session_close"
W_EVENT_DUPLICATE = "duplicate_event_suppressed"
W_DOCUMENT_RESTRICTED = "document_text_not_redistributable"
W_RESTRICTED_EXPORT = "restricted_source_not_exportable"
W_PARAMETRIC_HINDSIGHT = "parametric_hindsight_disclosed"
W_PROVIDER_VINTAGE = "provider_vintage_not_proven"
W_VINTAGE_AT_CUTOFF = "price_vintage_unverified_at_cutoff"
W_DATE_PRECISION = "date_precision_availability"
W_UNKNOWN_SOURCE = "unregistered_source"
W_MISSING_LICENCE = "source_licence_missing"
W_BENCHMARK_EMPTY = "benchmark_no_comparable_observations"
W_BENCHMARK_ALIGNMENT = "benchmark_alignment_insufficient"
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
    #: ``auto`` resolves to an interval close-to-close return for multi-session
    #: selections and a prior-session close-to-close return for a one-candle selection.
    return_convention: str = RETURN_CONVENTION_AUTO


@dataclass(slots=True)
class _Resolved:
    security: dict[str, Any]
    mic: str
    issuer: dict[str, Any]
    series: evidence.MarketSeriesSelection
    points: list[evidence.MarketObservation]
    actions: list[CorporateAction]
    context: evidence.MarketSeriesSelection
    previous_point: evidence.MarketObservation | None
    requested_start: str
    requested_end: str
    start_session: str
    end_session: str
    action_exclusions: dict[str, int] = field(default_factory=dict)
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
    if request.return_convention not in (RETURN_CONVENTION_AUTO, *RETURN_CONVENTIONS):
        raise ValidationError(
            "unknown return convention",
            requested=request.return_convention,
            supported=[RETURN_CONVENTION_AUTO, *RETURN_CONVENTIONS],
        )
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
                "the interval contains one stored session; the move is measured from the "
                "previous eligible close when one is stored, and refused with a reason "
                "when none is. Atlas never reports a flat 0% for a one-candle selection.",
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

    all_actions = ActionStore(db).list(request.security_id)
    actions = ActionStore(db).list(
        request.security_id, knowledge_as_of=cutoff if request.mode == MODE_HISTORICAL else None
    )
    kept_action_ids = {action.action_id for action in actions}
    action_exclusions = {
        "excluded_unknown_availability": sum(
            1
            for action in all_actions
            if action.action_id not in kept_action_ids and action.availability_time is None
        ),
        "excluded_after_cutoff": sum(
            1
            for action in all_actions
            if action.action_id not in kept_action_ids
            and action.availability_time is not None
            and cutoff is not None
            and iso_date(action.availability_time) > cutoff
        ),
    }

    # Context is the same provider's series over a bounded lookback. It supplies the
    # previous eligible session for a one-candle return, the trailing volume baseline and
    # the market-model estimation window. It never contributes a spliced price.
    context_start = (
        parse_date(start_session) - timedelta(days=request.estimation_sessions * 3)
    ).isoformat()
    context = evidence.select_series(
        db,
        request.security_id,
        mic=mic,
        start=context_start,
        end=end_session,
        anchor=evidence.select_price(db, request.security_id, end_session),
    )
    previous_point = next(
        (
            point
            for point in reversed(list(context.points))
            if point.session_date < start_session
        ),
        None,
    )
    return _Resolved(
        security=security,
        mic=mic,
        issuer=issuer,
        series=series,
        points=points,
        actions=actions,
        action_exclusions=action_exclusions,
        context=context,
        previous_point=previous_point,
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


def _window_instant(day: str, *, end_of_day: bool) -> str:
    """A session-date boundary as a UTC instant.

    The window *ends* at end-of-day, matching the kernel's conservative date policy for
    date-only evidence. It *begins* at 00:00:00Z: a filing published during the first
    session's day is inside the interval. Using the end-of-day pin for both boundaries
    silently dropped every publication before 23:59:59 on the first day.
    """
    if end_of_day:
        return availability_from_date(day, "price_explanation.window_end_end_of_day_utc").iso
    return f"{iso_date(day)}T00:00:00Z"


def _session_bounds(db: Database, mic: str, start: str, end: str) -> dict[str, tuple[str, str]]:
    """Stored venue open/close instants for the sessions around the interval.

    A calendar is optional metadata: without one the phase is reported as unknown rather
    than assumed from a hard-coded market open.
    """
    try:
        calendar = TradingCalendar(db)
        calendar.ensure_range(mic, start, end)
        return {
            session.session_date: (session.open_ts, session.close_ts)
            for session in calendar.sessions(mic, start, end)
        }
    except Exception:  # noqa: BLE001 - a missing calendar must not fail an investigation
        return {}


def _venue_timezone(db: Database, mic: str) -> str | None:
    """The exchange's own timezone, used to date a publication in venue-local time."""
    try:
        row = db.query_one("SELECT timezone FROM venue WHERE mic = ?", (mic.upper(),))
    except Exception:  # noqa: BLE001 - a missing venue row is a display limitation
        return None
    return str(row["timezone"]) if row is not None and row["timezone"] else None


def _filing_events(
    db: Database,
    *,
    issuer_id: str,
    start: str,
    end: str,
    mode: str,
    cutoff: str | None,
    limit: int,
    timezone: str,
    mic: str,
    stored_sessions: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Filings whose *publication* time is evidenced, ordered by that time.

    Ordering and admissibility use the availability instant produced by the Temporal
    Evidence Kernel policy: an SEC acceptance timestamp is exact, a filed date alone is
    pinned to the end of its UTC day, and a filing with no publication time is never
    admitted to the ranking. The SEC filed date is retained separately as metadata.

    Explanatory eligibility is not the calendar interval. A filing published after the
    final selected session's close cannot explain that closed candle even when its
    publication date is inside the interval: its first eligible trading session is a
    later session that the reader has not selected. Such evidence stays visible with
    relation ``subsequent_to_price_window`` and is excluded from the ranking.
    """
    rows = db.query(
        "SELECT * FROM filing WHERE issuer_id=? ORDER BY filed_date, accession_number",
        (issuer_id,),
    )
    cutoff_at = fe.cutoff_instant(cutoff)
    window_start_at = _window_instant(start, end_of_day=False)
    window_end_at = _window_instant(end, end_of_day=True)
    session_bound_rows = _session_bounds(
        db, mic, (parse_date(start) - timedelta(days=7)).isoformat(),
        (parse_date(end) + timedelta(days=21)).isoformat(),
    )
    venue_timezone = _venue_timezone(db, mic)
    final_bounds = session_bound_rows.get(end)
    final_close_at = final_bounds[1] if final_bounds else None
    next_after_final = next(
        (day for day in sorted(session_bound_rows) if day > end), None
    )
    in_window: list[dict[str, Any]] = []
    after_window: list[dict[str, Any]] = []
    subsequent: list[dict[str, Any]] = []
    subsequent_to_window: list[dict[str, Any]] = []
    excluded_after_cutoff = 0
    unknown_availability = 0
    before_window = 0
    timezone_shifted = 0
    published_after_final_close = 0
    in_window_accessions: set[str] = set()
    document_counts = {
        fe.DOC_RESOLVED: 0,
        fe.DOC_NOT_INGESTED: 0,
        fe.DOC_NOT_AT_CUTOFF: 0,
        fe.DOC_UNKNOWN_AVAILABILITY: 0,
        fe.DOC_UNAVAILABLE: 0,
        "text_unavailable": 0,
    }

    def _item(row: Any, availability: str, precision: str, basis: str) -> dict[str, Any]:
        locator = fe.source_locator(row["cik"], row["accession_number"], row["primary_document"])
        publication = fe.publication_context(
            availability=availability,
            precision=precision,
            timezone=timezone,
            venue_timezone=venue_timezone,
            session_bounds=session_bound_rows,
            stored_sessions=stored_sessions,
        )
        availability_date = iso_date(availability)
        local_date = publication["local_time"][:10] if publication["local_time"] else None
        return {
            "event_id": f"FIL-{row['filing_id']}",
            "kind": "sec_filing",
            "form_type": row["form_type"],
            "form_label": _FORM_LABELS.get(row["form_type"], row["form_type"]),
            "title": f"{row['form_type']} filed",
            # `date` and `filed_date` are the SEC calendar filing date, kept as metadata.
            "date": row["filed_date"],
            "filed_date": row["filed_date"],
            "acceptance_datetime": row["acceptance_datetime"],
            # The ordering key and the published date are the availability instant.
            "publication_date": availability_date,
            "availability_time": availability,
            "availability_precision": precision,
            "availability_basis": basis,
            "publication": publication,
            "publication_local_date_differs": bool(local_date and local_date != availability_date),
            "period_of_report": row["period_of_report"],
            "accession_number": row["accession_number"],
            "is_amendment": bool(row["is_amendment"]),
            "amends_accession": row["amends_accession"],
            "filing_version": "amendment" if row["is_amendment"] else "original",
            "source_id": row["source_id"],
            "source_url": locator.get("url"),
            "source_locator": locator,
            "document": None,
            "disclosed_items": [],
            "passages": [],
            "novelty": None,
            "issuer_relevance": {
                "level": "direct",
                "basis": "the filing is registered to this investigation's issuer",
            },
            "epistemic_status": "observed",
            "explanatory_eligible": False,
            "explanatory_eligibility": {
                "eligible": False,
                "basis": "not evaluated",
                "final_session": end,
                "final_session_close": final_close_at,
                "first_eligible_session": publication.get("tradable_session"),
                "reason": None,
            },
        }

    def _eligibility(available: str, publication: Mapping[str, Any]) -> dict[str, Any]:
        """Whether a publication could have been reflected in the final selected close."""
        tradable = publication.get("tradable_session")
        if final_close_at is None:
            eligible = available <= window_end_at
            return {
                "eligible": eligible,
                "basis": (
                    "no stored venue session close for the final selected session; "
                    "end-of-day UTC is used conservatively"
                ),
                "final_session": end,
                "final_session_close": None,
                "first_eligible_session": tradable,
                "reason": (
                    None
                    if eligible
                    else "published after the end-of-day fallback boundary for the window"
                ),
            }
        eligible = parse_iso(available) < parse_iso(final_close_at)
        reason = None
        if not eligible:
            reason = (
                f"published at {available}, at or after the close of the final selected "
                f"session {end} ({final_close_at}); its first eligible trading session is "
                f"{tradable or 'not stored'}, so it cannot explain that close"
            )
        return {
            "eligible": eligible,
            "basis": (
                "publication instant precedes the final selected session's close"
                if eligible
                else "publication instant is at or after the final selected session's close"
            ),
            "final_session": end,
            "final_session_close": final_close_at,
            "first_eligible_session": tradable,
            "reason": reason,
        }

    # A filing is public when it was *accepted*, not when its calendar date says it was
    # filed. A date-only filing is available at end-of-day UTC, never at its first second.
    pending: list[tuple[dict[str, Any], str]] = []
    for row in rows:
        available, precision, basis = fe.filing_availability(row)
        if available is None:
            unknown_availability += 1
            continue
        if available < window_start_at:
            before_window += 1
            continue
        item = _item(row, available, precision, basis)
        if item["publication_local_date_differs"]:
            timezone_shifted += 1
        eligibility = _eligibility(available, item["publication"])
        item["explanatory_eligible"] = eligibility["eligible"]
        item["explanatory_eligibility"] = eligibility
        if available <= window_end_at:
            in_window_accessions.add(row["accession_number"])
            if mode == MODE_HISTORICAL and cutoff_at and available > cutoff_at:
                excluded_after_cutoff += 1
                continue
            if eligibility["eligible"]:
                item["relation"] = "in_window"
                item["known_at_range_end"] = True
                in_window.append(item)
            else:
                # Visible, but not a candidate explanation of the final closed candle.
                item["relation"] = "subsequent_to_price_window"
                item["known_at_range_end"] = True
                published_after_final_close += 1
                subsequent_to_window.append(item)
            continue
        pending.append((item, available))

    for item, available in pending:
        is_revision_of_window = bool(
            item["is_amendment"] and item["amends_accession"] in in_window_accessions
        )
        if mode == MODE_HISTORICAL:
            # Knowable by the cutoff, but published after the move: context, never an
            # explanation of the interval.
            if cutoff_at and available <= cutoff_at:
                item["relation"] = "after_window"
                item["known_at_range_end"] = False
                after_window.append(item)
            else:
                excluded_after_cutoff += 1
            continue
        item["explanatory_eligible"] = False
        item["known_at_range_end"] = False
        item["explanatory_eligibility"] = {
            **item["explanatory_eligibility"],
            "eligible": False,
            "reason": (
                f"published at {available}, after the selected interval ended on {end}; "
                "it is retrospective context, not contemporaneous evidence"
            ),
        }
        if is_revision_of_window:
            item["kind"] = "sec_filing_amendment"
            item["title"] = f"{item['form_type']} amending {item['amends_accession']}"
            item["relation"] = "subsequent"
            subsequent.append(item)
        # A later non-amendment filing is outside the selected calendar interval, so it is
        # not part of this investigation's timeline. The in-interval after-close case is
        # handled above and stays visible as subsequent_to_price_window.

    # Order by evidenced publication time, not by the SEC calendar date. Ties break on
    # the event id so the order is reproducible.
    ordered = sorted(
        in_window + after_window + subsequent + subsequent_to_window,
        key=lambda item: (item["availability_time"], item["event_id"]),
    )[:limit]

    duplicates: list[dict[str, Any]] = []
    seen_identity: dict[str, str] = {}
    seen_document: dict[str, str] = {}
    kept: list[dict[str, Any]] = []
    for item in ordered:
        identity = f"{item['kind']}:{item.get('accession_number') or item['event_id']}"
        if identity in seen_identity:
            duplicates.append({"event_id": item["event_id"], "duplicate_of": seen_identity[identity]})
            continue
        seen_identity[identity] = item["event_id"]
        if item["kind"].startswith("sec_filing"):
            document = fe.resolve_document(
                db,
                row=db.query_one(
                    "SELECT * FROM filing WHERE accession_number = ?",
                    (item["accession_number"],),
                ),
                cutoff=cutoff_at,
                mode_historical=mode == MODE_HISTORICAL,
            )
            item["document"] = document
            item["disclosed_items"] = document.get("items", [])
            item["passages"] = document.get("passages", [])
            status = document.get("status")
            document_counts[status] = document_counts.get(status, 0) + 1
            if document.get("source_locator", {}).get("url"):
                item["source_url"] = document["source_locator"]["url"]
            sha = document.get("sha256")
            if sha:
                if sha in seen_document:
                    item["duplicate_document_of"] = seen_document[sha]
                    duplicates.append(
                        {
                            "event_id": item["event_id"],
                            "duplicate_document_of": seen_document[sha],
                            "reason": "identical primary-document bytes",
                        }
                    )
                else:
                    seen_document[sha] = item["event_id"]
            if document.get("items"):
                item["novelty"] = fe.prior_item_disclosure(
                    db,
                    issuer_id=issuer_id,
                    items=[entry["item"] for entry in document["items"]],
                    before_instant=item["availability_time"],
                )
            if item["is_amendment"] and item.get("amends_accession"):
                prior = db.query_one(
                    "SELECT filing_id FROM filing WHERE accession_number = ?",
                    (item["amends_accession"],),
                )
                item["supersedes_event_id"] = (
                    f"FIL-{prior['filing_id']}" if prior is not None else None
                )
                item["original_evidence_retained"] = True
        kept.append(item)

    kept.sort(key=lambda item: (item["availability_time"], item["event_id"]))
    resolved = sum(1 for item in kept if (item.get("document") or {}).get("status") == fe.DOC_RESOLVED)
    coverage = {
        "filings_total_for_issuer": len(rows),
        "in_window": len(in_window),
        "after_window": len(after_window),
        "subsequent": len(subsequent),
        "subsequent_to_price_window": len(subsequent_to_window),
        "published_after_final_session_close": published_after_final_close,
        "before_window": before_window,
        "excluded_after_cutoff": excluded_after_cutoff,
        "excluded_unknown_availability": unknown_availability,
        "publications_with_local_date_shift": timezone_shifted,
        "duplicates_suppressed": len(duplicates),
        "final_session": end,
        "final_session_close": final_close_at,
        "first_session_after_final": next_after_final,
        "explanatory_eligibility_basis": (
            "a publication is explainable only if its availability instant precedes the "
            "final selected session's close"
        ),
        "documents": {
            **document_counts,
            "resolved_in_returned_items": resolved,
            "note": (
                "a document is resolved only when Atlas archived its bytes and, in "
                "historical mode, it was publicly available at the cutoff"
            ),
        },
        "availability_policy": AVAILABILITY_POLICY,
        "publications_with_modelled_availability": sum(
            1
            for item in kept
            if (item.get("document") or {}).get("availability_is_upper_bound")
        ),
    }
    return kept, coverage, duplicates


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
    unknown_availability = 0
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
        relation = "in_window"
        if action.availability_time is None:
            # Retrospective mode may show the action, but an unevidenced publication time
            # cannot be placed inside the window or used as a contemporaneous explanation.
            unknown_availability += 1
            relation = "unknown_availability"
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
                "relation": relation,
                "known_at_range_end": (
                    action.availability_time is not None and iso_date(action.availability_time) <= end
                ),
            }
        )
    return items, {
        "in_window": sum(1 for item in items if item["relation"] == "in_window"),
        "unknown_availability": unknown_availability,
        "excluded_after_cutoff": excluded_after_cutoff,
        "excluded_unknown_availability": excluded_unknown,
    }


def _source_rights(db: Database, source_ids: Sequence[str]) -> dict[str, Any]:
    """Decide export rights over every contributing source, failing closed.

    Three states are refused, not assumed benign: a source id that is not registered at
    all, a redistribution class outside :data:`REDISTRIBUTABLE`, and a registered source
    with no recorded licence. An unknown class never becomes implicitly redistributable,
    and an empty source set cannot authorise an export.
    """
    unique = sorted({str(source_id) for source_id in source_ids if source_id})
    if not unique:
        return {
            "export_allowed": False,
            "sources": [],
            "restricted_sources": [],
            "unregistered_sources": [],
            "reasons": ["no source records were collected, so the export fails closed"],
        }
    rows = {
        row["source_id"]: row
        for row in db.query(
            "SELECT source_id, name, licence, redistribution, kind FROM source WHERE source_id IN ("
            + ",".join("?" for _ in unique)
            + ") ORDER BY source_id",
            list(unique),
        )
    }
    sources: list[dict[str, Any]] = []
    restricted: list[str] = []
    unregistered: list[str] = []
    missing_licence: list[str] = []
    reasons: list[str] = []
    for source_id in unique:
        row = rows.get(source_id)
        if row is None:
            sources.append(
                {
                    "source_id": source_id,
                    "name": None,
                    "licence": None,
                    "redistribution": "unregistered",
                    "kind": None,
                    "registered": False,
                    "export_allowed": False,
                }
            )
            restricted.append(source_id)
            unregistered.append(source_id)
            reasons.append(f"{source_id}: not registered in the source table")
            continue
        redistribution = (row["redistribution"] or "").strip()
        licence = (row["licence"] or "").strip()
        permitted = redistribution in REDISTRIBUTABLE
        reason = None
        if not permitted:
            reason = f"redistribution class {redistribution or 'unknown'!r} is not exportable"
        if not licence:
            missing_licence.append(source_id)
            reason = "no licence recorded; export fails closed"
            permitted = False
        if not permitted:
            restricted.append(source_id)
            reasons.append(f"{source_id}: {reason}")
        sources.append(
            {
                "source_id": source_id,
                "name": row["name"],
                "licence": row["licence"],
                "redistribution": row["redistribution"],
                "kind": row["kind"],
                "registered": True,
                "export_allowed": permitted,
                "reason": reason,
            }
        )
    return {
        "export_allowed": bool(unique) and not restricted,
        "sources": sources,
        "restricted_sources": restricted,
        "unregistered_sources": unregistered,
        "missing_licence_sources": missing_licence,
        "reasons": reasons,
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
    citations: Sequence[Mapping[str, Any]] = (),
    alternatives: Sequence[Mapping[str, Any]] = (),
    counterevidence: Sequence[Mapping[str, Any]] = (),
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
            "citations": [dict(citation) for citation in citations],
            "alternatives": [dict(alternative) for alternative in alternatives],
            "counterevidence": [dict(entry) for entry in counterevidence],
            "inputs": dict(inputs or {}),
        },
        "limitations": list(limitations),
    }
    payload["hypothesis_id"] = "HYP-" + _sha256(payload)[:16]
    return payload


def _publication_sentence(event: Mapping[str, Any]) -> str:
    publication = event.get("publication") or {}
    when = event.get("availability_time")
    precision = event.get("availability_precision")
    local = publication.get("local_time")
    zone = publication.get("timezone")
    phase = publication.get("phase")
    tradable = publication.get("tradable_session")
    pieces = [f"published {when}"]
    if precision == "date":
        pieces.append("(date-precision availability, pinned to end-of-day UTC)")
    if local and local != when:
        pieces.append(f"which is {local} in {zone}")
    if phase and phase != "unknown":
        pieces.append(f"during {phase.replace('_', ' ')}")
    if tradable:
        pieces.append(f"with {tradable} the first tradable stored session")
    return ", ".join(pieces)


def _document_citations(
    event: Mapping[str, Any], *, item: Mapping[str, Any] | None = None, limit: int = 2
) -> list[dict[str, Any]]:
    """Citations to exact stored spans, preferring the passage for this item."""
    document = event.get("document") or {}
    passages = list(event.get("passages") or [])
    if item is not None and item.get("section_path"):
        matching = [p for p in passages if p.get("section_path") == item["section_path"]]
        passages = matching or passages
    return [fe.citation_for(document, passage) for passage in passages[:limit]]


def _novelty_sentence(event: Mapping[str, Any], item_code: str) -> str | None:
    novelty = event.get("novelty") or {}
    if not novelty:
        return None
    if item_code in (novelty.get("repeated_items") or []):
        prior = [
            entry["accession"]
            for entry in novelty.get("prior_documents", [])
            if item_code in (entry.get("items") or [])
        ]
        return (
            " The same item appeared in previously archived filing(s) "
            f"{', '.join(prior[:3])}, so this is a repeat disclosure in the archived record."
        )
    if item_code in (novelty.get("first_disclosure_items") or []):
        if novelty.get("basis") == "archived_prior_filings":
            return (
                " It does not appear in the issuer's previously archived filings held here, "
                "so it is a new item in the archived record (not necessarily in the world)."
            )
        return " No earlier filing for this issuer is archived, so Atlas cannot assess novelty."
    return None


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
    requested_basis = request.price_basis
    return_convention = "interval_close_to_close"
    calculation_points = list(points)
    start_observation = points[0]
    end_observation = points[-1]
    if len(points) == 1:
        # A one-candle selection is a one-session move only if the immediately preceding
        # eligible session is known. Otherwise the return is refused with a reason rather
        # than assuming an unchanged prior close.
        if resolved.previous_point is not None:
            return_convention = "single_session_close_to_close"
            calculation_points = [resolved.previous_point, points[0]]
            start_observation = resolved.previous_point
            warnings.append(
                _warning(
                    W_SINGLE_SESSION_PREVIOUS,
                    "a one-candle selection measures the move from the previous eligible "
                    "session's close to the selected session's close",
                    previous_session=resolved.previous_point.session_date,
                    selected_session=points[0].session_date,
                )
            )
        else:
            return_convention = "unavailable"
            warnings.append(
                _warning(
                    W_SINGLE_SESSION_UNAVAILABLE,
                    "the selected interval has one session and Atlas holds no previous "
                    "eligible session for this listing's stored series; no return is "
                    "computed rather than assuming a flat prior close",
                    selected_session=points[0].session_date,
                )
            )
    calculation_bars = [point.to_bar() for point in calculation_points]
    bases: dict[str, list[Decimal]] = {
        basis: _basis_closes(calculation_bars, resolved.actions, basis)
        for basis in evidence.RETURN_BASES
    }
    returns: dict[str, float | None] = {
        basis: (_compound(closes) if return_convention != "unavailable" else None)
        for basis, closes in bases.items()
    }
    chosen = bases[requested_basis] if return_convention != "unavailable" else []
    chosen_returns = [value for _, value in _daily_returns(chosen)] if chosen else []

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

    start_close = chosen[0] if chosen else None
    end_close = chosen[-1] if chosen else None
    volatility = _stdev(chosen_returns) if chosen_returns else None

    # --- overnight versus intraday (split-adjusted opens) -----------------------
    adjusted = split_adjust(calculation_bars, resolved.actions, include_dividends=False)
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
    context = resolved.context
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
        "calculation_sessions": len(calculation_points),
        "return_convention": return_convention,
        "calendar_days": (parse_date(end) - parse_date(start)).days + 1,
        "start_price": float(start_close) if start_close is not None else None,
        "end_price": float(end_close) if end_close is not None else None,
        "absolute_change": (
            float(end_close - start_close)
            if start_close is not None and end_close is not None
            else None
        ),
        "interval_return": returns[requested_basis],
        "start_observation_id": start_observation.observation_id,
        "end_observation_id": end_observation.observation_id,
        "start_revision_seq": start_observation.revision_seq,
        "end_revision_seq": end_observation.revision_seq,
        "daily_volatility": volatility,
        "annualized_volatility": volatility * math.sqrt(252) if volatility is not None else None,
        "annualization": "sample standard deviation of daily returns x sqrt(252)" if volatility is not None else None,
        "max_drawdown": _max_drawdown(chosen),
        "best_session": _extreme_session(calculation_points, chosen, best=True),
        "worst_session": _extreme_session(calculation_points, chosen, best=False),
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
    benchmark, market_model, model_manifest = _benchmark_block(
        db,
        request=request,
        resolved=resolved,
        warnings=warnings,
    )
    peers, peer_manifest = _peer_block(
        db, request=request, resolved=resolved, warnings=warnings
    )

    # --- evidence --------------------------------------------------------------
    stored_sessions = sorted(
        {point.session_date for point in points} | {point.session_date for point in context.points}
    )
    filing_items, filing_coverage, filing_duplicates = _filing_events(
        db,
        issuer_id=resolved.security["issuer_id"],
        start=start,
        end=end,
        mode=request.mode,
        cutoff=cutoff,
        limit=request.evidence_limit,
        timezone=request.timezone,
        mic=resolved.mic,
        stored_sessions=stored_sessions,
    )
    action_items, action_coverage = _action_events(
        resolved.actions, start=start, end=end, mode=request.mode, cutoff=cutoff
    )
    # The cutoff filter runs inside ActionStore, so exclusions it made are merged into the
    # coverage rather than reported as zero.
    action_coverage["excluded_unknown_availability"] += (
        resolved.action_exclusions.get("excluded_unknown_availability", 0)
    )
    action_coverage["excluded_after_cutoff"] += (
        resolved.action_exclusions.get("excluded_after_cutoff", 0)
    )
    # Chronological order is the evidenced publication instant. A corporate action with
    # date-only availability is placed at the end of that day, conservatively.
    events = sorted(
        filing_items + action_items,
        key=lambda item: (
            item.get("availability_time") or f"{item['date']}T23:59:59Z",
            item["event_id"],
        ),
    )
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
    post_close_events = [
        item for item in events if item.get("relation") == "subsequent_to_price_window"
    ]
    if post_close_events:
        warnings.append(
            _warning(
                W_AFTER_FINAL_CLOSE,
                "some filings were published after the final selected session's close; "
                "their first eligible trading session is outside the selected interval, so "
                "they are visible as subsequent evidence and are not ranked as explanations "
                "of that close",
                count=len(post_close_events),
                final_session=end,
                final_session_close=filing_coverage.get("final_session_close"),
                event_ids=[item["event_id"] for item in post_close_events],
            )
        )
    if filing_coverage.get("publications_with_modelled_availability"):
        warnings.append(
            _warning(
                W_MODELLED_FILING_AVAILABILITY,
                "some cited documents have no observed public-release instant; their "
                "availability is a modelled upper bound derived from EDGAR acceptance plus "
                "a fixed publication lag, so they are quoted as evidence that was public by "
                "that bound and not as an exact release time",
                count=filing_coverage["publications_with_modelled_availability"],
                availability_policy=AVAILABILITY_POLICY,
            )
        )
    if filing_coverage["excluded_unknown_availability"]:
        warnings.append(
            _warning(
                W_UNKNOWN_FILING_AVAILABILITY,
                "filings with no evidenced publication time are excluded from the timeline "
                "and the ranking; a calendar date was not invented for them",
                count=filing_coverage["excluded_unknown_availability"],
            )
        )
    documents_not_ingested = filing_coverage["documents"].get(fe.DOC_NOT_INGESTED, 0)
    if documents_not_ingested:
        warnings.append(
            _warning(
                W_DOCUMENT_NOT_INGESTED,
                "some filing primary documents are not archived in this deployment; Atlas "
                "shows their original SEC locator and form but does not claim what they say",
                count=documents_not_ingested,
            )
        )
    documents_excluded_at_cutoff = filing_coverage["documents"].get(fe.DOC_NOT_AT_CUTOFF, 0)
    if documents_excluded_at_cutoff:
        warnings.append(
            _warning(
                W_DOCUMENT_NOT_AT_CUTOFF,
                "some archived documents were published after the information cutoff and are "
                "neither quoted nor used as contemporaneous evidence",
                count=documents_excluded_at_cutoff,
            )
        )
    if filing_coverage["publications_with_local_date_shift"]:
        warnings.append(
            _warning(
                W_TIMEZONE_SHIFT,
                "some publications fall on a different calendar date in the display "
                "timezone than in UTC; ordering uses the UTC instant, and the local date "
                "is reported alongside it",
                count=filing_coverage["publications_with_local_date_shift"],
                timezone=request.timezone,
            )
        )
    if filing_duplicates:
        warnings.append(
            _warning(
                W_EVENT_DUPLICATE,
                "duplicate events were suppressed rather than counted twice",
                count=len(filing_duplicates),
                duplicates=filing_duplicates,
            )
        )
    restricted_documents = [
        item["event_id"]
        for item in events
        if (item.get("document") or {}).get("rights")
        and not item["document"]["rights"]["redistributable"]
    ]
    if restricted_documents:
        warnings.append(
            _warning(
                W_DOCUMENT_RESTRICTED,
                "a resolved document's redistribution class does not permit its text to "
                "travel in an export; the locator, hash and span identifiers are kept and "
                "the excerpt is withheld",
                count=len(restricted_documents),
                event_ids=restricted_documents,
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
    if action_coverage["excluded_unknown_availability"] or action_coverage["unknown_availability"]:
        warnings.append(
            _warning(
                W_UNKNOWN_AVAILABILITY,
                "corporate actions with no recorded publication time are excluded from the "
                "historical reconstruction and are never placed inside the window; in "
                "retrospective mode they are shown with relation unknown_availability",
                excluded_count=action_coverage["excluded_unknown_availability"],
                shown_but_unplaced=action_coverage["unknown_availability"],
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
        "original_documents": {
            "status": (
                "available"
                if filing_coverage["documents"].get(fe.DOC_RESOLVED, 0)
                else "unavailable"
            ),
            "basis": "archived primary documents via the Financial Knowledge Engine",
            "excerpts_only_from_stored_bytes": True,
            "locators_without_bytes_are_not_quoted": True,
        },
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
        post_close_events=post_close_events,
    )

    price_vintage = {
        "status": "unverified",
        "verified_at_cutoff": False,
        "vintage_kind": "market_session_date",
        "provider_publication_vintage": None,
        "reason": (
            "Atlas stores the latest revision of each session, not the provider's publication "
            "history, so a historical reconstruction cannot prove these prices were available "
            "at the requested cutoff"
        ),
    }
    date_only = [
        item
        for item in events
        if item.get("availability_precision") == "date"
        and item.get("relation") in ("in_window", "after_window", "subsequent")
    ]
    if date_only:
        warnings.append(
            _warning(
                W_DATE_PRECISION,
                "evidence with date-only availability is pinned to the end of that UTC "
                "day under the Temporal Evidence Kernel policy, never to its first "
                "second; intraday ordering within that date is unknown",
                count=len(date_only),
                availability_policy=AVAILABILITY_POLICY,
            )
        )
    if request.mode == MODE_HISTORICAL:
        warnings.append(
            _warning(
                W_VINTAGE_AT_CUTOFF,
                "prices are filtered by session date, not by the provider's publication "
                "vintage; this reconstruction does not claim the vendor had published these "
                "values by the cutoff",
                cutoff=cutoff,
                price_vintage_status=price_vintage["status"],
            )
        )

    # Every source that contributed a value, an adjustment, a peer or an event is in the
    # rights decision. A source that is not registered fails closed rather than defaulting
    # to redistributable.
    contributing_sources: set[str] = {point.source_id for point in points}
    contributing_sources.update(point.source_id for point in context.points)
    contributing_sources.update(
        item["source_id"] for item in events if item.get("source_id")
    )
    contributing_sources.update(
        action.source_id for action in resolved.actions if action.source_id
    )
    if benchmark.get("source_id"):
        contributing_sources.add(benchmark["source_id"])
    for entry in (model_manifest.get("benchmark") or {}).get("window_points", []):
        if entry.get("source_id"):
            contributing_sources.add(entry["source_id"])
    for entry in (model_manifest.get("benchmark") or {}).get("estimation_points", []):
        if entry.get("source_id"):
            contributing_sources.add(entry["source_id"])
    contributing_sources.update(
        peer["source_id"] for peer in peers if peer.get("source_id")
    )
    rights = _source_rights(db, sorted(contributing_sources))
    if rights["unregistered_sources"]:
        warnings.append(
            _warning(
                W_UNKNOWN_SOURCE,
                "a contributing source is not registered, so its values are treated as "
                "restricted and the export fails closed",
                unregistered_sources=rights["unregistered_sources"],
            )
        )
    if rights["missing_licence_sources"]:
        warnings.append(
            _warning(
                W_MISSING_LICENCE,
                "a contributing source has no recorded licence, so the export fails closed",
                sources=rights["missing_licence_sources"],
            )
        )
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
        "calculation": {
            "version": CALCULATION_VERSION,
            "market_model_version": MARKET_MODEL_VERSION,
            "return_convention": return_convention,
            "requested_basis": request.price_basis,
            "annualization_sessions": ANNUALIZATION_SESSIONS,
            "min_benchmark_coverage": MIN_BENCHMARK_COVERAGE,
            "estimation_sessions": request.estimation_sessions,
            "evidence_limit": request.evidence_limit,
        },
        "request": _normalised_request(request, resolved),
        "selected_series": {
            "source_id": resolved.series.source_id,
            "policy": resolved.series.policy,
            "points": _point_manifest(calculation_points),
        },
        "context_series": {
            "source_id": context.source_id,
            "policy": context.policy,
            "missing_status": context.missing_status,
            "points": _point_manifest(context.points),
        },
        "benchmark": model_manifest.get("benchmark"),
        "market_model": model_manifest.get("market_model"),
        "peers": peer_manifest.get("peers"),
        "corporate_actions": [
            {
                "action_id": action.action_id,
                "source_id": action.source_id,
                "action_type": action.action_type,
                "status": action.status,
                "ex_date": action.ex_date,
                "effective_date": action.effective_date,
                "availability_time": action.availability_time,
                "availability_precision": action.availability_precision,
                "observed_at": action.observed_at,
                "supersedes": action.supersedes,
            }
            for action in resolved.actions
        ],
        "events": [
            {
                "event_id": item["event_id"],
                "kind": item.get("kind"),
                "date": item.get("date"),
                "filed_date": item.get("filed_date"),
                "publication_date": item.get("publication_date", item.get("date")),
                "publication_local_time": (item.get("publication") or {}).get("local_time"),
                "relation": item.get("relation"),
                "source_id": item.get("source_id"),
                "availability_time": item.get("availability_time"),
                "availability_precision": item.get("availability_precision"),
                "availability_basis": item.get("availability_basis"),
                "document": (
                    {
                        "status": (item.get("document") or {}).get("status"),
                        "document_id": (item.get("document") or {}).get("document_id"),
                        "sha256": (item.get("document") or {}).get("sha256"),
                        "availability_time": (item.get("document") or {}).get("availability_time"),
                    }
                    if item.get("document")
                    else None
                ),
                "disclosed_items": [entry["item"] for entry in item.get("disclosed_items") or []],
                "passage_spans": [
                    {
                        "unit_id": passage["unit_id"],
                        "section_path": passage["section_path"],
                        "char_start": passage["char_start"],
                        "char_end": passage["char_end"],
                        "sha256": passage["sha256"],
                    }
                    for passage in item.get("passages") or []
                ],
                "source_url": item.get("source_url"),
            }
            for item in events
        ],
        "sources": rights["sources"],
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
            "start_observation": start_observation.identity(),
            "end_observation": end_observation.identity(),
            "return_convention": return_convention,
            "price_vintage": price_vintage,
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
            "availability_policy": AVAILABILITY_POLICY,
            "chronological_order": "evidenced publication instant (UTC), not filing date",
        },
        "observations": observations,
        "hypotheses": hypotheses,
        "analysis": {
            "narrative": "deterministic_templates_over_observed_evidence",
            "ai_used": False,
            "epistemic_classes": {
                "observed": "values, timestamps, document spans and item codes read from stored records",
                "inferred": "relevance ranking and mechanical basis reconciliation",
                "unresolved": "causal attribution; every hypothesis is not_identified",
            },
            "note": (
                "no language model contributed text to this response, so no unsupported "
                "narrative can be introduced; a future AI layer must keep these classes apart"
            ),
        },
        "revision_check": revision_check,
        "rights": rights,
        "warnings": warnings,
        "refusals": (
            [
                {
                    "code": "return_unavailable",
                    "reason": "single session with no previous eligible session",
                    "detail": (
                        "Atlas will not assume an unchanged prior close. Select a range that "
                        "includes the previous session, or start after the listing's first "
                        "stored session."
                    ),
                }
            ]
            if return_convention == "unavailable"
            else []
        ),
        "reproducibility": reproducibility,
        "limitations": [
            "daily observations only; Atlas stores no intraday bars",
            "a statistical residual is not a proven issuer-specific cause",
            "no news, consensus or macro-release source is licensed here, so the event "
            "timeline is incomplete by construction",
            "the provider's past vintage is not archived; a session's stored revision may "
            "have been published after that session",
            (
                "in historical mode the price series is filtered by session date, not by "
                "the provider's publication vintage; the response labels that vintage "
                "unverified rather than implying it was available at the cutoff"
            ),
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
        "evidence_limit": request.evidence_limit,
        "return_convention": request.return_convention,
    }


def _point_manifest(points: Sequence[evidence.MarketObservation]) -> list[dict[str, Any]]:
    return [
        {
            "observation_id": point.observation_id,
            "session": point.session_date,
            "revision_seq": point.revision_seq,
            "content_hash": point.content_hash,
            "source_id": point.source_id,
        }
        for point in points
    ]


def _benchmark_block(
    db: Database,
    *,
    request: ExplanationRequest,
    resolved: _Resolved,
    warnings: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
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
        return unavailable, empty_model, {"benchmark": None, "market_model": None}
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
        return unavailable, empty_model, {"benchmark": None, "market_model": None}

    try:
        benchmark_mic = _primary_mic(db, master, request.benchmark_security_id)
    except ValidationError:
        unavailable["reason"] = "benchmark has no listing"
        empty_model["reason"] = "benchmark has no listing"
        return unavailable, empty_model, {"benchmark": None, "market_model": None}

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
        return unavailable, empty_model, {"benchmark": None, "market_model": None}

    benchmark_currency = benchmark_series.points[-1].currency
    security_currency = resolved.points[0].currency
    manifest: dict[str, Any] = {"benchmark": None, "market_model": None}
    window_points = [
        point
        for point in benchmark_series.points
        if resolved.start_session <= point.session_date <= resolved.end_session
    ]
    benchmark_by_date = {point.session_date: point for point in window_points}
    security_by_date = {point.session_date: point for point in resolved.points}
    common_window = sorted(set(benchmark_by_date) & set(security_by_date))
    coverage = len(common_window) / len(resolved.points) if resolved.points else 0.0

    # A benchmark with no comparable observations is reported as unavailable. Atlas does
    # not invent a 0.0 return for it, and does not label it "available".
    if len(window_points) < 2:
        warnings.append(
            _warning(
                W_BENCHMARK_EMPTY,
                "the benchmark has fewer than two stored observations inside the interval; "
                "no benchmark return, excess return or beta is claimed",
                benchmark_security_id=request.benchmark_security_id,
                sessions=len(window_points),
            )
        )
        unavailable.update(
            {
                "reason": "fewer than two benchmark observations inside the interval",
                "sessions": len(window_points),
                "source_id": benchmark_series.source_id,
                "currency": benchmark_currency,
            }
        )
        return (
            unavailable,
            {"status": "unavailable", "reason": unavailable["reason"], "sessions": len(window_points)},
            manifest,
        )
    if len(common_window) < 2:
        warnings.append(
            _warning(
                W_BENCHMARK_ALIGNMENT,
                "the benchmark and the security share fewer than two sessions in the "
                "interval; no relative statistic is claimed",
                aligned_sessions=len(common_window),
            )
        )
        unavailable.update(
            {
                "status": "insufficient_alignment",
                "reason": "fewer than two aligned sessions",
                "sessions": len(window_points),
                "aligned_sessions": len(common_window),
                "source_id": benchmark_series.source_id,
                "currency": benchmark_currency,
            }
        )
        return unavailable, {"status": "unavailable", "reason": unavailable["reason"], "aligned_sessions": len(common_window)}, manifest
    if coverage < MIN_BENCHMARK_COVERAGE:
        warnings.append(
            _warning(
                W_BENCHMARK_ALIGNMENT,
                "the benchmark covers too little of the selected interval to support a "
                "relative claim",
                aligned_sessions=len(common_window),
                security_sessions=len(resolved.points),
                coverage_ratio=coverage,
                required_coverage=MIN_BENCHMARK_COVERAGE,
            )
        )
        unavailable.update(
            {
                "status": "insufficient_alignment",
                "reason": "benchmark coverage of the interval is below the declared minimum",
                "aligned_sessions": len(common_window),
                "security_sessions": len(resolved.points),
                "coverage_ratio": coverage,
                "required_coverage": MIN_BENCHMARK_COVERAGE,
                "source_id": benchmark_series.source_id,
                "currency": benchmark_currency,
            }
        )
        return unavailable, {
            "status": "unavailable",
            "reason": unavailable["reason"],
            "aligned_sessions": len(common_window),
            "coverage_ratio": coverage,
        }, manifest

    security_aligned = [security_by_date[day] for day in common_window]
    benchmark_aligned = [benchmark_by_date[day] for day in common_window]
    security_closes_window = _basis_closes(
        [point.to_bar() for point in security_aligned], resolved.actions, request.price_basis
    )
    benchmark_closes_window = _basis_closes(
        [point.to_bar() for point in benchmark_aligned], benchmark_actions, request.price_basis
    )
    benchmark_return = _compound(benchmark_closes_window)
    security_window_return = _compound(security_closes_window)
    manifest["benchmark"] = {
        "security_id": request.benchmark_security_id,
        "mic": benchmark_mic,
        "source_id": benchmark_series.source_id,
        "currency": benchmark_currency,
        "window_points": _point_manifest(benchmark_aligned),
        "estimation_points": [],
    }
    benchmark_block = {
        "status": "available",
        "security_id": request.benchmark_security_id,
        "ticker": _ticker(db, request.benchmark_security_id, as_of=resolved.end_session),
        "mic": benchmark_mic,
        "source_id": benchmark_series.source_id,
        "currency": benchmark_currency,
        "sessions": len(common_window),
        "benchmark_sessions": len(window_points),
        "security_sessions": len(resolved.points),
        "aligned_sessions": len(common_window),
        "unaligned_sessions": len(resolved.points) - len(common_window),
        "coverage_ratio": coverage,
        "required_coverage": MIN_BENCHMARK_COVERAGE,
        "first_session": common_window[0],
        "last_session": common_window[-1],
        "return": benchmark_return,
        "security_return_aligned": security_window_return,
        "basis": request.price_basis,
        "basis_label": evidence.RETURN_LABELS[request.price_basis],
        "comparable": True,
        "reason": None,
        "note": (
            "the benchmark return, excess return and market-model window are computed on "
            "the sessions the two series share, so both sides describe the same days"
        ),
    }

    # Alignment for the market model: intersection of observed sessions, strictly before
    # the event window, so no in-window return estimates the model that scores it.
    security_context = resolved.context
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
        benchmark_block.update(
            {
                "status": "unavailable",
                "comparable": False,
                "return": None,
                "security_return_aligned": None,
                "reason": "currency mismatch between security and benchmark",
            }
        )
        return benchmark_block, {
            "status": "unavailable",
            "reason": "currency mismatch between security and benchmark",
        }, manifest

    excess = security_window_return - benchmark_return
    benchmark_block["excess_return_arithmetic"] = excess
    benchmark_block["excess_note"] = (
        "difference between the two aligned interval returns; not a compounded attribution"
    )

    if usable < MIN_MARKET_MODEL_SESSIONS:
        warnings.append(
            _warning(
                W_ESTIMATION_SHORT,
                "too few aligned pre-interval sessions estimate the market model; no beta or "
                "abnormal return is claimed",
                aligned_sessions=usable,
                required=MIN_MARKET_MODEL_SESSIONS,
            )
        )
        return benchmark_block, {
            "status": "unavailable",
            "reason": "insufficient aligned sessions before the interval",
            "aligned_sessions": usable,
        }, manifest

    fit = _ols(y, x)
    if fit is None:
        return benchmark_block, {
            "status": "unavailable",
            "reason": "benchmark returns have no variance in the estimation window",
            "aligned_sessions": usable,
        }, manifest
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

    # Cumulative attribution: compound the model's own daily expected return over the
    # aligned window instead of multiplying beta by one compounded benchmark return. The
    # latter is a first-order approximation whose cross terms do not vanish; it is reported
    # only inside `first_order_approximation` and is never the headline residual.
    benchmark_window_daily = [value for _, value in _daily_returns(benchmark_closes_window)]
    expected_level = 1.0
    for benchmark_daily in benchmark_window_daily:
        expected_daily = fit["alpha_daily"] + fit["beta"] * benchmark_daily
        if expected_daily <= -1:
            expected_level = 0.0
            break
        expected_level *= 1 + expected_daily
    expected_return = expected_level - 1
    abnormal_difference = security_window_return - expected_return
    abnormal_ratio = (
        (1 + security_window_return) / (1 + expected_return) - 1
        if expected_return > -1
        else None
    )
    manifest["market_model"] = {
        "version": MARKET_MODEL_VERSION,
        "status": "available",
        "beta": fit["beta"],
        "alpha_daily": fit["alpha_daily"],
        "estimation_sessions": fit["observations"],
        "estimation_points": _point_manifest(aligned_security[-usable:]) if usable else [],
        "window_aligned_sessions": len(common_window),
    }
    if manifest["benchmark"] is not None:
        manifest["benchmark"]["estimation_points"] = _point_manifest(aligned_benchmark[-usable:])
    return benchmark_block, {
        "status": "available",
        "model": "single-factor market model (OLS on daily simple returns)",
        "version": MARKET_MODEL_VERSION,
        "basis": request.price_basis,
        "estimation": {
            "sessions": fit["observations"],
            "first_session": dates[0] if dates else None,
            "last_session": dates[-1] if dates else None,
            "window_rule": "aligned sessions strictly before the selected interval, "
            "most recent sessions up to estimation_sessions",
            "aligned_available": max(0, len(common) - 1),
            "interval_prices_used": False,
        },
        "window": {
            "aligned_sessions": len(common_window),
            "first_session": common_window[0],
            "last_session": common_window[-1],
            "coverage_ratio": coverage,
        },
        "alpha_daily": fit["alpha_daily"],
        "beta": fit["beta"],
        "r_squared": fit["r_squared"],
        "benchmark_return_aligned": benchmark_return,
        "security_return_aligned": security_window_return,
        "expected_return_compounded": expected_return,
        "abnormal_return_difference": abnormal_difference,
        "abnormal_return_ratio": abnormal_ratio,
        "attribution_convention": (
            "compound the model's daily expected return (alpha + beta x benchmark daily "
            "return) over the aligned window; abnormal return is reported both as an "
            "arithmetic difference and as a multiplicative ratio"
        ),
        "first_order_approximation": {
            "beta_times_benchmark": fit["beta"] * benchmark_return,
            "note": (
                "beta x compounded benchmark return is a first-order approximation; its "
                "cross terms do not vanish over multiple sessions and it is not the "
                "abnormal return"
            ),
        },
        "applicability": [
            "the coefficients describe co-movement in the estimation window, not a stable law",
            "the abnormal return is what this one-factor model does not explain; it is not "
            "evidence of an issuer-specific cause",
            "a beta estimated on one benchmark does not identify sector or style exposures",
            "estimation error in alpha and beta is not propagated into this point estimate",
        ],
    }, manifest


def _peer_block(
    db: Database,
    *,
    request: ExplanationRequest,
    resolved: _Resolved,
    warnings: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Window returns for an explicitly supplied peer universe.

    Each peer is measured on its own stored series over the same date bounds. No peer is
    silently substituted, and a different currency is reported as not comparable rather
    than converted without an FX convention.
    """
    if not request.peer_security_ids:
        return [], {"peers": []}
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
    peer_manifest: list[dict[str, Any]] = []
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
        peer_manifest.append(
            {
                "security_id": peer_id,
                "mic": mic,
                "source_id": series.source_id,
                "currency": peer_currency,
                "points": _point_manifest(series.points),
            }
        )
    return items, {"peers": peer_manifest}


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
    returns: Mapping[str, float | None],
    price_statistics: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    market_model: Mapping[str, Any],
    benchmark: Mapping[str, Any],
    volume_ratio: float | None,
    post_close_events: Sequence[Mapping[str, Any]] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate confirmed observations from competing, unproven explanations.

    Every explanatory claim that quotes a filing cites the exact document version and
    character span it came from. A filing whose bytes Atlas does not hold is described
    as a timing fact only: the form is named, the disclosed event is not.
    """
    total = returns[request.price_basis]
    convention = str(price_statistics.get("return_convention"))
    if total is None:
        return_statement = (
            f"No {request.price_basis} return is computed for {resolved.start_session}: "
            "the selection has one session and no previous eligible session is stored."
        )
        return_derivation = "refused: a prior eligible close is required and was not fabricated"
    elif convention == "single_session_close_to_close":
        return_statement = (
            f"The {request.price_basis} single-session change into {resolved.end_session} "
            f"from the previous eligible close is {total:.6f}."
        )
        return_derivation = (
            "selected session close / previous eligible session close - 1 on the declared basis"
        )
    else:
        return_statement = (
            f"The {request.price_basis} change from {resolved.start_session} to "
            f"{resolved.end_session} is {total:.6f}."
        )
        return_derivation = "last selected close / first selected close - 1 on the declared basis"
    observations: list[dict[str, Any]] = [
        {
            "observation_id": "OBS-interval-return",
            "statement": return_statement,
            "value": total,
            "unit": "ratio",
            "evidence": [
                resolved.points[0].observation_id,
                resolved.points[-1].observation_id,
            ],
            "derivation": return_derivation,
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
                    "Over the estimation window the security's daily returns had a beta of "
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
        observations.append(
            {
                "observation_id": "OBS-abnormal-return",
                "statement": (
                    "Compounding the model's daily expected return over the aligned window "
                    f"gives {market_model['expected_return_compounded']:.6f}; the security "
                    f"returned {market_model['security_return_aligned']:.6f}, leaving an "
                    f"abnormal return of {market_model['abnormal_return_difference']:.6f}."
                ),
                "value": market_model["abnormal_return_difference"],
                "unit": "ratio",
                "evidence": list(resolved.series.observation_ids()[-3:]),
                "derivation": market_model["attribution_convention"],
            }
        )

    hypotheses: list[dict[str, Any]] = []
    filing_events = [
        item for item in events if item["kind"] in ("sec_filing", "sec_filing_amendment")
    ]
    action_events = [item for item in events if item["kind"] == "corporate_action"]
    material_filings = [
        item for item in filing_events if str(item.get("form_type")) in MATERIAL_FORMS
    ]
    routine_filings = len(filing_events) - len(material_filings)
    disclosed = [item for item in material_filings if item.get("disclosed_items")]
    undisclosed_material = [item for item in material_filings if not item.get("disclosed_items")]

    alternatives_pool: list[dict[str, Any]] = []
    if market_model.get("status") == "available":
        alternatives_pool.append(
            {
                "kind": "market_co_movement",
                "statement": (
                    "Common market exposure could account for part of the move; the one-factor "
                    "model's compounded expected return is "
                    f"{market_model['expected_return_compounded']:.6f}."
                ),
                "evidence": list(resolved.series.observation_ids()[-3:]),
            }
        )
    if routine_filings:
        alternatives_pool.append(
            {
                "kind": "routine_filing",
                "statement": (
                    f"{routine_filings} routine administrative filing(s) are present; they are "
                    "shown in the timeline but are not treated as a repricing explanation."
                ),
                "evidence": [],
            }
        )
    alternatives_pool.append(
        {
            "kind": "unidentified_information",
            "statement": (
                "An unobserved information event (news, analyst action, sector flow) could have "
                "moved the price; Atlas holds no licensed news or consensus history to test it."
            ),
            "evidence": [],
        }
    )

    for event in disclosed:
        accession = event.get("accession_number")
        for item in event["disclosed_items"]:
            code = item["item"]
            citations = _document_citations(event, item=item)
            quoted = next((citation for citation in citations if citation.get("excerpt")), None)
            sentence = (
                f"Form {event.get('form_type')} Item {code} ({item['label']}) was disclosed in a "
                f"filing for this issuer {_publication_sentence(event)}."
            )
            if quoted is not None:
                sentence += (
                    f' The stored filing text at section "{quoted["section_path"]}" '
                    f'(chars {quoted["char_start"]}-{quoted["char_end"]}) reads: '
                    f'"{quoted["excerpt"]}".'
                )
            elif item.get("section_path"):
                sentence += (
                    f' The document records the item under section "{item["section_path"]}"; '
                    "its redistribution class does not permit quoting the text in this response."
                )
            novelty = _novelty_sentence(event, code)
            if novelty:
                sentence += novelty
            counter: list[dict[str, Any]] = []
            novelty_data = event.get("novelty") or {}
            if code in (novelty_data.get("repeated_items") or []):
                counter.append(
                    {
                        "kind": "repeat_disclosure",
                        "statement": (
                            "The item was already disclosed in an earlier archived filing, so a "
                            "novel-information interpretation is weaker."
                        ),
                        "prior_documents": [
                            entry["accession"]
                            for entry in novelty_data.get("prior_documents", [])
                            if code in (entry.get("items") or [])
                        ],
                    }
                )
            if market_model.get("status") == "available" and total:
                expected = float(market_model["expected_return_compounded"])
                if expected and abs(expected / float(total)) >= 0.5:
                    counter.append(
                        {
                            "kind": "market_co_movement",
                            "statement": (
                                "The compounded market-model expectation already accounts for at "
                                "least half of the move, so issuer-specific attribution is weaker."
                            ),
                            "evidence": list(resolved.series.observation_ids()[-3:]),
                        }
                    )
            hypotheses.append(
                _hypothesis(
                    statement=sentence,
                    tier=2,
                    basis=(
                        "the filing's archived primary document names this 8-K item and the "
                        "passage is citable to an exact span"
                    ),
                    supporting=[event["event_id"]],
                    citations=citations,
                    alternatives=alternatives_pool,
                    counterevidence=counter,
                    inputs={
                        "accession_number": accession,
                        "document_id": (event.get("document") or {}).get("document_id"),
                        "document_sha256": (event.get("document") or {}).get("sha256"),
                        "item": code,
                        "item_label": item.get("label"),
                        "publication_time": event.get("availability_time"),
                        "publication_precision": event.get("availability_precision"),
                        "tradable_session": (event.get("publication") or {}).get("tradable_session"),
                        "novelty": (event.get("novelty") or {}).get("basis"),
                        "quoted_span_id": quoted.get("unit_id") if quoted else None,
                    },
                    limitations=[
                        "the document reports the disclosed event; Atlas has not measured how "
                        "expectations changed",
                        "a disclosure inside the interval does not establish that it moved the price",
                        "no consensus, estimate-revision or news archive is licensed, so the "
                        "surprise component is unmeasured",
                    ],
                )
            )

    if undisclosed_material:
        forms = sorted({str(item["form_type"]) for item in undisclosed_material})
        citations = [
            citation
            for event in undisclosed_material
            for citation in _document_citations(event, limit=1)
        ]
        statuses = sorted(
            {
                str((event.get("document") or {}).get("status") or "unknown")
                for event in undisclosed_material
            }
        )
        hypotheses.append(
            _hypothesis(
                statement=(
                    "A material SEC disclosure was published inside the interval "
                    f"({', '.join(forms)}), but Atlas has not archived the filing's primary "
                    "document, so it cannot identify the disclosed event. The publication is a "
                    "timing fact, not an explanation. Document status: "
                    + ", ".join(statuses)
                    + "."
                ),
                tier=2,
                basis=(
                    "a material filing was published inside the interval, but no stored document "
                    "identifies the item disclosed"
                ),
                supporting=[item["event_id"] for item in undisclosed_material],
                citations=citations,
                alternatives=alternatives_pool,
                inputs={
                    "forms": forms,
                    "count": len(undisclosed_material),
                    "document_statuses": statuses,
                    "accessions": [
                        item.get("accession_number") for item in undisclosed_material
                    ],
                    "routine_filings_not_ranked": routine_filings,
                },
                limitations=[
                    "the form alone does not say what was disclosed",
                    "Atlas does not quote or paraphrase a document it has not retrieved",
                    "publication inside the interval does not establish that the filing moved the price",
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
                counterevidence=[
                    {
                        "kind": "basis_effect_only",
                        "statement": (
                            "The action explains a change of basis, not the economic direction of "
                            "the move; the split-adjusted and total-return figures are the check."
                        ),
                        "evidence": [],
                    }
                ],
                alternatives=alternatives_pool,
                inputs={
                    "raw_return": returns["price"],
                    "split_adjusted_return": returns["split_adjusted"],
                    "total_return": returns["total_return"],
                },
                limitations=[
                    "the action explains a basis change, not the economic direction of the move"
                ],
            )
        )

    if market_model.get("status") == "available" and total:
        expected = float(market_model["expected_return_compounded"])
        abnormal = float(market_model["abnormal_return_difference"])
        explained_share = expected / total
        if explained_share >= 0.5:
            statement = (
                "Most of the interval's change is consistent with benchmark co-movement: "
                f"compounding the model's daily expected return (alpha "
                f"{market_model['alpha_daily']:.6f}, beta {market_model['beta']:.3f}) over "
                f"the aligned window accounts for {expected:.4f} of the {total:.4f} move. "
                f"The remaining {abnormal:.4f} is the abnormal return this model does not "
                "explain."
            )
            basis = "the compounded expected return has at least half the magnitude of the move"
        else:
            statement = (
                "An abnormal component remains after market adjustment: of the "
                f"{total:.4f} move, the model's compounded expected return explains "
                f"{expected:.4f}, leaving an abnormal return of {abnormal:.4f}. A "
                "company-specific event is plausible but not identified."
            )
            basis = "the abnormal return is larger than the compounded expected return"
        hypotheses.append(
            _hypothesis(
                statement=statement,
                tier=3,
                basis=basis,
                supporting=list(resolved.series.observation_ids()[-3:]),
                counterevidence=[
                    {
                        "kind": "residual_is_not_a_cause",
                        "statement": (
                            "The abnormal return is what this one-factor model does not explain; "
                            "it is not evidence of a specific issuer event."
                        ),
                        "evidence": [],
                    }
                ],
                alternatives=alternatives_pool,
                inputs={
                    "beta": market_model["beta"],
                    "alpha_daily": market_model["alpha_daily"],
                    "benchmark_return_aligned": benchmark.get("return"),
                    "expected_return_compounded": expected,
                    "abnormal_return_difference": abnormal,
                    "abnormal_return_ratio": market_model["abnormal_return_ratio"],
                    "explained_share_of_total": explained_share,
                    "convention": market_model["attribution_convention"],
                },
                limitations=[
                    "one benchmark and one factor do not identify sector, style or idiosyncratic exposure",
                    "the abnormal return is not a cause; it is what the model does not explain",
                    "beta instability and estimation error are not propagated into this point estimate",
                    "the arithmetic difference and the ratio can disagree in sign when returns are large",
                ],
            )
        )

    if volume_ratio is not None and volume_ratio >= 2.0:
        hypotheses.append(
            _hypothesis(
                statement=(
                    f"Trading volume in the interval averaged {volume_ratio:.2f} times its "
                    "trailing median. Unusual participation is consistent with an "
                    "information-driven repricing, but volume does not identify the information."
                ),
                tier=4,
                basis="mean window volume is at least twice the trailing median",
                supporting=list(resolved.series.observation_ids()[-3:]),
                counterevidence=[
                    {
                        "kind": "descriptive_only",
                        "statement": (
                            "Volume is descriptive: index rebalancing, option expiry and liquidity "
                            "events also raise it."
                        ),
                        "evidence": [],
                    }
                ],
                alternatives=alternatives_pool,
                inputs={"average_to_trailing_median": volume_ratio},
                limitations=[
                    "volume can rise for index rebalancing, option expiry or liquidity reasons",
                    "no order-book or participant data is stored",
                ],
            )
        )

    if not disclosed and not mechanical:
        statement = (
            "No material company-specific SEC disclosure or corporate action inside this "
            "interval is stored. Atlas cannot explain the move from its sources and abstains "
            "rather than inferring a cause."
        )
        if post_close_events:
            count = len(post_close_events)
            subject = "1 SEC filing was" if count == 1 else f"{count} SEC filings were"
            statement = (
                f"{subject} published inside the calendar interval but after the final "
                "selected session's close. The first eligible trading session is later, so "
                "the filing is visible as subsequent evidence and is not a candidate "
                "explanation of this close. Atlas abstains from attributing the move to it."
                if count == 1
                else f"{subject} published inside the calendar interval but after the final "
                "selected session's close. Their first eligible trading session is later, so "
                "they are visible as subsequent evidence and are not candidate explanations "
                "of this close. Atlas abstains from attributing the move to them."
            )
        elif undisclosed_material:
            statement = (
                "A material filing was published inside this interval, but no archived primary "
                "document identifies what it disclosed. Atlas abstains from explaining the move "
                "rather than treating the filing itself as the explanation."
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
                basis="no material in-window disclosure with an archived document, and no corporate action, is present in the store",
                supporting=[],
                alternatives=alternatives_pool,
                inputs={
                    "routine_filings_not_ranked": routine_filings,
                    "undocumented_material_filings": len(undisclosed_material),
                    "post_close_filings_not_ranked": len(post_close_events),
                },
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
        "CALCULATION_VERSION",
        "MARKET_MODEL_VERSION",
        "RETURN_CONVENTIONS",
        "ExplanationRequest",
    "explain_range",
]
