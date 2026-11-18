"""Build the vintage dataset for the real-world revision study.

Every number in the study comes from a real-time vintage served by ALFRED. This module fetches one
vintage of one series at a time, caches the response with its SHA-256, and derives *events*: an
observation period, the vintage that first printed it, and the vintage four quarters (or twelve
months) later. Nothing here estimates a model or makes a decision; it only records what was published
and when, so that the decision study can be reproduced from the archive without refetching.

Run: ``.venv/bin/python scripts/research/rtds_build.py``
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "rtds_cache"
OUT = ROOT / "artifacts" / "research" / "rtds"

ALFRED_CSV = "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={series}&vintage_date={date}"
ALFRED_VINTAGES = "https://alfred.stlouisfed.org/series/downloaddata?seid={series}"

COHORTS: dict[str, dict[str, Any]] = {
    "A": {
        "name": "BEA quarterly expenditure components",
        "frequency": "quarterly",
        # PCEC1 (real personal consumption) has no ALFRED vintage archive: its download page
        # returns 404, so the cohort uses the four real expenditure aggregates that do. Recorded as
        # an accessibility limitation, not a modelling choice.
        "series": ["GDPC1", "GPDIC1", "GCEC1", "EXPGSC1"],
        "labels": ["total", "investment", "government", "exports"],
        "horizon_days": 400,
        "step_months": 3,
        "source": "BEA via ALFRED/FRED (Federal Reserve Bank of St. Louis)",
    },
    "B": {
        "name": "BLS monthly payroll employment",
        "frequency": "monthly",
        "series": ["PAYEMS", "MANEMP", "USCONS"],
        "labels": ["total", "manufacturing", "construction"],
        "horizon_days": 366,
        "step_months": 1,
        "source": "BLS via ALFRED/FRED (Federal Reserve Bank of St. Louis)",
    },
}

#: Fetch window. The data reach back further, but the study's training split starts in 2000.
WINDOW = (date(1999, 1, 1), date(2026, 12, 31))

TRAIN = (date(2000, 1, 1), date(2012, 12, 31))
PILOT = (date(2013, 1, 1), date(2014, 12, 31))
TEST = (date(2015, 1, 1), date(2024, 6, 30))


def _curl(url: str, timeout: int = 45, attempts: int = 4) -> bytes:
    # ALFRED's edge intermittently drops HTTP/2 streams; HTTP/1.1 with a bounded retry loop is the
    # difference between a reproducible fetch and a flaky one.
    last = ""
    for attempt in range(attempts):
        # No custom User-Agent: ALFRED's edge stalls on anything but curl's default string (a
        # browser string hangs too), so the fetch keeps the default and records the URL it used.
        result = subprocess.run(
            ["curl", "-sS", "--http1.1", "--max-time", str(timeout), "--retry", "1", url],
            capture_output=True, check=False,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
        last = (result.stderr.decode("utf-8", "replace")[:200]
                or f"empty response (rc={result.returncode})")
        # ALFRED answers an empty 200 when it throttles, so the wait has to grow: a fixed half
        # second simply spends the retries inside the same window.
        time.sleep(3.0 * (attempt + 1))
    raise RuntimeError(f"fetch failed after {attempts} attempts for {url}: {last!r}")


def _cached(url: str, path: Path, *, refresh: bool = False) -> tuple[bytes, bool]:
    if path.exists() and not refresh:
        return path.read_bytes(), True
    payload = _curl(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload, False


def vintage_dates(series: str) -> list[date]:
    """Release dates ALFRED records for one series, ascending."""

    path = CACHE / series / "vintages.html"
    payload, _cached_hit = _cached(ALFRED_VINTAGES.format(series=series), path)
    text = payload.decode("utf-8", "replace")
    import re

    found = {
        date.fromisoformat(value)
        for value in re.findall(r"(?:19|20)\d{2}-\d{2}-\d{2}", text)
    }
    return sorted(d for d in found if WINDOW[0] <= d <= WINDOW[1])


def parse_vintage_csv(text: str) -> dict[str, float]:
    """``observation_date,value`` rows; missing values are ``.``/empty and are dropped."""

    rows: dict[str, float] = {}
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        period, raw = parts[0].strip(), parts[1].strip()
        if not period or not raw or raw in {".", "NaN", "null"}:
            continue
        try:
            rows[period] = float(raw)
        except ValueError:
            continue
    return rows


@dataclass(frozen=True, slots=True)
class Fetch:
    series: str
    vintage: str
    url: str
    sha256: str
    bytes: int
    periods: int
    cached: bool


def _fetch_one(series: str, stamp: date, refresh: bool) -> Fetch:
    url = ALFRED_CSV.format(series=series, date=stamp.isoformat())
    path = CACHE / series / f"{stamp.isoformat()}.csv"
    payload, hit = _cached(url, path, refresh=refresh)
    text = payload.decode("utf-8", "replace")
    if text.lstrip().lower().startswith("<!doctype") or "observation_date" not in text:
        raise RuntimeError(f"unexpected payload for {series} {stamp}: {text[:120]!r}")
    return Fetch(series, stamp.isoformat(), url, hashlib.sha256(payload).hexdigest(),
                 len(payload), len(parse_vintage_csv(text)), hit)


def fetch_series(series: str, dates: Sequence[date], *, refresh: bool = False,
                 workers: int = 8) -> tuple[dict[date, dict[str, float]], list[Fetch]]:
    """Fetch every vintage of one series, eight at a time, caching each response by date."""

    from concurrent.futures import ThreadPoolExecutor

    def one(stamp: date) -> Fetch:
        # A small stagger keeps a burst of forty requests from being read as a scrape.
        time.sleep(0.15)
        return _fetch_one(series, stamp, refresh)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        manifest = list(pool.map(one, dates))
    panel: dict[date, dict[str, float]] = {}
    for item in manifest:
        path = CACHE / series / f"{item.vintage}.csv"
        panel[date.fromisoformat(item.vintage)] = parse_vintage_csv(
            path.read_text(encoding="utf-8", errors="replace"))
    return panel, manifest


def period_key(period: str) -> tuple[int, int] | None:
    try:
        year, month, *_ = period.split("-")
        return int(year), int(month)
    except (AttributeError, ValueError):
        return None


def shift(period: str, steps: int) -> str | None:
    key = period_key(period)
    if key is None:
        return None
    year, month = key
    total = year * 12 + (month - 1) + steps
    return f"{total // 12:04d}-{total % 12 + 1:02d}-01"


def split_of(clock: date) -> str:
    if TRAIN[0] <= clock <= TRAIN[1]:
        return "train"
    if PILOT[0] <= clock <= PILOT[1]:
        return "pilot"
    if TEST[0] <= clock <= TEST[1]:
        return "test"
    return "out_of_window"


def build_cohort(key: str, *, refresh: bool = False) -> tuple[dict[str, Any], list[Fetch]]:
    spec = COHORTS[key]
    series: list[str] = spec["series"]
    dates_by_series: dict[str, list[date]] = {}
    panels: dict[str, dict[date, dict[str, float]]] = {}
    manifest: list[Fetch] = []
    for name in series:
        stamps = vintage_dates(name)
        dates_by_series[name] = stamps
        panel, records = fetch_series(name, stamps, refresh=refresh)
        panels[name] = panel
        manifest.extend(records)

    all_dates = sorted({stamp for stamps in dates_by_series.values() for stamp in stamps})

    # One snapshot per union date: for each series, the vintage a reader would see at that date.
    # Building it once keeps the period scan linear instead of re-deriving "latest vintage" per
    # period, which is what makes a few hundred dates and periods tractable in pure Python.
    snapshots: dict[date, dict[str, dict[str, float]]] = {}
    latest_at: dict[date, dict[str, date | None]] = {}
    for stamp in all_dates:
        snapshot: dict[str, dict[str, float]] = {}
        resolved: dict[str, date | None] = {}
        for name in series:
            usable = [item for item in dates_by_series[name] if item <= stamp]
            chosen = usable[-1] if usable else None
            resolved[name] = chosen
            if chosen is not None:
                snapshot[name] = panels[name][chosen]
        snapshots[stamp] = snapshot
        latest_at[stamp] = resolved
    present_all: dict[date, set[str]] = {}
    for stamp, snapshot in snapshots.items():
        if len(snapshot) == len(series):
            keys = set(snapshot[series[0]])
            for name in series[1:]:
                keys &= set(snapshot[name])
            present_all[stamp] = keys
        else:
            present_all[stamp] = set()

    def observe(period: str, clock: date) -> dict[str, float] | None:
        if period not in present_all[clock]:
            return None
        return {name: snapshots[clock][name][period] for name in series}

    first_seen: dict[str, date] = {}
    for stamp in all_dates:
        for period in present_all[stamp]:
            first_seen.setdefault(period, stamp)

    def first_report(period: str) -> date | None:
        return first_seen.get(period)

    # Observation periods: every period any series reports, inside the fetch window.
    periods: set[str] = set()
    for name in series:
        for stamp_values in panels[name].values():
            periods.update(stamp_values)
    # Quarterly and monthly cohorts step by different numbers of months; shifting a quarter by one
    # month silently produces a period the data does not contain, which is how this filter first
    # rejected every quarterly event.
    step = int(spec["step_months"])
    by_month = sorted(
        (period for period in periods if period_key(period) is not None),
        key=lambda item: period_key(item) or (0, 0),
    )

    if os.environ.get("RTDS_DEBUG"):
        print(f"[{key}] dates={len(all_dates)} present_all_nonempty="
              f"{sum(1 for v in present_all.values() if v)} first_seen={len(first_seen)} "
              f"periods={len(by_month)} panel_sizes="
              f"{ {name: len(panels[name]) for name in series} }", flush=True)

    events: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    horizon = timedelta(days=int(spec["horizon_days"]))
    for period in by_month:
        previous = shift(period, -step)
        if previous is None:
            rejected.append({"period": period, "reason": "no_previous_period"})
            continue
        decision = first_report(period)
        if decision is None:
            rejected.append({"period": period, "reason": "never_reported"})
            continue
        split = split_of(decision)
        if split == "out_of_window":
            continue
        target = decision + horizon
        audit_candidates = [stamp for stamp in all_dates if stamp >= target]
        if not audit_candidates:
            rejected.append({"period": period, "reason": "no_audit_vintage"})
            continue
        audit = audit_candidates[0]
        at_decision = observe(period, decision)
        at_audit = observe(period, audit)
        previous_decision = observe(previous, decision)
        previous_audit = observe(previous, audit)
        if None in (at_decision, at_audit, previous_decision, previous_audit):
            missing = [label for label, value in (
                ("period@decision", at_decision), ("period@audit", at_audit),
                ("previous@decision", previous_decision), ("previous@audit", previous_audit))
                if value is None]
            rejected.append({"period": period, "reason": "incomplete_panel",
                             "decision": decision.isoformat(), "audit": audit.isoformat(),
                             "missing": missing})
            continue
        if audit == decision:
            rejected.append({"period": period, "reason": "audit_equals_decision"})
            continue
        assert at_decision and at_audit and previous_decision and previous_audit
        growth_decision = [at_decision[name] / previous_decision[name] - 1.0 for name in series]
        growth_audit = [at_audit[name] / previous_audit[name] - 1.0 for name in series]
        changed = [name for name, before, after in
                   zip(series, growth_decision, growth_audit) if before != after]
        revision_index = sum(1 for stamp in all_dates
                             if decision < stamp <= audit and observe(period, stamp) is not None)
        microseconds = {
            name: {
                "period": period,
                "decision_vintage": decision.isoformat(),
                "audit_vintage": audit.isoformat(),
                "value_decision": at_decision[name],
                "value_audit": at_audit[name],
                "previous_period": previous,
                "previous_value_decision": previous_decision[name],
                "previous_value_audit": previous_audit[name],
                "growth_decision": before,
                "growth_audit": after,
                "changed": bool(before != after),
            }
            for name, before, after in zip(series, growth_decision, growth_audit)
        }
        month = int(period[5:7])
        if key == "A":
            category = ("annual_benchmark_window" if month in (9, 10)
                        else "second_estimate" if revision_index <= 1 else "later_estimate")
        else:
            category = ("annual_benchmark_window" if month == 2
                        else "second_print" if revision_index <= 1 else "later_print")
        events.append({
            "cohort": key,
            "period": period,
            "decision_vintage": decision.isoformat(),
            "audit_vintage": audit.isoformat(),
            "horizon_days": int(spec["horizon_days"]),
            "split": split,
            "category": category,
            "revision_index": int(revision_index),
            "inputs": microseconds,
            "changed_inputs": changed,
            "growth_decision": growth_decision,
            "growth_audit": growth_audit,
            "delta_growth_l2": float(sum((a - b) ** 2 for a, b in
                                         zip(growth_audit, growth_decision)) ** 0.5),
            "any_revision": bool(changed),
            "ambiguity": [] if at_decision else ["missing_value_at_decision"],
        })

    digest = hashlib.sha256(
        json.dumps([[item.url, item.sha256] for item in manifest], sort_keys=True).encode()
    ).hexdigest()
    return {
        "cohort": key,
        "name": spec["name"],
        "frequency": spec["frequency"],
        "series": series,
        "labels": spec["labels"],
        "source": spec["source"],
        "source_urls": {
            "vintage_dates": ALFRED_VINTAGES.format(series="<ID>"),
            "vintage_series": ALFRED_CSV.format(series="<ID>", date="<DATE>"),
        },
        "time_policy": ("a vintage date is a release date; it is treated as available at 23:59:59 UTC "
                        "on that date, and no intraday timestamp is claimed"),
        "rights": ("ALFRED/FRED, Federal Reserve Bank of St. Louis terms of use; underlying series "
                   "are US government statistics in the public domain; raw responses are not "
                   "redistributed, only event records, URLs and SHA-256 digests"),
        "window": {"from": WINDOW[0].isoformat(), "to": WINDOW[1].isoformat()},
        "splits": {"train": [TRAIN[0].isoformat(), TRAIN[1].isoformat()],
                   "pilot": [PILOT[0].isoformat(), PILOT[1].isoformat()],
                   "test": [TEST[0].isoformat(), TEST[1].isoformat()]},
        "vintage_dates": {name: [stamp.isoformat() for stamp in stamps]
                          for name, stamps in dates_by_series.items()},
        "events": events,
        "rejected": rejected,
        "manifest_digest": digest,
        "manifest_counts": {"files": len(manifest), "cached": sum(1 for item in manifest if item.cached),
                            "bytes": sum(item.bytes for item in manifest)},
    }, manifest


def markdown(payload: dict[str, Any]) -> str:
    lines = ["# Real-time vintage dataset (generated)", "",
             "Built by `scripts/research/rtds_build.py`. Do not hand-edit.", ""]
    for cohort in payload["cohorts"]:
        lines.append(f"## Cohort {cohort['cohort']}: {cohort['name']}")
        lines.append("")
        lines.append(f"* series: {', '.join(cohort['series'])}")
        lines.append(f"* source: {cohort['source']}")
        lines.append(f"* vintage files fetched: {cohort['manifest_counts']['files']} "
                     f"({cohort['manifest_counts']['cached']} from cache, "
                     f"{cohort['manifest_counts']['bytes'] / 1e6:.1f} MB)")
        lines.append(f"* manifest digest: `{cohort['manifest_digest']}`")
        lines.append("")
        lines.append("| split | events | with a changed input | median changed inputs |")
        lines.append("|---|---|---|---|")
        for split in ("train", "pilot", "test"):
            subset = [event for event in cohort["events"] if event["split"] == split]
            changed = [event for event in subset if event["any_revision"]]
            median = (sorted(len(item["changed_inputs"]) for item in subset)[len(subset) // 2]
                      if subset else 0)
            lines.append(f"| {split} | {len(subset)} | {len(changed)} | {median} |")
        lines.append("")
        lines.append("| category | test events |")
        lines.append("|---|---|")
        categories: dict[str, int] = {}
        for event in cohort["events"]:
            if event["split"] == "test":
                categories[event["category"]] = categories.get(event["category"], 0) + 1
        for name in sorted(categories):
            lines.append(f"| {name} | {categories[name]} |")
        lines.append("")
        rejected = cohort["rejected"]
        if rejected:
            lines.append(f"Rejected or excluded periods: {len(rejected)} "
                         f"({', '.join(sorted({item['reason'] for item in rejected}))}).")
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema": "atlas.rtds.dataset.v1",
        "built_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "time_policy": ("vintage date = release date; eligible at 23:59:59 UTC on that date; no "
                        "intraday availability is claimed"),
        "splits": {"train": [TRAIN[0].isoformat(), TRAIN[1].isoformat()],
                   "pilot": [PILOT[0].isoformat(), PILOT[1].isoformat()],
                   "test": [TEST[0].isoformat(), TEST[1].isoformat()]},
        "cohorts": [],
    }
    manifests: list[dict[str, Any]] = []
    for key in COHORTS:
        cohort, manifest = build_cohort(key)
        payload["cohorts"].append(cohort)
        manifests.extend({
            "cohort": key, "series": item.series, "vintage": item.vintage, "url": item.url,
            "sha256": item.sha256, "bytes": item.bytes, "periods": item.periods,
            "cached": item.cached,
        } for item in manifest)
        print(f"cohort {key}: {len(cohort['events'])} events, {len(manifest)} vintage files")
    payload["manifest"] = manifests
    (OUT / "dataset.json").write_text(json.dumps(payload, indent=1, sort_keys=True))
    (OUT / "dataset.md").write_text(markdown(payload))
    print(f"wrote {OUT / 'dataset.json'}")


if __name__ == "__main__":
    main()
