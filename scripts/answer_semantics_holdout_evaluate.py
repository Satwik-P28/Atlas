"""First and only prospective scoring run of the frozen holdout cohort.

Order of operations, none of which may be skipped:

1. verify the preregistration (frozen inputs, committed blobs, resolution code, clean tree) and
   refuse to run on any drift;
2. ingest the archived bytes into a holdout-only database, verified against the source manifest
   digests before parsing;
3. run the existing baseline and geometry resolvers once, on the same questions, documents and
   environment, writing the unfiltered per-question results;
4. add the preregistered analysis (issuer table, paired comparison, issuer-cluster bootstrap,
   timing and cost) to the artifact.

It never overwrites an existing first-run artifact. Refusals, failures, false answers, citation
failures and unsupported answers are all kept: there is no performance gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research import answer_semantics, holdout  # noqa: E402
from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

FREEZE_CHECK = ROOT / "scripts" / "answer_semantics_holdout_freeze.py"


def _maxrss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def _git(*args: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def _ingest(manifest: dict[str, Any], snapshots: Path, db_path: Path) -> dict[str, Any]:
    """Ingest the archived bytes only after re-hashing them against the manifest."""
    started = time.perf_counter()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    database = Database(str(db_path))
    database.migrate()
    engine = KnowledgeEngine(database)
    if database.query_one("SELECT 1 FROM source WHERE source_id='sec-edgar'") is None:
        database.execute(
            "INSERT INTO source (source_id,name,kind,homepage,licence,redistribution,notes,created_at)"
            " VALUES ('sec-edgar','SEC EDGAR','sec_edgar','https://www.sec.gov',"
            "'Issuer-prepared SEC filing; access and reuse permitted under SEC web-site policy "
            "(fair access, no fee); not a work of U.S. federal employees, so 17 U.S.C. 105 does "
            "not apply and no public-domain status is asserted','user_responsibility',"
            "'issuer-prepared filings; SEC access-and-reuse terms, not federal authorship',?)",
            (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    ingested = 0
    for filing in manifest["filings"]:
        path = snapshots / f"{filing['accession']}.html"
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != filing["document_sha256"]:
            raise SystemExit(f"archived bytes changed before ingestion: {filing['accession']}")
        existing = database.query_one(
            "SELECT document_id FROM knowledge_document WHERE accession = ?",
            (filing["accession"],))
        if existing:
            continue
        row = database.query_one("SELECT issuer_id FROM issuer WHERE cik = ?", (filing["cik"],))
        issuer_id = row["issuer_id"] if row else f"ISS-CIK{filing['cik']}"
        if row is None:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            database.execute(
                "INSERT INTO issuer (issuer_id,cik,legal_name,entity_type,is_active,"
                "provenance_source,created_at,updated_at) VALUES (?,?,?,'company',1,'sec',?,?)",
                (issuer_id, filing["cik"], filing["issuer"], now, now))
        engine.ingest_document(
            issuer_id=issuer_id, accession=filing["accession"], form_type="10-K", html=payload,
            filed_date=filing["filed_date"], acceptance_time=filing["acceptance_time"],
            period_of_report=filing["period_of_report"],
            rights="user_responsibility",
            primary_document_url=filing["primary_document_url"])
        ingested += 1
    return {"ingest_ms": round((time.perf_counter() - started) * 1000, 3),
            "documents_ingested": ingested, "maxrss_mb_after_ingest": _maxrss_mb()}


def _failure_inventory(report: dict[str, Any], questions: dict[str, dict[str, Any]]) -> list[dict]:
    out = []
    for item in report["results"]:
        if item.get("status") in {"correct", "justified_abstention", "excluded"}:
            continue
        meta = questions[item["id"]]
        out.append({
            "id": item["id"], "runner": item["runner"], "status": item.get("status"),
            "reason": item.get("reason"), "detail": item.get("detail"),
            "issuer": meta["issuer"], "accession": meta["accession"],
            "question": meta["question"], "tags": meta.get("tags", []),
            "gold_class": item.get("gold_class"),
            "response": item.get("response"),
        })
    return out


def _refusals(report: dict[str, Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for runner in ("baseline", "geometry"):
        counter: Counter[str] = Counter()
        for item in report["results"]:
            if item["runner"] != runner or item.get("outcome") != "abstained":
                continue
            reason = str(item.get("reason") or "")
            head = reason.split(":")[0] or "unspecified"
            counter[head] += 1
        out[runner] = dict(sorted(counter.items()))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(holdout.OUTPUT_PATH))
    args = parser.parse_args(argv)
    output = Path(args.out)
    if output.exists():
        print(f"refusing to overwrite the first-run artifact: {output}", file=sys.stderr)
        print("reproduce it with scripts/answer_semantics_holdout_replay.py, or move the file "
              "aside deliberately and explain why in the report", file=sys.stderr)
        return 2
    check = subprocess.run([sys.executable, str(FREEZE_CHECK), "--check"],
                           capture_output=True, text=True)
    print(check.stdout.strip())
    if check.returncode != 0:
        print("the preregistration does not verify; the first run is refused", file=sys.stderr)
        return 3

    freeze = json.loads(holdout.FREEZE_PATH.read_text())
    manifest = json.loads(holdout.MANIFEST_PATH.read_text())
    questions_payload = json.loads(holdout.QUESTIONS_PATH.read_text())
    issuer_by_accession = {item["accession"]: item["issuer"] for item in
                           json.loads(holdout.CORPUS_PATH.read_text())["filings"]}
    questions = {item["id"]: {**item, "cik": item["issuer_cik"],
                              "issuer": issuer_by_accession[item["accession"]]}
                 for item in questions_payload["questions"]}
    started = time.perf_counter()
    before = _maxrss_mb()
    ingest = _ingest(manifest, holdout.SNAPSHOTS, holdout.DB_PATH)
    report = answer_semantics.run(
        output=output, db_path=holdout.DB_PATH, snapshots=holdout.SNAPSHOTS,
        questions_path=holdout.QUESTIONS_PATH, manifest_path=holdout.MANIFEST_PATH,
        facts_path=holdout.FACTS_PATH, corpus_path=holdout.CORPUS_PATH)
    wall_ms = round((time.perf_counter() - started) * 1000, 3)

    report["run"] = {
        "schema": "atlas.answer_semantics.holdout_run.v1",
        "cohort": "prospective-holdout-1",
        "run_ordinal": 1,
        "executed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gold_freeze_commit": _git("rev-parse", "HEAD"),
        "gold_freeze_status": freeze["status"],
        "gold_digest": freeze["gold_digest"],
        "protocol_version": freeze["protocol_version"],
        "evaluation_version": freeze["evaluation_version"],
        "code": freeze["code"],
        "selection_commitment": freeze["selection"]["plan_commitment"],
        "counts": freeze["counts"],
        "wall_ms": wall_ms,
        "ingest": ingest,
        "memory_mb": {"before": before, "after": _maxrss_mb()},
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
        "first_run_artifact": "preserved unfiltered; no performance gate applied",
    }
    report["analysis"] = {
        "issuers": holdout.issuer_table(report["results"], questions),
        "paired": holdout.paired_comparison(report["results"]),
        "cluster_bootstrap": holdout.cluster_bootstrap(report["results"], questions),
        "cost": holdout.amortised_cost(report["build_ms"], report["results"],
                                       ingest["ingest_ms"]),
        "refusal_reasons": _refusals(report),
        "failures": _failure_inventory(report, questions),
        "caveats": [
            "questions from one filing are correlated; issuer-level results are the honest unit",
            "twelve issuer clusters make any interval coarse",
            "timing is environment-specific and is not a correctness measure",
            "gold is single-author reviewed against two authorities, not independently annotated",
        ],
    }
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print("runner        answered  num%    cit%    exact%  precision  header  citfail  false  "
          "unsupported  median_ms")
    for runner, metrics in report["metrics"].items():
        print(f"{runner:12s}  {metrics['answered']:7d}  "
              f"{metrics['numerical_accuracy']}  {metrics['citation_accuracy']}  "
              f"{metrics['exact_answer_rate']}  {metrics['answer_precision']}  "
              f"{metrics['period_header_confirmed']}  {metrics['citation_failures']:7d}  "
              f"{metrics['false_answers']:5d}  {metrics['unsupported_confident_answers']:11d}  "
              f"{metrics['latency_ms']['median']}")
    print("statuses:", dict(sorted(Counter(item['status'] for item in report['results']).items())))
    print("artifact:", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
