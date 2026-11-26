#!/usr/bin/env python3
"""Fetch the public Phase 7 source archives into the ignored local cache.

No credentials are used. The URLs are the documented EIA-930 six-month bulk
files and NCEI GHCN-Daily station archives. The raw archives are never committed.
"""

from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "var" / "phase7" / "raw"
FILES = {
    "EIA930_BALANCE_2023_Jan_Jun.csv": "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2023_Jan_Jun.csv",
    "EIA930_BALANCE_2023_Jul_Dec.csv": "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles/EIA930_BALANCE_2023_Jul_Dec.csv",
    "USW00013960.csv": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00013960.csv",
    "USW00003971.csv": "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/USW00003971.csv",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        target = RAW / name
        if target.exists() and not args.force:
            print(f"present {target}")
            continue
        request = urllib.request.Request(url, headers={"User-Agent": "AtlasQuant/0.7 public-data-research"})
        with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as handle:
            while chunk := response.read(1024 * 1024):
                handle.write(chunk)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        print(f"downloaded {target} sha256={digest}")


if __name__ == "__main__":
    main()
