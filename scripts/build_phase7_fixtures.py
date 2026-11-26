#!/usr/bin/env python3
"""Build the compact, committed Phase 7 weather-demand fixture.

Inputs are the public EIA-930 six-month balance files and the NCEI GHCN-Daily
station files downloaded into ``var/phase7/raw``. The committed fixture contains
daily aggregates only; the large source archives remain in the ignored cache.

Public-domain U.S. Government data. This script does not invent publication
vintages: the manifest records the retrieval time and explicitly says that the
current archive is not a historical as-issued snapshot.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "var" / "phase7" / "raw"
OUT = ROOT / "fixtures" / "phase7"

EIA_URLS = [
    "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2023_Jan_Jun.csv",
    "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2023_Jul_Dec.csv",
]
NOAA_PRIMARY_URL = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00013960.csv"
NOAA_COMPARISON_URL = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00003971.csv"

EIA_FILES = [
    RAW / "EIA930_BALANCE_2023_Jan_Jun.csv",
    RAW / "EIA930_BALANCE_2023_Jul_Dec.csv",
]
PRIMARY_FILE = RAW / "USW00013960.csv"
COMPARISON_FILE = RAW / "USW00003971.csv"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _date(text: str) -> str:
    return datetime.strptime(text, "%m/%d/%Y").date().isoformat()


def read_eia() -> dict[str, dict[str, float | int]]:
    daily: dict[str, dict[str, float | int]] = {}
    for path in EIA_FILES:
        if not path.exists():
            raise SystemExit(f"missing raw EIA file: {path}; run scripts/fetch_phase7_data.py")
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row["Balancing Authority"] != "ERCO":
                    continue
                day = _date(row["Data Date"])
                raw = row["Demand (MW)"].strip()
                if not raw:
                    continue
                value = float(raw)
                if value <= 0:
                    raise SystemExit(f"nonpositive ERCO demand on {day} hour {row['Hour Number']}")
                item = daily.setdefault(day, {"hours": 0, "sum_mw": 0.0, "peak": value, "min": value})
                item["hours"] = int(item["hours"]) + 1
                item["sum_mw"] = float(item["sum_mw"]) + value
                item["peak"] = max(float(item["peak"]), value)
                item["min"] = min(float(item["min"]), value)
    if len(daily) != 365:
        raise SystemExit(f"expected 365 ERCO days, found {len(daily)}")
    return daily


def read_ghcn(path: Path, year: int = 2023) -> dict[str, dict[str, float | None]]:
    if not path.exists():
        raise SystemExit(f"missing raw NOAA file: {path}; run scripts/fetch_phase7_data.py")
    result: dict[str, dict[str, float | None]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row["DATE"].startswith(f"{year}-"):
                continue
            def tenths(key: str) -> float | None:
                raw = row.get(key, "").strip()
                return float(raw) / 10.0 if raw else None
            result[row["DATE"]] = {
                "tmax_c": tenths("TMAX"),
                "tmin_c": tenths("TMIN"),
                "precip_mm": tenths("PRCP"),
            }
    if len(result) != 365:
        raise SystemExit(f"expected 365 NOAA days in {path.name}, found {len(result)}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieved-at", default=datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    demand = read_eia()
    primary = read_ghcn(PRIMARY_FILE)
    comparison = read_ghcn(COMPARISON_FILE)
    days = sorted(demand)
    if days != sorted(primary) or days != sorted(comparison):
        raise SystemExit("the demand and weather calendars do not align")

    path = OUT / "weather_demand_2023.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "date", "demand_mean_mw", "demand_peak_mw", "demand_min_mw",
            "demand_energy_mwh", "hours_observed", "temperature_mean_c",
            "temperature_max_c", "temperature_min_c", "cooling_degree_day_18c",
            "heating_degree_day_18c", "precipitation_mm",
            "comparison_temperature_max_c", "comparison_temperature_min_c",
        ])
        for day in days:
            d = demand[day]
            p = primary[day]
            c = comparison[day]
            tmax, tmin = p["tmax_c"], p["tmin_c"]
            tmean = (tmax + tmin) / 2 if tmax is not None and tmin is not None else None
            writer.writerow([
                day,
                f"{float(d['sum_mw']) / int(d['hours']):.3f}",
                f"{float(d['peak']):.3f}",
                f"{float(d['min']):.3f}",
                f"{float(d['sum_mw']):.3f}",
                int(d["hours"]),
                "" if tmean is None else f"{tmean:.3f}",
                "" if tmax is None else f"{tmax:.3f}",
                "" if tmin is None else f"{tmin:.3f}",
                "" if tmean is None else f"{max(tmean - 18.0, 0.0):.3f}",
                "" if tmean is None else f"{max(18.0 - tmean, 0.0):.3f}",
                "" if p["precip_mm"] is None else f"{p['precip_mm']:.3f}",
                "" if c["tmax_c"] is None else f"{c['tmax_c']:.3f}",
                "" if c["tmin_c"] is None else f"{c['tmin_c']:.3f}",
            ])

    manifest = {
        "schema": "atlas.economic.fixture.v1",
        "created_at": args.retrieved_at,
        "data_class": "observed_public_archive_no_vintage",
        "panel": {
            "path": "weather_demand_2023.csv",
            "sha256": _sha256(path),
            "rows": len(days),
            "start": days[0],
            "end": days[-1],
            "frequency": "daily",
            "geography": "ERCOT balancing authority / Dallas-Fort Worth, Texas",
            "timezone_note": "EIA Data Date is the local operating day; NOAA DATE is the station local observation day.",
        },
        "sources": [
            {
                "source_id": "eia-930",
                "name": "U.S. Energy Information Administration Form EIA-930",
                "urls": EIA_URLS,
                "files": [p.name for p in EIA_FILES],
                "sha256": [_sha256(p) for p in EIA_FILES],
                "rights": "U.S. Government public domain",
                "redistribution": "permitted",
                "transform": "ERCO hourly Demand (MW) aggregated to daily mean, peak, minimum and summed MWh; DST days retain their actual 23/24/25 hourly observations.",
                "limitations": [
                    "balanced/submitted data may reflect operator corrections after the operating day",
                    "the current bulk archive is not an as-issued historical vintage",
                    "hourly demand is not a settlement-grade revenue-meter record",
                ],
            },
            {
                "source_id": "noaa-ghcn",
                "name": "NOAA NCEI Global Historical Climatology Network Daily",
                "urls": [NOAA_PRIMARY_URL, NOAA_COMPARISON_URL],
                "files": [PRIMARY_FILE.name, COMPARISON_FILE.name],
                "sha256": [_sha256(PRIMARY_FILE), _sha256(COMPARISON_FILE)],
                "rights": "U.S. Government public domain",
                "redistribution": "permitted",
                "transform": "TMAX/TMIN tenths of degrees Celsius converted to Celsius; daily mean is the arithmetic mean of TMAX and TMIN; no infilling.",
                "limitations": [
                    "a point station is not an area-weighted temperature for the whole ERCOT footprint",
                    "quality-controlled archive values are not a historical forecast",
                    "the current archive does not establish the exact data publicly available on each historical date",
                ],
            },
        ],
        "stations": [
            {"id": "USW00013960", "name": "Dallas/Fort Worth International Airport", "role": "primary weather station"},
            {"id": "USW00003971", "name": "Dallas Redbird Airport", "role": "independent comparison station"},
        ],
        "notes": [
            "The fixture is derived only; raw source archives remain in ignored var/phase7/raw.",
            "Both sources are U.S. Government works treated as public domain; attribution and source URLs are retained.",
            "Weather is an observation, not a forecast. The same-day relationship is an association unless a defensible identification design is supplied.",
        ],
    }
    (OUT / "source_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"fixture": str(path), "rows": len(days), "sha256": manifest["panel"]["sha256"], "start": days[0], "end": days[-1]}, indent=2))


if __name__ == "__main__":
    main()
