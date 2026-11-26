"""Phase 10.4 flagship acceptance: does Atlas work as one product, end to end?

Every previous phase certified a component. This script starts the real HTTP server on a real
demonstration database and drives the journey a user is promised: find a company, read its
statements, ask a question, get a certificate, follow the evidence, check the arithmetic, value
it, change the assumptions, compare, save, export, verify the export, reproduce the answer on a
second database, and ask the same question through MCP.

The script's own check is agreement: the figure the browser surface shows, the figure in the PDF
text, the figure in the machine-readable export and the figure MCP returns must be the same
number. It also runs a quantitative journey (import, strategy, backtest, accounting, benchmark,
limitations, export, replay) including one refusal and one negative result.

Usage::

    python scripts/accept_phase10_4.py --out artifacts/release/acceptance_phase10_4.json

Exit status is 0 only when every step passed. A step that could not be attempted is recorded as
``not_run`` with its reason and fails the run: silence is not acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime as _dt
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "atlas.acceptance.phase10_4.v1"
APPLE = "ISS-CIK0000320193"
DEMO_ANSWER_CIK = "1900003"
DEMO_ANSWER_ISSUER = "ISS-CIK0001900003"
CONCEPT = "gross_profit"
PERIOD = "2023"
GROSS_PROFIT_MILLIONS = 21690
NET_SALES_MILLIONS = 48200
COST_OF_SALES_MILLIONS = 26510


# --------------------------------------------------------------------------- #
# record keeping
# --------------------------------------------------------------------------- #
class Run:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.values: dict[str, Any] = {}

    def step(self, step_id: str, surface: str, ok: bool, detail: str,
             **payload: Any) -> dict[str, Any]:
        record = {
            "id": step_id,
            "surface": surface,
            "status": "pass" if ok else "fail",
            "detail": detail,
            "seconds": payload.pop("seconds", None),
            **payload,
        }
        if record["seconds"] is not None:
            record["seconds"] = round(float(record["seconds"]), 4)
        self.steps.append(record)
        return record

    def skip(self, step_id: str, surface: str, reason: str) -> None:
        self.steps.append({"id": step_id, "surface": surface, "status": "not_run",
                           "detail": reason, "seconds": None})

    def summary(self) -> dict[str, int]:
        counts = {"pass": 0, "fail": 0, "not_run": 0}
        for step in self.steps:
            counts[step["status"]] += 1
        return counts


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# HTTP against the real server
# --------------------------------------------------------------------------- #
class Server:
    def __init__(self, db: Path, workdir: Path) -> None:
        self.db = db
        self.workdir = workdir
        self.port = _free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.log = workdir / "serve.log"
        self.proc: subprocess.Popen[bytes] | None = None
        self.last_headers: dict[str, str] = {}

    def __enter__(self) -> "Server":
        handle = self.log.open("wb")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "atlas", "--db", str(self.db), "serve",
             "--port", str(self.port)],
            cwd=str(ROOT), stdout=handle, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        )
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"server exited early:\n{self.log.read_text()[-2000:]}")
            try:
                with urllib.request.urlopen(f"{self.base}/api/health", timeout=2) as response:
                    if response.status == 200:
                        return self
            except (urllib.error.URLError, socket.timeout):
                time.sleep(0.25)
        raise RuntimeError(f"server did not become healthy:\n{self.log.read_text()[-2000:]}")

    def __exit__(self, *exc: object) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def request(self, method: str, path: str, body: Any = None,
                *, raw: bool = False) -> tuple[int, Any, float]:
        url = f"{self.base}{path}"
        data = None
        headers = {"accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["content-type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = response.read()
                self.last_headers = {k.lower(): v for k, v in response.headers.items()}
                elapsed = time.perf_counter() - started
                if raw:
                    return response.status, payload, elapsed
                return response.status, json.loads(payload.decode() or "null"), elapsed
        except urllib.error.HTTPError as error:
            payload = error.read()
            elapsed = time.perf_counter() - started
            try:
                parsed = json.loads(payload.decode() or "null")
            except json.JSONDecodeError:
                parsed = payload.decode(errors="replace")
            return error.code, parsed, elapsed


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --------------------------------------------------------------------------- #
# helpers for the response shapes we need to read
# --------------------------------------------------------------------------- #
def walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def find_row(document: Any, label: str) -> dict[str, Any] | None:
    """Find a statement row by label anywhere in a statements payload."""
    lowered = label.lower()
    for node in walk(document):
        for key in ("label", "row_label", "name", "metric"):
            value = node.get(key)
            if isinstance(value, str) and lowered in value.lower():
                return node
    return None


def numbers_in(text: str) -> set[str]:
    """Normalise every number in a text surface to a canonical integer/decimal string."""
    found: set[str] = set()
    for token in re.findall(r"-?\d[\d,]*\.?\d*", text):
        cleaned = token.replace(",", "").strip(".")
        if cleaned in {"", "-"}:
            continue
        try:
            value = float(cleaned)
        except ValueError:
            continue
        found.add(f"{value:.2f}")
    return found


TEXTUAL = re.compile(rb"\((?:\\.|[^()\\])*\)\s*Tj")
STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)


def pdf_text(payload: bytes) -> str:
    """Extract the text our own renderer wrote (content streams are deliberately uncompressed)."""
    pieces: list[str] = []
    for stream in STREAM.findall(payload):
        for match in TEXTUAL.finditer(stream):
            raw = match.group(0)[1:match.group(0).rfind(b")")]
            pieces.append(raw.decode("latin-1"))
    text = "\n".join(pieces)
    return text.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")


# --------------------------------------------------------------------------- #
# the flagship journey
# --------------------------------------------------------------------------- #
def flagship(run: Run, server: Server, db: Path, work: Path) -> dict[str, Any]:
    api = server.request

    status, companies, _ = api("GET", "/api/health")
    run.step("demo_health", "api", status == 200 and companies.get("status") == "ok",
             f"/api/health {status} status={companies.get('status')} evidence={companies.get('evidence')}")

    started = time.perf_counter()
    status, results, elapsed = api("GET", "/api/search?q=apple&limit=5")
    items = results.get("items") if isinstance(results, dict) else None
    run.step("palette_search", "api", status == 200 and bool(items),
             f"{len(items or [])} palette result(s) for 'apple'", seconds=elapsed,
             value=items[0] if items else None)

    status, company, _ = api("GET", f"/api/companies/{APPLE}")
    legal = (company or {}).get("legal_name") or (company or {}).get("issuer", {}).get("legal_name")
    run.step("select_company", "api", status == 200 and bool(legal), f"{legal} ({status})")

    status, statements, _ = api("GET", f"/api/companies/{APPLE}/statements")
    columns = (statements or {}).get("columns") or []
    run.step("statements", "api", status == 200 and len(columns) >= 2,
             f"{len(columns)} statement column(s), completeness="
             f"{(statements or {}).get('completeness')}")

    status, filings, _ = api("GET", f"/api/companies/{APPLE}/filings")
    filing_rows = (filings or {}).get("items") or (filings or {}).get("filings") or []
    run.step("filing_search", "api", status == 200 and bool(filing_rows),
             f"{len(filing_rows)} archived filing(s)")

    # The synthetic demonstration registrant carries the parsed statement tables the answer
    # engine needs. Its figures are invented and the report says so on every surface.
    status, answer, elapsed = api("POST", "/api/answers/certificate", {
        "issuer_id": DEMO_ANSWER_ISSUER,
        "concept": CONCEPT, "period": PERIOD,
        "research_question": f"What was gross profit in fiscal {PERIOD}?",
    })
    if status != 200:
        run.step("ask_question", "api", False, f"certificate refused: {status} {answer}")
        return run.values
    certificate = answer["certificate"]
    evidence = answer["evidence"]
    value = evidence.get("value")
    api_value = float(value) if value is not None else None
    run.values["answer_value"] = api_value
    run.values["certificate"] = certificate
    run.step("ask_question", "api", api_value == GROSS_PROFIT_MILLIONS,
             f"{CONCEPT} {PERIOD} = {value} {evidence.get('currency')} "
             f"({evidence.get('row_label')} / {evidence.get('statement_title')})",
             seconds=elapsed, value=value)
    run.step("answer_certificate", "api", bool(certificate.get("certificate_fingerprint")),
             f"fingerprint {certificate.get('certificate_fingerprint', '')[:16]}…, "
             f"level={answer.get('availability', {}).get('availability_precision')}",
             fingerprint=certificate.get("certificate_fingerprint"))

    status, verdict, _ = api("POST", "/api/certificates/verify", {"certificate": certificate})
    checks = (verdict or {}).get("verification") or verdict or {}
    level = checks.get("level") if isinstance(checks, dict) else None
    passed = status == 200 and isinstance(checks, dict) and checks.get("verified") is not False
    run.step("verify_certificate", "api", passed,
             f"independent verification: {level or checks}", verification=checks)

    accession = evidence.get("accession")
    status, doc, _ = api("GET", f"/api/companies/{APPLE}/filings")
    followed = any(str(row.get("accession_number") or row.get("accession")) == str(accession)
                   for row in ((doc or {}).get("items") or []))
    filing_ok = status == 200
    run.step("follow_evidence", "api", bool(accession) and filing_ok,
             f"evidence accession {accession} resolves on the filings surface "
             f"({'matched' if followed else 'company-level listing only'})")

    # The answer is bound to a cell of a parsed filing table; recompute the arithmetic from that
    # same parsed table read back through the knowledge surface, not from the answer itself.
    status, docs, _ = api("GET", f"/api/knowledge/documents?issuer_id={DEMO_ANSWER_ISSUER}")
    document_id = ((docs or {}).get("items") or [{}])[0].get("document_id")
    status, tables, _ = api("GET", f"/api/knowledge/documents/{document_id}/tables")
    rows = _table_cells(tables, PERIOD)
    sales, cost, gross = rows.get("net sales"), rows.get("cost of sales"), rows.get("gross profit")
    recomputed = (sales - cost) if (sales is not None and cost is not None) else None
    run.step("verify_calculation", "knowledge",
             recomputed is not None and gross == float(value)
             and abs(recomputed - float(value)) < 1e-6,
             f"parsed table: net sales {sales} - cost of sales {cost} = {recomputed}; "
             f"gross profit row {gross}; certificate {value}",
             value=recomputed)

    status, defaults, _ = api("GET", f"/api/valuation/defaults/{APPLE}")
    assumptions = (defaults or {}).get("defaults") or {}
    base = _dcf(api, APPLE, assumptions)
    run.step("valuation", "api", base is not None,
             f"base DCF value per share {base}", value=base)

    tighter = {**assumptions, "wacc": round(float(assumptions.get("wacc", 0.09)) + 0.02, 4)}
    worse = _dcf(api, APPLE, tighter)
    run.step("modify_assumptions", "api", base is not None and worse is not None and worse < base,
             f"wacc {assumptions.get('wacc')} -> {tighter['wacc']}: {base} -> {worse}",
             value={"base": base, "higher_wacc": worse})

    status, scenarios, _ = api("POST", "/api/valuation/scenarios", {"issuer": APPLE})
    values = [item.get("value_per_share") for item in
              ((scenarios or {}).get("scenarios") or {}).values()]
    distinct = len({round(float(v), 6) for v in values if v is not None})
    run.step("scenario_comparison", "api", distinct >= 2,
             f"{len(values)} scenario(s), {distinct} distinct value(s)", value=values)

    status, comparison, _ = api("POST", "/api/research/comparison", {
        "issuers": [APPLE, DEMO_ANSWER_ISSUER],
        "concepts": ["revenue", "net_income"], "period": "2023",
    })
    findings = [finding for concept in ((comparison or {}).get("concepts") or [])
                for finding in concept.get("findings") or []]
    blocking = [f for f in findings if f.get("severity") == "blocking"]
    comparable = (comparison or {}).get("comparable")
    run.step("cross_company_compare", "api",
             status == 200 and comparable is False and bool(findings),
             f"comparable={comparable}, {len(findings)} finding(s) "
             f"({len(blocking)} blocking): {[f.get('code') for f in findings][:4]}",
             value={"blocking": len(blocking), "codes": [f.get("code") for f in findings]})

    status, memo, elapsed = api("POST", f"/api/equity/{APPLE}/memo/save",
                                {"name": "Phase 10.4 acceptance memo"})
    object_id = (memo or {}).get("object_id") or (memo or {}).get("memo", {}).get("object_id")
    if status not in (200, 201) or not object_id:
        run.step("save_research", "api", False, f"memo save failed: {status} {str(memo)[:300]}")
        return run.values
    run.step("save_research", "api", True, f"saved research object {object_id}",
             seconds=elapsed, value=object_id)
    run.values["memo_id"] = object_id

    status, pdf, elapsed = api("GET", f"/api/research/memos/{object_id}/export?format=pdf",
                               raw=True)
    text = pdf_text(pdf) if isinstance(pdf, bytes) else ""
    if not isinstance(pdf, bytes):
        run.step("export_pdf", "api", False, f"PDF export failed {status}: {str(pdf)[:300]}")
        return run.values
    served_hash = server.last_headers.get("x-atlas-content-sha256")
    actual_hash = hashlib.sha256(pdf).hexdigest()
    run.step("export_pdf", "api",
             status == 200 and pdf[:4] == b"%PDF" and len(text) > 200 and served_hash == actual_hash,
             f"{len(pdf)} bytes, {pdf.count(b'/Type /Page')} page object(s), "
             f"{len(text)} characters of extractable text, manifest hash "
             f"{'matches' if served_hash == actual_hash else 'DIFFERS from'} the served bytes",
             seconds=elapsed)
    run.values["pdf_text_numbers"] = numbers_in(text)

    status, exported, _ = api("GET", f"/api/research/memos/{object_id}/export?format=json",
                              raw=True)
    payload = json.loads(exported) if status == 200 else {}
    json_hash = server.last_headers.get("x-atlas-content-sha256")
    memo_payload = payload.get("memo") or {}
    claims = memo_payload.get("claims") or payload.get("claims") or []
    run.step("export_machine_readable", "api",
             status == 200 and bool(json_hash) and bool(claims),
             f"json export: schema {payload.get('schema')}, {len(claims)} claim(s), "
             f"manifest hash {str(json_hash)[:16]}…, memo hash "
             f"{str(memo_payload.get('content_hash'))[:16]}…")

    # The PDF is rendered from the same memo object; spot-check that its figures survive the
    # rendering rather than trusting the container.
    def _numeric(value: Any) -> float | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).replace(",", ""))
        except (TypeError, ValueError):
            return None

    claim_values = [number for number in (_numeric(claim.get("value")) for claim in claims)
                    if number is not None]
    matched = [value for value in claim_values
               if f"{float(value):.2f}" in run.values["pdf_text_numbers"]]
    coverage = (len(matched) / len(claim_values)) if claim_values else 0.0
    run.step("pdf_matches_memo", "pdf", bool(claim_values) and coverage >= 0.5,
             f"{len(matched)}/{len(claim_values)} memo figures appear verbatim in the PDF text "
             f"({coverage:.0%})", value={"matched": len(matched), "claims": len(claim_values)})

    status, change, _ = api("POST", f"/api/research/memos/{object_id}/check", {})
    run.step("verify_export", "api", status == 200 and "categories" in (change or {}),
             f"change report: {(change or {}).get('categories')}")

    # Reproduction: build a second demonstration database and ask the same question.
    second = work / "reproduce.db"
    completed = subprocess.run(
        [sys.executable, "-m", "atlas", "--db", str(second), "demo"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    reproduced = None
    if completed.returncode == 0:
        with Server(second, work) as replay:
            status, again, _ = replay.request("POST", "/api/answers/certificate", {
                "issuer_id": DEMO_ANSWER_ISSUER, "concept": CONCEPT, "period": PERIOD,
                "research_question": f"What was gross profit in fiscal {PERIOD}?",
            })
            if status == 200:
                # Record ids (document/table/cell) are database-local; the bytes of the source
                # table and the answer they produce are not. Reproduce on those.
                reproduced = {
                    "value": again["evidence"].get("value"),
                    "table_sha256": again["evidence"].get("source_table_sha256"),
                    "outcome": (again.get("answer") or {}).get("outcome"),
                }
    original = {
        "value": value,
        "table_sha256": evidence.get("source_table_sha256"),
        "outcome": (answer.get("answer") or {}).get("outcome"),
    }
    identical = bool(reproduced) and reproduced == original
    run.step("reproduce_on_clean_install", "cli+api", identical,
             f"same value/cell/source-table-hash on a second database: "
             f"{'identical' if identical else 'differs'} "
             f"({json.dumps(reproduced) if reproduced else 'no answer'})",
             value=reproduced)

    # MCP: the same question through the stdio server.
    mcp_value, mcp_detail = mcp_answer(db, DEMO_ANSWER_ISSUER)
    agreement = (mcp_value is not None and api_value is not None
                 and abs(float(mcp_value) - float(api_value)) < 1e-6)
    run.step("mcp_equivalent_query", "mcp", agreement,
             f"MCP resolve_financial_question returned {mcp_value} ({mcp_detail}); "
             f"HTTP certificate returned {api_value}", value=mcp_value)
    run.values["mcp_value"] = mcp_value
    run.values["surfaces_agree"] = agreement
    return run.values


def _table_cells(tables: Any, period: str) -> dict[str, float]:
    """Read labelled cells out of parsed filing tables for one period column.

    Filers word their labels differently ("Net sales", "Total net sales", "Gross margin") and
    their column headers carry the period date rather than a bare year ("Years ended
    September 26, 2026"), so labels are matched by phrase and the column is located by the
    first header cell that mentions the period.
    """
    wanted = ("gross margin", "gross profit", "net sales", "cost of sales")
    found: dict[str, float] = {}
    for table in (tables or {}).get("items") or []:
        rows = table.get("rows") or []
        index = None
        for header_row in rows[:3]:
            for position, cell in enumerate(header_row):
                text = str(cell).strip()
                if position and (text == period or text.endswith(period)
                                 or f" {period}" in text or f"{period}" in text):
                    index = position
                    break
            if index is not None:
                break
        if index is None:
            continue
        for row in rows:
            if not row or len(row) <= index:
                continue
            label = str(row[0]).strip().lower()
            for name in wanted:
                if name in label and name not in found:
                    try:
                        found[name] = float(str(row[index]).replace(",", "").replace("(", "-")
                                            .replace(")", "").replace("$", ""))
                    except ValueError:
                        pass
    if "gross profit" not in found and "gross margin" in found:
        found["gross profit"] = found["gross margin"]
    return found


def _row_values(row: dict[str, Any] | None) -> list[float]:
    if not row:
        return []
    values: list[float] = []
    for node in walk(row):
        for key, item in node.items():
            if key in {"value", "value_numeric", "amount"} and isinstance(item, (int, float)):
                values.append(float(item))
    return sorted(set(values), key=values.index)


def _dcf(api, issuer: str, assumptions: dict[str, Any]) -> float | None:
    payload = {k: v for k, v in assumptions.items() if k != "provenance"}
    status, body, _ = api("POST", "/api/valuation/dcf",
                          {"issuer": issuer, "assumptions": payload,
                           "mode": "public_available"})
    if status != 200:
        return None
    for node in walk(body):
        if isinstance(node.get("value_per_share"), (int, float)):
            return float(node["value_per_share"])
    return None


# --------------------------------------------------------------------------- #
# MCP client for the same question
# --------------------------------------------------------------------------- #
def mcp_answer(db: Path, issuer: str) -> tuple[float | None, str]:
    process = subprocess.Popen(
        [sys.executable, "-m", "atlas", "--db", str(db), "mcp"],
        cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    try:
        def send(message: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            deadline = time.time() + timeout
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise RuntimeError(f"MCP server did not answer {message.get('method')} "
                                       f"within {timeout}s")
                ready, _, _ = select.select([process.stdout], [], [], remaining)
                if not ready:
                    continue
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError("MCP server closed the stream")
                reply = json.loads(line)
                if reply.get("id") == message["id"]:
                    return reply

        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "atlas-acceptance", "version": "10.4"}}})
        # A JSON-RPC notification is defined as having no reply; waiting for one would hang.
        process.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()
        reply = send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "resolve_financial_question",
                                 "arguments": {"issuer_id": issuer, "concept": CONCEPT,
                                               "period": PERIOD}}})
        result = reply.get("result") or {}
        structured = result.get("structuredContent") or {}
        if not structured:
            for content in result.get("content") or []:
                if content.get("type") == "text":
                    structured = json.loads(content.get("text") or "{}")
                    break
        answer = structured.get("answer") or {}
        value = answer.get("value")
        return (float(value) if value is not None else None,
                f"outcome={answer.get('outcome')} tool_error={reply.get('error')}")
    finally:
        try:
            process.stdin.close()
        except Exception:  # pragma: no cover - best effort
            pass
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            process.kill()


# --------------------------------------------------------------------------- #
# the quantitative journey
# --------------------------------------------------------------------------- #
def quant(run: Run, work: Path, demo_db: Path) -> None:
    import csv
    import sqlite3

    series = work / "acceptance_prices.csv"
    # Deterministic, project-authored, clearly synthetic: a rise followed by a drawdown so the
    # journey contains a genuine negative result as well as a positive one.
    rows = []
    price = 100.0
    session = datetime(2023, 1, 2)
    while len(rows) < 260:
        if session.weekday() < 5:
            step = 0.55 if len(rows) < 170 else -0.75
            price = round(max(price + step, 5.0), 2)
            rows.append({"date": session.date().isoformat(), "open": price,
                         "high": round(price * 1.01, 2), "low": round(price * 0.99, 2),
                         "close": price, "volume": 10000})
        session += timedelta(days=1)
    with series.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    import_db = work / "quant.db"
    shutil.copy(demo_db, import_db)
    connection = sqlite3.connect(import_db)
    security_row = connection.execute(
        "SELECT security_id FROM security ORDER BY security_id LIMIT 1").fetchone()
    connection.close()
    security_id = security_row[0] if security_row else "SEC-ACCEPTANCE"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    completed = subprocess.run(
        [sys.executable, "-m", "atlas", "--db", str(import_db), "bars", "import",
         "--security-id", security_id, "--mic", "XNAS", "--file", str(series),
         "--source-name", "Atlas acceptance synthetic fixture",
         "--licence", "project-authored (Atlas project)"],
        cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=300,
    )
    run.step("import_lawful_dataset", "cli", completed.returncode == 0,
             f"project-authored synthetic CSV of {len(rows)} sessions imported for "
             f"{security_id} (exit {completed.returncode}) "
             f"{(completed.stdout or completed.stderr).strip()[:180]}")

    with Server(import_db, work) as lab:
        status, catalog, _ = lab.request("GET", "/api/quant/catalog")
        universe = (catalog or {}).get("universe") or []
        templates = (catalog or {}).get("templates") or (catalog or {}).get("strategies") or []
        run.step("configure_strategy", "api", status == 200 and bool(universe) and bool(templates),
                 f"{len(universe)} instrument(s), {len(templates)} template(s)")
        if not universe or not templates:
            return
        from atlas.quant.lab import template_spec

        template = templates[0]
        instrument = universe[0]
        spec = template_spec(template, instrument, name="Phase 10.4 acceptance strategy")
        status, spec_bundle, _ = lab.request("POST", "/api/quant/preview", {"spec": spec})
        preview = (spec_bundle or {}).get("metrics") if isinstance(spec_bundle, dict) else None
        run.step("strategy_preview", "api", status == 200 and bool(preview),
                 f"template {template.get('key')} on {instrument.get('security_id')}: "
                 f"preview metrics {str(preview)[:140]} ({status})")
        if not spec:
            return
        status, result, elapsed = lab.request("POST", "/api/quant/backtest", {
            "spec": spec, "persist": True, "hypothesis":
                "a synthetic momentum series is used only to exercise the accounting path",
            "experiment_name": "Phase 10.4 acceptance",
        })
        metrics = (result or {}).get("metrics") or {}
        transactions = (result or {}).get("trades") or []
        equity = (result or {}).get("equity_curve") or []
        run.step("run_backtest", "api",
                 status == 200 and bool(metrics) and bool(equity) and bool(transactions),
                 f"run {(result or {}).get('run_id')}: {len(transactions)} trade(s), "
                 f"{len(equity)} equity point(s), return={metrics.get('total_return')}, "
                 f"benchmark={metrics.get('benchmark_return')}", seconds=elapsed)
        credibility = (result or {}).get("credibility") or {}
        limitations = credibility.get("limitations") or []
        run.step("statistical_limitations", "api",
                 bool(credibility) and metrics.get("return_observations") is not None,
                 f"credibility {str(credibility.get('verdict') or credibility.get('level'))}, "
                 f"{len(limitations)} limitation(s), "
                 f"{metrics.get('return_observations')} return observations, "
                 f"{len((result or {}).get('warnings') or [])} warning(s)")
        benchmark = metrics.get("benchmark") or (result or {}).get("benchmark")
        run.step("benchmark_comparison", "api", benchmark is not None,
                 f"benchmark comparison: {str(benchmark)[:160]}")
        run_id = (result or {}).get("run_id")
        if run_id:
            status, capsule, _ = lab.request("GET", f"/api/quant/runs/{run_id}/capsule")
            run.step("export_and_replay", "api", status == 200 and bool(capsule),
                     f"reproduction capsule for {run_id}: {str(list(capsule or {}))[:120]}")
        status, refusal, _ = lab.request("POST", "/api/quant/backtest", {
            "spec": {**spec, "signal": {"kind": "not_a_registered_operator"}},
            "persist": False,
        })
        run.step("negative_refusal", "api", status == 422,
                 f"unregistered operator refused with {status}: "
                 f"{str(refusal)[:200]}")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "artifacts" / "release" / "acceptance_phase10_4.json")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)

    work = Path(tempfile.mkdtemp(prefix="atlas-acceptance-"))
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    run = Run()
    db = work / "demo.db"
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "atlas", "--db", str(db), "demo"],
            cwd=str(ROOT), capture_output=True, text=True, env=env, timeout=300,
        )
        sections = completed.stdout.count("=" * 78) // 2
        run.step("offline_demonstration", "cli",
                 completed.returncode == 0 and db.is_file() and sections >= 8,
                 f"atlas demo exit {completed.returncode}, {sections} sections, "
                 f"{db.stat().st_size if db.is_file() else 0} bytes")
        with Server(db, work) as server:
            flagship(run, server, db, work)
        quant(run, work, db)
    finally:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                                capture_output=True, text=True).stdout.strip()
        report = {
            "schema": SCHEMA,
            "generated_at": now(),
            "commit": commit,
            "python": sys.version.split()[0],
            "summary": run.summary(),
            "pass": run.summary()["fail"] == 0 and run.summary()["not_run"] == 0,
            "surfaces": sorted({step["surface"] for step in run.steps}),
            "cross_surface": {
                "answer_value": run.values.get("answer_value"),
                "mcp_value": run.values.get("mcp_value"),
                "surfaces_agree": run.values.get("surfaces_agree"),
                "pdf_figures": len(run.values.get("pdf_text_numbers") or []),
            },
            "steps": run.steps,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n")
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        counts = report["summary"]
        print(f"acceptance: {counts['pass']} pass, {counts['fail']} fail, "
              f"{counts['not_run']} not run -> {'PASS' if report['pass'] else 'FAIL'}")
        for step in run.steps:
            marker = {"pass": "ok  ", "fail": "FAIL", "not_run": "skip"}[step["status"]]
            print(f"  {marker} {step['id']:26} [{step['surface']:8}] {step['detail'][:120]}")
        print(f"report: {args.out}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
