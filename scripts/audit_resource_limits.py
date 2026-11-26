"""Bounded resource-exhaustion audit for the release candidate.

Each case feeds one hostile shape an operator could actually reach (an HTML filing, a market
CSV, a research-application package, the local HTTP API, an MCP client) and records what
happened: whether the work stayed bounded, whether the failure was typed, and whether the
process was still healthy afterwards. It is a bounded audit, not a fuzzing campaign.

    python scripts/audit_resource_limits.py --out artifacts/release/resource_limits.json

Nothing here proves the absence of a resource bug. It establishes behaviour under the tested
workload and records the limits that were actually exercised.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import resource
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.errors import ValidationError  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
#: A single case may not grow the process beyond this. The audit is about bounded work, so a
#: shape that needs more memory than this is a finding, not a slow test.
PEAK_LIMIT_MB = 2048


def peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def run_case(case_id: str, description: str, action: Callable[[], tuple[bool, str]]) -> dict:
    started = time.perf_counter()
    try:
        ok, detail = action()
    except ValidationError as refusal:
        ok, detail = True, f"typed refusal: {refusal}"
    except Exception as error:  # noqa: BLE001 - a crash is the finding
        ok, detail = False, f"{type(error).__name__}: {str(error)[:200]}"
    seconds = round(time.perf_counter() - started, 2)
    peak = round(peak_mb(), 1)
    if peak > PEAK_LIMIT_MB:
        ok = False
        detail += f"; peak RSS {peak} MB exceeds the {PEAK_LIMIT_MB} MB bound"
    print(f"{'ok  ' if ok else 'FAIL'} {case_id:<28} {seconds:>6.2f}s {peak:>8.1f}MB  {detail[:140]}")
    return {"id": case_id, "status": "pass" if ok else "fail", "detail": detail,
            "seconds": seconds, "peak_rss_mb": peak, "description": description}


def _database(directory: Path) -> Database:
    database = Database(str(directory / "audit.db"))
    database.migrate()
    database.execute(
        "INSERT OR IGNORE INTO source (source_id, name, kind, redistribution, created_at) "
        "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain','2026-01-01T00:00:00Z')")
    database.execute(
        "INSERT OR IGNORE INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
        "provenance_source, created_at, updated_at) VALUES "
        "('ISS-AUDIT','0000000099','Audit Fixture Corp','company',1,'test',"
        "'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')")
    return database


def _ingest(database: Database, html: str, accession: str) -> dict:
    from atlas.research.knowledge import KnowledgeEngine

    return KnowledgeEngine(database).ingest_document(
        issuer_id="ISS-AUDIT", accession=accession, form_type="10-K", html=html.encode(),
        filed_date="2026-02-01", acceptance_time="2026-02-01T12:00:00Z",
        period_of_report="2025-12-31", rights="public_domain",
        primary_document_url=f"https://example.invalid/{accession}.htm")


def malformed_html(directory: Path) -> tuple[bool, str]:
    """Unclosed tags, spans that overrun the grid, and a table nested in itself."""
    pieces = ["<html><body>"]
    for index in range(300):
        pieces.append(
            f"<table><tr><td colspan='9' rowspan='4'>2026<td>{index}"
            f"<tr><td>Revenue<td>1,234<td colspan='-2'>x</tr><table><tr><td>inner")
    pieces.append("</body></html>")
    html = "".join(pieces)
    database = _database(directory)
    try:
        document = _ingest(database, html, "0000000099-26-000901")
    finally:
        database.close()
    return True, (f"{len(html) / 1024:.0f} KB of malformed markup ingested; "
                  f"{document['table_count']} tables, {document['unit_count']} units")


def large_table(directory: Path) -> tuple[bool, str]:
    rows = ["<table><tr><td>Line item</td><td>2025</td><td>2024</td><td>2023</td>"
            "<td>2022</td><td>2021</td></tr>"]
    for index in range(4000):
        rows.append("<tr><td>Line %d</td><td>%d</td><td>%d</td><td>%d</td><td>%d</td>"
                    "<td>%d</td></tr>" % (index, index, index, index, index, index))
    rows.append("</table>")
    html = ("<html><body><p>Consolidated statements of operations (in millions)</p>"
            + "".join(rows) + "</body></html>")
    database = _database(directory)
    try:
        document = _ingest(database, html, "0000000099-26-000902")
    finally:
        database.close()
    ok = document["table_count"] >= 1
    return ok, (f"4,000 x 5 table ({len(html) / 1024:.0f} KB) ingested in the case budget; "
                f"{document['table_count']} tables, {document['unit_count']} units")


def oversized_document(directory: Path) -> tuple[bool, str]:
    """One 30 MB filing: either it is processed within the bound or refused, never hung."""
    paragraph = "<p>" + ("consolidated statements of operations revenue " * 40) + "</p>"
    table = ("<table><tr><td></td><td>2025</td><td>2024</td></tr>"
             "<tr><td>Revenue</td><td>1,000</td><td>900</td></tr></table>")
    html = "<html><body>" + (paragraph + table) * 16000 + "</body></html>"
    size = len(html) / (1024 * 1024)
    database = _database(directory)
    try:
        document = _ingest(database, html, "0000000099-26-000903")
    finally:
        database.close()
    return True, f"{size:.1f} MB document ingested; {document['table_count']} tables"


def large_csv(directory: Path) -> tuple[bool, str]:
    from atlas.ingestion.market_csv import import_csv_bars

    path = directory / "large.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("date,open,high,low,close,volume\n")
        for index in range(200_000):
            handle.write(f"2025-01-{1 + index % 28:02d},100,101,99,100.5,1000\n")
    result = import_csv_bars(path, security_id="SEC-AUDIT", mic="XNYS",
                             source_id="onboarding-preview")
    return True, f"200,000-row CSV parsed into {len(result.bars)} bars"


def archive_expansion(directory: Path) -> tuple[bool, str]:
    """A 16 MB expansion inside a tiny ZIP, and a package with 200 entries."""
    from atlas.applications.contracts import PackageValidationError, read_package

    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("payload.bin", b"\0" * (16 * 1024 * 1024))
    payload = bomb.getvalue()
    refusals = 0
    try:
        read_package(payload)
    except PackageValidationError:
        refusals += 1
    many = io.BytesIO()
    with zipfile.ZipFile(many, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("manifest.json", "{}")
        for index in range(200):
            archive.writestr(f"file{index}.txt", "x")
    try:
        read_package(many.getvalue())
    except PackageValidationError:
        refusals += 1
    return refusals == 2, (f"{len(payload) / 1024:.0f} KB zip expanding to 16 MB and a "
                           f"200-entry package both refused ({refusals}/2)")


def _server(directory: Path, port: int) -> subprocess.Popen:
    database = directory / "server.db"
    subprocess.run([sys.executable, "-m", "atlas", "--db", str(database), "init"],
                   check=True, capture_output=True, env=ENV)
    process = subprocess.Popen([sys.executable, "-m", "atlas", "--db", str(database), "serve",
                                "--port", str(port)], env=ENV, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                if response.status == 200:
                    return process
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(0.5)
    process.terminate()
    raise RuntimeError("server did not become ready")


def _health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001 - a dead server is the finding
        return False


def repeated_invalid_requests(directory: Path, port: int) -> tuple[bool, str]:
    process = _server(directory, port)
    try:
        def one(_: int) -> int:
            body = json.dumps({"issuer_id": "x", "concept": "revenue", "period": "2025",
                               "as_of": "2099-01-01"}).encode()
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/answers/resolve", data=body,
                headers={"Content-Type": "application/json",
                         "Origin": f"http://127.0.0.1:{port}"})
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    return response.status
            except urllib.error.HTTPError as error:
                return error.code
            except Exception:  # noqa: BLE001 - recorded as a non-4xx outcome
                return 0

        with ThreadPoolExecutor(max_workers=16) as pool:
            statuses = list(pool.map(one, range(200)))
        healthy = _health(port)
    finally:
        process.terminate()
        process.wait(timeout=20)
    refused = sum(1 for status in statuses if 400 <= status < 500)
    return healthy and refused == 200, (
        f"{refused}/200 invalid requests refused with 4xx; health after load={healthy}")


def cancellation(directory: Path, port: int) -> tuple[bool, str]:
    process = _server(directory, port)
    try:
        dropped = 0
        for _ in range(20):
            client = socket.create_connection(("127.0.0.1", port), timeout=5)
            client.sendall(b"GET /api/knowledge/units?limit=500 HTTP/1.1\r\n"
                           b"Host: 127.0.0.1\r\n\r\n")
            client.close()  # the client goes away mid-response
            dropped += 1
        time.sleep(1.0)
        healthy = _health(port)
    finally:
        process.terminate()
        process.wait(timeout=20)
    return healthy, f"{dropped} connections dropped mid-response; health afterwards={healthy}"


def concurrent_mcp(directory: Path) -> tuple[bool, str]:
    database = directory / "mcp.db"
    subprocess.run([sys.executable, "-m", "atlas", "--db", str(database), "init"],
                   check=True, capture_output=True, env=ENV)

    def one(_: int) -> bool:
        process = subprocess.Popen([sys.executable, "-m", "atlas", "--db", str(database), "mcp"],
                                   env=ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True)
        try:
            request = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
            return '"result"' in line
        finally:
            process.terminate()
            process.wait(timeout=20)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, range(4)))
    return all(results), f"{sum(results)}/4 concurrent MCP sessions answered initialize"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "artifacts" / "release" / "resource_limits.json")
    arguments = parser.parse_args(argv)
    cases: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="atlas-limits-") as raw:
        directory = Path(raw)
        cases.append(run_case("malformed_html", "broken nesting and spans in 300 tables",
                              lambda: malformed_html(directory)))
        cases.append(run_case("large_financial_table", "4,000-row statement table",
                              lambda: large_table(directory)))
        cases.append(run_case("oversized_document", "a 30 MB filing", lambda: oversized_document(directory)))
        cases.append(run_case("large_csv", "200,000-row market CSV", lambda: large_csv(directory)))
        cases.append(run_case("archive_expansion", "ZIP bomb and entry-count limit",
                              lambda: archive_expansion(directory)))
        cases.append(run_case("repeated_invalid_requests", "200 concurrent invalid API requests",
                              lambda: repeated_invalid_requests(directory, 3987)))
        cases.append(run_case("cancellation", "clients dropping mid-response",
                              lambda: cancellation(directory, 3988)))
        cases.append(run_case("concurrent_mcp", "four simultaneous MCP sessions",
                              lambda: concurrent_mcp(directory)))
    cases.append({"id": "expensive_model_requests", "status": "not_run", "seconds": None,
                  "peak_rss_mb": round(peak_mb(), 1),
                  "detail": "no model provider is configured in this environment; an expensive "
                            "model request cannot be issued and is not claimed as tested",
                  "description": "expensive language-model request"})
    summary = {
        "pass": sum(1 for case in cases if case["status"] == "pass"),
        "fail": sum(1 for case in cases if case["status"] == "fail"),
        "not_run": sum(1 for case in cases if case["status"] == "not_run"),
    }
    report = {"schema": "atlas.audit.resource_limits.v1", "peak_limit_mb": PEAK_LIMIT_MB,
              "summary": summary, "cases": cases,
              "limitations": [
                  "Bounded audit, not a fuzzing campaign or a memory-profiler trace.",
                  "Single-process SQLite; no multi-user isolation is exercised by design.",
                  "The oversized-document case records that the work finished inside the "
                  "bound; it does not establish a maximum supported filing size.",
              ]}
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"resource audit: {summary['pass']} pass, {summary['fail']} fail, "
          f"{summary['not_run']} not run -> {arguments.out}")
    return 0 if summary["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
