"""Phase 10.5 flagship acceptance on a real company filing.

The Phase 10.4 acceptance uses a project-authored synthetic 10-K so it can run offline and
deterministically. This harness is its real-data counterpart: it initialises a database, syncs
Apple Inc. from SEC EDGAR with the caller's contact identity, downloads the latest 10-K from
SEC Archives, parses it, and then drives the research journey a user is promised — answer,
certificate, independent verification, historical availability, valuation, scenarios, memo,
PDF, structured export, verification, MCP agreement and reproduction on a second installation.

What it does with the filing: nothing is committed. The HTML is fetched into a temporary
directory at run time, ingested into a temporary database, and deleted with it. SEC filings are
public records; this harness still does not redistribute them.

Usage::

    ATLAS_SEC_USER_AGENT="Your Name you@example.org" \
        python scripts/accept_real_filing_phase10_5.py --out artifacts/release/acceptance_real_filing.json

SEC requires a descriptive User-Agent with a contact address. Without one the run stops and the
report says so; it does not fall back to a placeholder identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from accept_phase10_4 import (  # noqa: E402
    DEMO_ANSWER_ISSUER,
    Run,
    Server,
    _table_cells,
    numbers_in,
    pdf_text,
)

SCHEMA = "atlas.acceptance.real_filing.v1"
CIK = "0000320193"
CONCEPT = "revenue"
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def user_agent() -> str:
    value = os.environ.get("ATLAS_SEC_USER_AGENT", "").strip()
    return value


def fetch(url: str, agent: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": agent, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    import gzip
    try:
        return gzip.decompress(payload)
    except OSError:
        return payload


def run_cli(*arguments: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "atlas", *arguments],
                          cwd=str(ROOT), capture_output=True, text=True,
                          env={**ENV, "ATLAS_SEC_USER_AGENT": user_agent()}, timeout=timeout)


def latest_ten_k(agent: str) -> dict[str, Any]:
    submissions = json.loads(fetch(f"https://data.sec.gov/submissions/CIK{CIK}.json", agent))
    recent = submissions["filings"]["recent"]
    for index, form in enumerate(recent["form"]):
        if form == "10-K":
            accession = recent["accessionNumber"][index]
            document = recent["primaryDocument"][index]
            return {
                "accession": accession,
                "document": document,
                "filed_date": recent["filingDate"][index],
                "period_of_report": recent["reportDate"][index],
                "acceptance_time": recent.get("acceptanceDateTime", [None] * len(recent["form"]))[index],
                "url": ("https://www.sec.gov/Archives/edgar/data/"
                        f"{int(CIK)}/{accession.replace('-', '')}/{document}"),
                "company": submissions.get("name"),
            }
    raise RuntimeError("no 10-K in the submissions archive")


def ingest_filing(db_path: Path, filing: dict[str, Any], agent: str, work: Path) -> dict[str, Any]:
    from atlas.research.knowledge import KnowledgeEngine
    from atlas.storage.db import Database

    cache = work / f"{filing['accession']}.html"
    if cache.is_file():
        payload = cache.read_bytes()
    else:
        payload = fetch(filing["url"], agent)
        cache.write_bytes(payload)
    database = Database(str(db_path))
    try:
        issuer = database.query_one("SELECT issuer_id FROM issuer WHERE cik = ?", (CIK.lstrip("0"),))
        if issuer is None:
            issuer = database.query_one("SELECT issuer_id FROM issuer WHERE cik = ?", (CIK,))
        engine = KnowledgeEngine(database)
        document = engine.ingest_document(
            issuer_id=issuer["issuer_id"],
            accession=filing["accession"],
            form_type="10-K",
            html=payload,
            filed_date=filing["filed_date"],
            acceptance_time=filing["acceptance_time"],
            period_of_report=filing["period_of_report"],
            # The filing is a public record, but the project does not claim a right to
            # republish the publisher's document: it stores what it parses locally and marks
            # the document as the operator's responsibility. That is the honest class.
            rights="user_responsibility",
            primary_document_url=filing["url"],
            notes="fetched from SEC Archives for the Phase 10.5 acceptance run",
        )
        return {
            "document_id": document["document_id"],
            "sha256": document["sha256"],
            "bytes": len(payload),
            "tables": document["table_count"],
            "units": document["unit_count"],
            "availability_precision": document["availability_precision"],
            "availability_time": document["availability_time"],
        }
    finally:
        database.close()


def mcp_answer(db: Path, issuer: str, period: str) -> tuple[float | None, str]:
    process = subprocess.Popen([sys.executable, "-m", "atlas", "--db", str(db), "mcp"],
                               cwd=str(ROOT), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=ENV)
    try:
        def call(message: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
            process.stdin.write(json.dumps(message) + "\n")
            process.stdin.flush()
            deadline = time.time() + timeout
            import select
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise RuntimeError("MCP server did not answer")
                ready, _, _ = select.select([process.stdout], [], [], remaining)
                if not ready:
                    continue
                reply = json.loads(process.stdout.readline())
                if reply.get("id") == message["id"]:
                    return reply

        call({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "atlas-real-acceptance", "version": "10.5"}}})
        process.stdin.write(json.dumps({"jsonrpc": "2.0",
                                        "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()
        reply = call({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "resolve_financial_question",
                                 "arguments": {"issuer_id": issuer, "concept": CONCEPT,
                                               "period": period}}})
        result = reply.get("result") or {}
        structured = result.get("structuredContent") or {}
        if not structured:
            for item in result.get("content") or []:
                if item.get("type") == "text":
                    structured = json.loads(item.get("text") or "{}")
                    break
        answer = structured.get("answer") or {}
        value = answer.get("value")
        return (float(value) if value is not None else None,
                f"outcome={answer.get('outcome')} error={reply.get('error')}")
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


def journey(run: Run, db: Path, filing: dict[str, Any], work: Path,
            *, label: str) -> dict[str, Any]:
    from atlas.core.temporal import iso, utcnow

    started = time.perf_counter()
    ingested = ingest_filing(db, filing, user_agent(), work)
    run.step(f"{label}_ingest_10k", "cli+parsed",
             ingested["tables"] > 0 and ingested["units"] > 0,
             f"{filing['accession']} ({filing['document']}, filed {filing['filed_date']}) "
             f"{ingested['bytes']} bytes parsed into {ingested['tables']} tables / "
             f"{ingested['units']} units in {time.perf_counter() - started:.1f} s",
             seconds=time.perf_counter() - started, value=ingested)

    with Server(db, work) as server:
        api = server.request
        status, health, _ = api("GET", "/api/health")
        run.step(f"{label}_health", "api", status == 200 and health.get("status") == "ok",
                 f"/api/health {status}, evidence={health.get('evidence')}, "
                 f"issuers={health.get('issuers')}")

        status, search, _ = api("GET", "/api/search?q=apple&limit=5")
        items = (search or {}).get("items") or []
        issuer_id = items[0].get("issuer_id") if items else None
        run.step(f"{label}_company_selection", "api", status == 200 and bool(issuer_id),
                 f"palette returned {len(items)} match(es); selected {issuer_id}")
        if not issuer_id:
            return {}

        status, company, _ = api("GET", f"/api/companies/{issuer_id}")
        run.step(f"{label}_company_detail", "api", status == 200,
                 f"{company.get('legal_name') or (company.get('issuer') or {}).get('legal_name')}")

        status, statements, _ = api("GET", f"/api/companies/{issuer_id}/statements")
        columns = (statements or {}).get("columns") or []
        run.step(f"{label}_statements", "api", status == 200 and bool(columns),
                 f"{len(columns)} period column(s) from synced XBRL facts")

        status, filings, _ = api("GET", f"/api/companies/{issuer_id}/filings")
        rows = (filings or {}).get("items") or []
        run.step(f"{label}_filing_list", "api", status == 200 and bool(rows),
                 f"{len(rows)} filing(s) recorded")

        status, documents, _ = api("GET", f"/api/knowledge/documents?issuer_id={issuer_id}")
        documents = (documents or {}).get("items") or []
        parsed = [d for d in documents if d.get("accession") == filing["accession"]]
        run.step(f"{label}_narrative_evidence", "api", bool(parsed),
                 f"{len(documents)} parsed document(s); the real 10-K is "
                 f"{'present' if parsed else 'absent'} with "
                 f"{parsed[0].get('table_count') if parsed else 0} tables")

        period = str(filing["period_of_report"])[:4]
        status, answer, elapsed = api("POST", "/api/answers/certificate", {
            "issuer_id": issuer_id, "concept": CONCEPT, "period": period,
            "research_question": f"What was total net sales in fiscal {period}?",
        })
        if status != 200:
            run.step(f"{label}_answer", "api", False,
                     f"refused {status}: {str(answer)[:300]}")
            return {}
        evidence = answer["evidence"]
        value = float(evidence["value"])
        run.step(f"{label}_answer", "api", True,
                 f"{evidence.get('row_label')} {evidence.get('period')} = "
                 f"{evidence.get('value')} {evidence.get('currency')} "
                 f"from {evidence.get('statement_title')}", seconds=elapsed, value=value)

        status, verdict, _ = api("POST", "/api/certificates/verify",
                                 {"certificate": answer["certificate"]})
        report = (verdict or {}).get("verification") or verdict or {}
        run.step(f"{label}_certificate_verify", "api", status == 200,
                 f"independent verification: {str(report)[:180]}")

        availability = answer.get("availability") or {}
        run.step(f"{label}_availability_contract", "api",
                 availability.get("is_estimated") is True
                 and availability.get("availability_precision") in {"unknown", "date", "exact"}
                 and "not an observed instant" in (availability.get("note") or ""),
                 f"precision={availability.get('availability_precision')}, "
                 f"estimated={availability.get('is_estimated')}, "
                 f"time={availability.get('availability_time')}")

        # The answer is bound to one cell of one parsed table unit. Read that unit back and
        # recompute a line that is an identity inside it: the segment rows sum to total net
        # sales. (Gross margin spans two tables in this filing, so it cannot be recomputed
        # from one unit and is deliberately not used here.)
        status, unit, _ = api("GET", f"/api/knowledge/units/{evidence['unit_id']}")
        segments, total = _segment_sum(unit.get("body") or "", "total net sales")
        run.step(f"{label}_arithmetic", "knowledge",
                 total is not None and segments is not None
                 and abs(segments - total) < 1e-6 and abs(total - value) < 1e-6,
                 f"parsed unit: segment rows sum to {segments}; the table's own Total net "
                 f"sales is {total}; certificate {value}")

        quality = evidence.get("citation_quality")
        agrees = evidence.get("column_label_agrees_with_period")
        run.step(f"{label}_citation_quality", "api",
                 quality == "exact" and agrees is True,
                 f"citation quality '{quality}' (column label {evidence.get('column_label')!r} "
                 f"vs resolved period {evidence.get('period')!r}, agrees={agrees}); the cited "
                 f"column prints the period the answer is bound to")

        status, defaults, _ = api("GET", f"/api/valuation/defaults/{issuer_id}")
        assumptions = (defaults or {}).get("defaults") or {}
        base = _dcf(api, issuer_id, assumptions)
        run.step(f"{label}_valuation", "api", base is not None,
                 f"DCF value per share {base} from synced facts", value=base)
        higher = dict(assumptions, wacc=round(float(assumptions.get("wacc", 0.09)) + 0.02, 4))
        worse = _dcf(api, issuer_id, higher)
        run.step(f"{label}_scenario_change", "api", base is not None and worse is not None and worse < base,
                 f"wacc {assumptions.get('wacc')} -> {higher['wacc']}: {base} -> {worse}")

        status, comparison, _ = api("POST", "/api/research/comparison", {
            "issuers": [issuer_id, DEMO_ANSWER_ISSUER], "concepts": [CONCEPT],
            "period": period,
        })
        findings = [f for concept in ((comparison or {}).get("concepts") or [])
                    for f in concept.get("findings") or []]
        run.step(f"{label}_comparison_refusal", "api",
                 status == 200 and (comparison or {}).get("comparable") is False and bool(findings),
                 f"comparison refused with {len(findings)} finding(s): "
                 f"{[f.get('code') for f in findings][:3]} (a synthetic issuer cannot be "
                 f"compared with a real one)")

        status, memo, elapsed = api("POST", f"/api/equity/{issuer_id}/memo/save",
                                    {"name": f"Apple FY{period} acceptance memo"})
        object_id = (memo or {}).get("object_id")
        run.step(f"{label}_memo_save", "api", status in (200, 201) and bool(object_id),
                 f"saved memo {object_id} in {elapsed:.2f} s")

        status, pdf, _ = api("GET", f"/api/research/memos/{object_id}/export?format=pdf", raw=True)
        text = pdf_text(pdf) if isinstance(pdf, bytes) else ""
        served = server.last_headers.get("x-atlas-content-sha256")
        run.step(f"{label}_pdf_export", "api",
                 isinstance(pdf, bytes) and pdf[:4] == b"%PDF" and len(text) > 1000
                 and served == hashlib.sha256(pdf).hexdigest(),
                 f"{len(pdf)} bytes, {len(text)} extractable characters, manifest hash "
                 f"{'matches' if served == hashlib.sha256(pdf).hexdigest() else 'differs'}")
        run.values["pdf_numbers"] = numbers_in(text)

        status, exported, _ = api("GET", f"/api/research/memos/{object_id}/export?format=json",
                                  raw=True)
        payload = json.loads(exported) if status == 200 else {}
        claims = (payload.get("memo") or {}).get("claims") or []
        numeric = [float(c["value"]) for c in claims
                   if isinstance(c.get("value"), (int, float)) or
                   (isinstance(c.get("value"), str) and c["value"].replace(".", "", 1).isdigit())]
        matched = [v for v in numeric if f"{v:.2f}" in run.values["pdf_numbers"]]
        run.step(f"{label}_structured_export", "api", status == 200 and bool(claims),
                 f"{len(claims)} claim(s); {len(matched)}/{len(numeric)} numeric figures "
                 f"appear in the PDF text")

        status, change, _ = api("POST", f"/api/research/memos/{object_id}/check", {})
        run.step(f"{label}_export_verification", "api", status == 200,
                 f"change report categories {(change or {}).get('categories')}")

        mcp_value, detail = mcp_answer(db, issuer_id, period)
        run.step(f"{label}_mcp", "mcp", mcp_value is not None and abs(mcp_value - value) < 1e-6,
                 f"MCP returned {mcp_value} ({detail}); API certificate returned {value}")

        snapshot = {
            "value": evidence.get("value"),
            "table_sha256": evidence.get("source_table_sha256"),
            "document_sha256": ingested["sha256"],
            "issuer_id": issuer_id,
            "period": period,
        }
    return snapshot


_YEAR = __import__("re").compile(r"(?:19|20)\d{2}")


def _segment_sum(body: str, total_label: str) -> tuple[float | None, float | None]:
    """Sum the component rows printed directly above a total row of one parsed table unit.

    Table text arrives as pipe-separated rows. The components of a total are the contiguous
    valued rows immediately above it; the first unvalued row (a banner such as "Net sales:")
    ends the block. This reads layout rather than issuer vocabulary, so a filer that breaks
    revenue into products and services and one that breaks it into geographies both work.
    """
    def numbers(line: str) -> list[float]:
        values: list[float] = []
        for cell in line.split("|"):
            token = cell.strip().replace("$", "").replace(",", "").replace("%", "")
            if not token or token in {"(", ")"}:
                continue
            try:
                values.append(float(token))
            except ValueError:
                continue
        return values

    rows: list[tuple[str, list[float]]] = []
    for line in body.splitlines():
        label = line.split("|")[0].strip().lower()
        if not label:
            continue
        rows.append((label, numbers(line)))
    total: float | None = None
    total_index = None
    for index, (label, values) in enumerate(rows):
        if label == total_label and values:
            total, total_index = values[0], index
    if total_index is None:
        return None, total
    components: list[float] = []
    for label, values in reversed(rows[:total_index]):
        if not values or label.startswith(("total", "subtotal")) or _YEAR.fullmatch(label):
            # A banner, another total or the period header ends the block: the components of a
            # total are the rows between it and the previous heading.
            break
        components.append(values[0])
    components.reverse()
    return (sum(components) if len(components) >= 2 else None), total



def _dcf(api, issuer: str, assumptions: dict[str, Any]) -> float | None:
    payload = {k: v for k, v in assumptions.items() if k != "provenance"}
    status, body, _ = api("POST", "/api/valuation/dcf",
                          {"issuer": issuer, "assumptions": payload, "mode": "public_available"})
    if status != 200:
        return None
    for node in _walk(body):
        if isinstance(node.get("value_per_share"), (int, float)):
            return float(node["value_per_share"])
    return None


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "artifacts" / "release" / "acceptance_real_filing.json")
    args = parser.parse_args(argv)

    run = Run()
    work = Path(tempfile.mkdtemp(prefix="atlas-real-"))
    agent = user_agent()
    report: dict[str, Any] = {}
    try:
        if not agent:
            run.skip("sec_contact_identity", "network",
                     "ATLAS_SEC_USER_AGENT is not set; SEC requires a contact identity, so the "
                     "live acquisition was not attempted and no result is claimed")
            return _finish(run, args.out, work, {"limitation": "no SEC contact identity"})
        run.step("sec_contact_identity", "config", "@" in agent,
                 f"using the configured SEC contact identity: {agent}")

        primary = work / "primary.db"
        init = run_cli("--db", str(primary), "init")
        run.step("primary_init", "cli", init.returncode == 0,
                 f"atlas init exit {init.returncode}")

        started = time.perf_counter()
        sync = run_cli("--db", str(primary), "sec", "sync", "--cik", CIK, "--no-history")
        summary = ""
        if sync.returncode == 0:
            try:
                summary = (json.loads(sync.stdout).get("summary") or "")[:180]
            except json.JSONDecodeError:
                summary = sync.stdout.strip()[:180]
        run.step("sec_sync_live", "cli", sync.returncode == 0 and "issuer" in summary,
                 f"live sync exit {sync.returncode} in {time.perf_counter() - started:.1f} s: "
                 f"{summary or sync.stderr.strip()[:200]}", seconds=time.perf_counter() - started)
        if sync.returncode != 0:
            return _finish(run, args.out, work, {"limitation": "sec sync failed"})

        filing = latest_ten_k(agent)
        run.step("sec_filing_selected", "network", True,
                 f"{filing['company']} 10-K {filing['accession']} for period "
                 f"{filing['period_of_report']}, filed {filing['filed_date']}, "
                 f"{filing['url']}")

        snapshot = journey(run, primary, filing, work, label="real")

        # Reproduction on a second installation: same steps, fresh database.
        secondary = work / "secondary.db"
        run_cli("--db", str(secondary), "init")
        run_cli("--db", str(secondary), "sec", "sync", "--cik", CIK, "--no-history")
        replay = journey(run, secondary, filing, work, label="replay")
        identical = bool(snapshot) and bool(replay) and snapshot == replay
        run.step("real_reproduction", "cli+api", identical,
                 f"second installation reproduced value/table/document hash: "
                 f"{'identical' if identical else 'differs'} "
                 f"({json.dumps(replay)[:220] if replay else 'no answer'})",
                 value=replay)
        report = {"primary": snapshot, "replay": replay,
                  "filing": {k: v for k, v in filing.items() if k != "url"}}
    finally:
        pass
    return _finish(run, args.out, work, report)


def _finish(run: Run, out: Path, work: Path, extra: dict[str, Any]) -> int:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                            capture_output=True, text=True).stdout.strip()
    summary = run.summary()
    report = {
        "schema": SCHEMA,
        "generated_at": now(),
        "commit": commit,
        "python": sys.version.split()[0],
        "issuer": "Apple Inc. (CIK 0000320193)",
        "data_source": "SEC EDGAR live acquisition; the filing HTML is not stored in the repository",
        "summary": summary,
        "pass": summary["fail"] == 0 and summary["not_run"] == 0 and summary["pass"] > 0,
        "steps": run.steps,
        **extra,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(f"real filing acceptance: {summary['pass']} pass, {summary['fail']} fail, "
          f"{summary['not_run']} not run -> {'PASS' if report['pass'] else 'FAIL'}")
    for step in run.steps:
        marker = {"pass": "ok  ", "fail": "FAIL", "not_run": "skip"}[step["status"]]
        print(f"  {marker} {step['id']:34} {step['detail'][:130]}")
    print(f"report: {out}")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
