"""Phase 10.4 measurements: the integrated release candidate, timed on this machine.

The historical numbers (≈24.3 s cold geometry for 12 filings, ≈45 ms warm, ≈111 ms per
geometry question, ≈706 MB peak) came from a different workload and a different machine.
Nothing here claims to reproduce them; this script measures the workloads a user actually
touches and writes the raw samples, the percentiles and the hardware they were taken on.

Usage::

    python scripts/benchmark_phase10_4.py --out artifacts/release/performance_phase10_4.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from accept_phase10_4 import DEMO_ANSWER_ISSUER, Server, _free_port  # noqa: E402

SCHEMA = "atlas.performance.phase10_4.v1"
APPLE = "ISS-CIK0000320193"


def percentile(samples: list[float], fraction: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    index = min(int(round(fraction * (len(ordered) - 1))), len(ordered) - 1)
    return round(ordered[index], 4)


def summarise(name: str, samples: list[float], unit: str = "ms", **extra: Any) -> dict[str, Any]:
    scaled = [value * 1000 if unit == "ms" else value for value in samples]
    return {
        "name": name,
        "unit": unit,
        "samples": len(samples),
        "p50": percentile(scaled, 0.5),
        "p95": percentile(scaled, 0.95),
        "min": round(min(scaled), 4) if scaled else None,
        "max": round(max(scaled), 4) if scaled else None,
        "mean": round(statistics.fmean(scaled), 4) if scaled else None,
        **extra,
    }


def timed(action: Callable[[], Any], repeat: int) -> tuple[list[float], Any]:
    samples: list[float] = []
    result = None
    for _ in range(repeat):
        started = time.perf_counter()
        result = action()
        samples.append(time.perf_counter() - started)
    return samples, result


def hardware() -> dict[str, Any]:
    cpu = platform.processor() or ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    memory_kb = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            memory_kb = int(handle.readline().split()[1])
    except (OSError, ValueError):
        pass
    return {
        "cpu": cpu,
        "cores": os.cpu_count(),
        "memory_gib": round(memory_kb / 1024 / 1024, 1) if memory_kb else None,
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "sqlite": _sqlite_version(),
    }


def _sqlite_version() -> str:
    import sqlite3
    return sqlite3.sqlite_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "artifacts" / "release" / "performance_phase10_4.json")
    parser.add_argument("--repeat", type=int, default=15)
    args = parser.parse_args(argv)

    work = Path(tempfile.mkdtemp(prefix="atlas-bench-"))
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    db = work / "demo.db"
    measurements: list[dict[str, Any]] = []
    notes: list[str] = []

    started = time.perf_counter()
    build = subprocess.run([sys.executable, "-m", "atlas", "--db", str(db), "demo"],
                           cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=600)
    build_seconds = time.perf_counter() - started
    notes.append(f"`atlas demo` built the demonstration database in {build_seconds:.2f} s "
                 f"(exit {build.returncode}); it ingests SEC payloads and parses one filing.")
    measurements.append({"name": "offline_demonstration_build", "unit": "s", "samples": 1,
                         "p50": round(build_seconds, 3), "p95": None, "min": round(build_seconds, 3),
                         "max": round(build_seconds, 3), "mean": round(build_seconds, 3),
                         "note": "cold: empty database, offline fixtures"})

    started = time.perf_counter()
    with Server(db, work) as server:
        startup_seconds = time.perf_counter() - started
        measurements.append({"name": "application_startup", "unit": "s", "samples": 1,
                             "p50": round(startup_seconds, 3), "p95": None,
                             "min": round(startup_seconds, 3), "max": round(startup_seconds, 3),
                             "mean": round(startup_seconds, 3),
                             "note": "process spawn to first healthy /api/health"})

        samples, _ = timed(lambda: server.request("GET", "/api/search?q=apple&limit=5"), args.repeat)
        measurements.append(summarise("command_palette_search", samples, samples_count=args.repeat))

        samples, _ = timed(lambda: server.request("GET", f"/api/companies/{APPLE}/statements"),
                           args.repeat)
        measurements.append(summarise("financial_statement_retrieval", samples))

        samples, _ = timed(lambda: server.request("GET", f"/api/companies/{APPLE}"), args.repeat)
        measurements.append(summarise("company_detail", samples))

        samples, _ = timed(lambda: server.request(
            "POST", "/api/answers/certificate",
            {"issuer_id": DEMO_ANSWER_ISSUER, "concept": "gross_profit", "period": "2023"}), 5)
        measurements.append(summarise("answer_certificate", samples))

        samples, _ = timed(lambda: server.request("POST", "/api/research/comparison", {
            "issuers": [APPLE, DEMO_ANSWER_ISSUER], "concepts": ["revenue"],
            "period": "2023"}), 5)
        measurements.append(summarise("company_comparison", samples))

        defaults = server.request("GET", f"/api/valuation/defaults/{APPLE}")[1]["defaults"]
        assumptions = {k: v for k, v in defaults.items() if k != "provenance"}
        samples, _ = timed(lambda: server.request("POST", "/api/valuation/dcf", {
            "issuer": APPLE, "assumptions": assumptions, "mode": "public_available"}), 5)
        measurements.append(summarise("dcf_valuation", samples))

        status, memo, _ = server.request("POST", f"/api/equity/{APPLE}/memo/save", {"name": "bench"})
        object_id = memo.get("object_id")
        samples, _ = timed(lambda: server.request(
            "GET", f"/api/research/memos/{object_id}/export?format=pdf", raw=True), 5)
        measurements.append(summarise("pdf_report_generation", samples))

        samples, _ = timed(lambda: server.request(
            "GET", f"/api/research/memos/{object_id}/export?format=json", raw=True), 5)
        measurements.append(summarise("machine_readable_export", samples))

        def answer(_: int) -> None:
            server.request("POST", "/api/answers/certificate",
                           {"issuer_id": DEMO_ANSWER_ISSUER, "concept": "gross_profit",
                            "period": "2023"})

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(answer, range(24)))
        concurrent_seconds = time.perf_counter() - started
        measurements.append({"name": "concurrent_answers_8_way", "unit": "s", "samples": 24,
                             "p50": round(concurrent_seconds / 24, 4), "p95": None,
                             "min": None, "max": None,
                             "mean": round(concurrent_seconds / 24, 4),
                             "note": f"24 requests over 8 threads in {concurrent_seconds:.2f} s total"})

    # MCP: process lifetime plus per-call latency through the stdio server.
    mcp_started = time.perf_counter()
    process = subprocess.Popen([sys.executable, "-m", "atlas", "--db", str(db), "mcp"],
                               cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=env)
    latencies: list[float] = []
    try:
        def call(message: dict[str, Any]) -> dict[str, Any]:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            while True:
                reply = json.loads(process.stdout.readline())
                if reply.get("id") == message["id"]:
                    return reply

        call({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "bench", "version": "10.4"}}})
        process.stdin.write(json.dumps({"jsonrpc": "2.0",
                                        "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()
        handshake = time.perf_counter() - mcp_started
        for index in range(2, 12):
            started = time.perf_counter()
            call({"jsonrpc": "2.0", "id": index, "method": "tools/call",
                  "params": {"name": "resolve_financial_question",
                             "arguments": {"issuer_id": DEMO_ANSWER_ISSUER,
                                           "concept": "gross_profit", "period": "2023"}}})
            latencies.append(time.perf_counter() - started)
        measurements.append({"name": "mcp_handshake", "unit": "s", "samples": 1,
                             "p50": round(handshake, 3), "p95": None, "min": round(handshake, 3),
                             "max": round(handshake, 3), "mean": round(handshake, 3)})
        measurements.append(summarise("mcp_tool_call", latencies))
    finally:
        try:
            process.stdin.close()
        except Exception:
            pass
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    peak_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    measurements.append({"name": "peak_resident_memory_of_client_process", "unit": "MB",
                         "samples": 1, "p50": peak_mb, "p95": None, "min": peak_mb,
                         "max": peak_mb, "mean": peak_mb,
                         "note": "this harness, not the server process"})
    db_bytes = db.stat().st_size if db.is_file() else 0
    measurements.append({"name": "database_size", "unit": "MB", "samples": 1,
                         "p50": round(db_bytes / 1024 / 1024, 1), "p95": None,
                         "min": round(db_bytes / 1024 / 1024, 1),
                         "max": round(db_bytes / 1024 / 1024, 1),
                         "mean": round(db_bytes / 1024 / 1024, 1),
                         "note": "demonstration database after `atlas demo`"})

    report = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                                 capture_output=True, text=True).stdout.strip(),
        "hardware": hardware(),
        "dataset": {"database": "atlas demo", "issuers": 5, "filings": 1003,
                    "evidence_rows": 6524, "ingested_documents": 1,
                    "note": "the offline demonstration corpus; one parsed synthetic 10-K"},
        "measurements": measurements,
        "notes": notes + [
            "Percentiles are over the samples stated in each row, on one warm process unless "
            "the note says otherwise.",
            "The historical geometry numbers (24.3 s cold / 45 ms warm / 111 ms per question) "
            "are not comparable to these rows: different workload, different machine.",
            "No optimisation is claimed from these numbers. They are a baseline for future "
            "work, not a target that was met.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    for row in measurements:
        print(f"{row['name']:38} {str(row['p50']):>10} {row['unit']:>4}  "
              f"p95={row['p95']}  n={row['samples']}")
    print(f"report: {args.out}")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
