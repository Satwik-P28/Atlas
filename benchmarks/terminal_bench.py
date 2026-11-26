"""Measure the Phase 2 terminal against a running local API.

Reports wall-clock HTTP latency (median and p95) for the read paths a user actually
waits on, plus the server's resident memory and the on-disk database size. No number
here is estimated: each is measured on the built `var/atlas.db`.

Usage:
    .venv/bin/python benchmarks/terminal_bench.py [--base http://127.0.0.1:8000] [--pid PID]
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts" / "perf.json"


def timed(client: httpx.Client, method: str, path: str, payload: dict | None = None, repeat: int = 7) -> dict:
    samples: list[float] = []
    body: dict | None = None
    for _ in range(repeat):
        started = time.perf_counter()
        response = client.request(method, path, json=payload)
        samples.append((time.perf_counter() - started) * 1000)
        response.raise_for_status()
        body = response.json()
    samples.sort()
    return {
        "path": f"{method} {path}",
        "median_ms": round(statistics.median(samples), 2),
        "p95_ms": round(samples[max(0, int(len(samples) * 0.95) - 1)], 2),
        "min_ms": round(samples[0], 2),
        "max_ms": round(samples[-1], 2),
        "samples": repeat,
        "bytes": len(json.dumps(body)),
    }


def server_rss_kb(pid: int | None) -> int | None:
    if not pid:
        return None
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--pid", type=int, default=None)
    args = parser.parse_args()

    db_path = ROOT / "var" / "atlas.db"
    with httpx.Client(base_url=args.base, timeout=60) as client:
        health = client.get("/api/health").json()
        companies = client.get("/api/companies").json()
        issuer = next(item for item in companies["items"] if item["legal_name"].startswith("Apple"))
        issuer_id = issuer["issuer_id"]
        security_id = issuer["securities"][0]["security_id"]
        statements = client.get(f"/api/companies/{issuer_id}/statements?statement=income&period=FY&limit=6").json()
        evidence_id = statements["rows"][0]["cells"][0]["evidence_id"]

        results = [
            timed(client, "GET", "/api/health"),
            timed(client, "GET", "/api/companies"),
            timed(client, "GET", f"/api/companies/{issuer_id}"),
            timed(client, "GET", f"/api/companies/{issuer_id}/statements?statement=income&period=FY&limit=6"),
            timed(client, "GET", f"/api/companies/{issuer_id}/metrics"),
            timed(client, "GET", f"/api/securities/{security_id}/market?range=1Y&view=split"),
            timed(
                client,
                "POST",
                f"/api/securities/{security_id}/market",
                {"range": "1Y", "view": "total_return", "indicators": [
                    {"key": "sma", "params": {"window": 50}},
                    {"key": "rsi", "params": {"window": 14}},
                    {"key": "macd", "params": {}},
                    {"key": "bollinger", "params": {"window": 20, "num_std": 2}},
                ]},
            ),
            timed(client, "GET", f"/api/companies/{issuer_id}/statements?statement=income&period=FY&as_of=2023-12-31T23:59:59Z"),
            timed(client, "GET", f"/api/evidence/{evidence_id}"),
            timed(client, "POST", "/api/screeners/run", {"filters": [{"metric": "net_margin", "op": "gt", "value": 0.1}], "limit": 100}),
            timed(client, "GET", f"/api/companies/{issuer_id}/filings?limit=50"),
        ]

    # Cold read path: opening the database and producing one company page in-process.
    started = time.perf_counter()
    from atlas.storage.db import Database
    from atlas.terminal import read_models

    db = Database(db_path)
    companies = read_models.list_companies(db)
    apple = next(item for item in companies if item["legal_name"].startswith("Apple"))
    read_models.company_detail(db, apple["issuer_id"])
    read_models.statements(db, apple["issuer_id"], statement="income", period="FY", limit=6)
    cold_ms = (time.perf_counter() - started) * 1000
    db.close()

    report = {
        "database": {
            "path": str(db_path.relative_to(ROOT)),
            "size_mb": round(db_path.stat().st_size / 1_048_576, 1),
            "evidence": health["evidence"],
            "issuers": health["issuers"],
            "bars": health["bars"],
            "schema_version": health["schema_version"],
        },
        "server": {
            "rss_mb": round(server_rss_kb(args.pid) / 1024, 1) if server_rss_kb(args.pid) else None,
            "cold_first_read_ms": round(cold_ms, 1),
        },
        "requests": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n")

    print(f"database: {report['database']['size_mb']} MB, {report['database']['evidence']:,} evidence records")
    print(f"cold first read (open + company page + statements): {report['server']['cold_first_read_ms']} ms")
    if report["server"]["rss_mb"]:
        print(f"server RSS: {report['server']['rss_mb']} MB")
    print(f"{'endpoint':64s} {'median':>9s} {'p95':>9s}")
    for row in results:
        print(f"{row['path'][:64]:64s} {row['median_ms']:>7.2f}ms {row['p95_ms']:>7.2f}ms")
    print(f"written to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
