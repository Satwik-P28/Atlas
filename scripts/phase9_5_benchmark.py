"""Phase 9.5 retrieval benchmark.

The question set is authored here, before the results are inspected, and scored by
mechanical rules: a question is a hit only when a retrieved passage contains every
required term; a historical query leaks if any returned document became available after
its cutoff. Reference answers are the filing sections the terms were authored from — not
model-generated questions.

Run:
    python scripts/phase9_5_benchmark.py --db var/phase9_5.db --out artifacts/phase9_5_benchmark.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.research.knowledge_claims import build_document_claim  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

# Pre-registered thresholds (declared before examining held-out results).
THRESHOLDS = {
    "hit_at_5": 0.70,
    "citation_support": 0.90,
    "future_leak": 0.0,
    "abstention_precision": 0.80,
}

QUESTIONS = [
    # Numerical disclosure question.
    {"key": "aapl-total-net-sales", "cik": "0000320193", "category": "numerical_disclosure",
     "question": "total net sales", "cutoff": "2026-11-10T00:00:00Z", "terms": ["net sales"]},
    {"key": "jpm-net-interest-income", "cik": "0000019617", "category": "numerical_disclosure",
     "question": "net interest income", "cutoff": "2026-11-10T00:00:00Z", "terms": ["net interest income"]},
    # Narrative business-risk question.
    {"key": "aapl-supply-chain-risk", "cik": "0000320193", "category": "narrative_risk",
     "question": "supply chain disruption risk", "cutoff": "2026-11-10T00:00:00Z",
     "terms": ["supply"]},
    {"key": "jpm-credit-risk", "cik": "0000019617", "category": "narrative_risk",
     "question": "credit risk concentration", "cutoff": "2026-11-10T00:00:00Z", "terms": ["credit risk"]},
    # Financial-table question.
    {"key": "aapl-segment-products", "cik": "0000320193", "category": "financial_table",
     "question": "iPhone net sales by segment", "cutoff": "2026-11-10T00:00:00Z", "terms": ["iPhone"]},
    {"key": "jpm-allowance-loans", "cik": "0000019617", "category": "financial_table",
     "question": "allowance for credit losses", "cutoff": "2026-11-10T00:00:00Z",
     "terms": ["allowance"]},
    # Multi-document synthesis (same question, both issuers must be reachable).
    {"key": "aapl-legal-proceedings", "cik": "0000320193", "category": "multi_document",
     "question": "legal proceedings", "cutoff": "2026-11-10T00:00:00Z", "terms": ["legal proceedings"]},
    # Historical cutoff: this must not return the FY2026 filing.
    # The FY2026 10-K was accepted in November 2026, so a June 2026 cutoff must return
    # only the earlier filing while still answering the question.
    {"key": "aapl-risk-as-of-2026-06", "cik": "0000320193", "category": "historical_cutoff",
     "question": "risk factors", "cutoff": "2026-06-01T00:00:00Z", "terms": ["risk"],
     "expect_no_newer_than": "2026-06-01T00:00:00Z"},
    {"key": "jpm-risk-as-of-2026-06", "cik": "0000019617", "category": "historical_cutoff",
     "question": "risk factors", "cutoff": "2026-06-01T00:00:00Z", "terms": ["risk"],
     "expect_no_newer_than": "2026-06-01T00:00:00Z"},
    # Same words, different financial meaning: "capital" appears in both a bank and a
    # hardware issuer; issuer scoping must keep them apart.
    {"key": "jpm-capital-scoped", "cik": "0000019617", "category": "disambiguation",
     "question": "regulatory capital ratios", "cutoff": "2026-11-10T00:00:00Z",
     "terms": ["capital"], "must_not_issuer": "0000320193"},
    # Negative evidence: a term that should not appear in this corpus.
    {"key": "aapl-crypto-mining", "cik": "0000320193", "category": "unanswerable",
     "question": "bitcoin mining rig depreciation schedule", "cutoff": "2026-11-10T00:00:00Z",
     "terms": ["bitcoin"], "answerable": False},
    {"key": "jpm-antarctic-subsidiary", "cik": "0000019617", "category": "unanswerable",
     "question": "antarctic penguin subsidiary revenue", "cutoff": "2026-11-10T00:00:00Z",
     "terms": ["penguin"], "answerable": False},
    # Amendment / version awareness: report whether an amended form is retrievable.
    {"key": "aapl-amendment-awareness", "cik": "0000320193", "category": "amendment_version",
     "question": "risk factors", "cutoff": "2026-11-10T00:00:00Z", "terms": ["risk"],
     "expect_amendment_report": True},
]


def resolve_issuer(db: Database, cik: str) -> str | None:
    row = db.query_one("SELECT issuer_id FROM issuer WHERE cik = ?", (cik.lstrip("0").zfill(10),))
    if row is None:
        row = db.query_one("SELECT issuer_id FROM issuer WHERE cik = ?", (cik,))
    return row["issuer_id"] if row else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="var/phase9_5.db")
    parser.add_argument("--out", default="artifacts/phase9_5_benchmark.json")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    db = Database(args.db)
    engine = KnowledgeEngine(db)
    page = db.scalar("PRAGMA page_count") or 0
    page_size = db.scalar("PRAGMA page_size") or 0
    rows = []
    latencies: list[float] = []
    for item in QUESTIONS:
        issuer_id = resolve_issuer(db, item["cik"])
        if issuer_id is None:
            rows.append({**item, "status": "issuer_not_indexed"})
            continue
        started = time.perf_counter()
        result = engine.search(item["question"], issuer_id=issuer_id, cutoff=item["cutoff"],
                               limit=args.limit)
        elapsed = (time.perf_counter() - started) * 1000
        latencies.append(elapsed)
        terms = [term.lower() for term in item["terms"]]
        hit = any(all(term in row["body"].lower() for term in terms)
                  for row in _bodies(db, result["results"]))
        leak = any(row["availability_time"] > (item.get("expect_no_newer_than") or "9999")
                   for row in result["results"])
        cross_issuer = any(row["issuer_id"] != issuer_id for row in result["results"])
        citation_ok = None
        if result["results"]:
            claim = build_document_claim(
                engine, issuer_id=issuer_id, cutoff=item["cutoff"], key=item["key"],
                question=item["question"], epistemic_status="observed_fact", limit=1,
            )
            citation_ok = claim["verification"]["outcome"] == "verified"
        answerable = item.get("answerable", True)
        rows.append({
            "key": item["key"], "category": item["category"], "issuer_id": issuer_id,
            "question": item["question"], "cutoff": item["cutoff"], "count": result["count"],
            "abstained": result["abstained"], "hit_at_k": hit, "future_leak": leak,
            "cross_issuer": cross_issuer, "citation_verified": citation_ok,
            "answerable": answerable, "latency_ms": round(elapsed, 2),
            "top": [{"unit_id": r["unit_id"], "accession": r["accession"],
                     "section": r["section_path"][:80], "relevance": r["relevance"]}
                    for r in result["results"][:3]],
        })
    answerable = [row for row in rows if row.get("answerable", True) and row.get("count") is not None]
    negative = [row for row in rows if row.get("answerable") is False]
    hits = [row for row in answerable if row["hit_at_k"]]
    citations = [row for row in rows if row.get("citation_verified") is not None]
    leaks = [row for row in rows if row.get("future_leak")]
    cross = [row for row in rows if row.get("cross_issuer")]
    abstained_negative = [row for row in negative if row["abstained"]]
    false_abstention = [row for row in answerable if row["abstained"]]
    metrics = {
        "questions": len(QUESTIONS),
        "scored_answerable": len(answerable),
        "hit_at_5": round(len(hits) / len(answerable), 4) if answerable else None,
        "citation_support": round(
            len([row for row in citations if row["citation_verified"]]) / len(citations), 4
        ) if citations else None,
        "future_leak_rate": round(len(leaks) / len(rows), 4) if rows else None,
        "cross_issuer_rate": round(len(cross) / len(rows), 4) if rows else None,
        "abstention_recall_unanswerable": round(
            len(abstained_negative) / len(negative), 4) if negative else None,
        "answerable_abstention_rate": round(
            len(false_abstention) / len(answerable), 4) if answerable else None,
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2) if latencies else None,
            "p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2)
            if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
        },
        "index": {"database_bytes": int(page) * int(page_size),
                  "documents": engine.stats()["documents"], "passages": engine.stats()["units"],
                  "tables": engine.stats()["tables"]},
    }
    gates = {
        "hit_at_5": metrics["hit_at_5"] is not None and metrics["hit_at_5"] >= THRESHOLDS["hit_at_5"],
        "citation_support": (metrics["citation_support"] or 0) >= THRESHOLDS["citation_support"],
        "no_future_leak": metrics["future_leak_rate"] == THRESHOLDS["future_leak"],
        "abstention": (metrics["abstention_recall_unanswerable"] or 0)
        >= THRESHOLDS["abstention_precision"],
    }
    payload = {"schema": "atlas.knowledge.benchmark.v1", "baseline": "sqlite-fts5-bm25",
               "thresholds": THRESHOLDS, "metrics": metrics, "gates": gates, "rows": rows,
               "limitations": [
                   "14 authored questions over 6 documents; small-sample and not independent.",
                   "No embedding or LLM baseline was evaluated, so no retrieval architecture "
                   "comparison is claimed.",
                   "Scoring is term-presence at passage level, not human-judged answer correctness.",
               ]}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"metrics": metrics, "gates": gates}, indent=2))
    return 0 if all(gates.values()) else 1


def _bodies(db: Database, results: list[dict]) -> list[dict]:
    out = []
    for result in results:
        row = db.query_one("SELECT body FROM knowledge_unit WHERE unit_id = ?", (result["unit_id"],))
        out.append({"body": row["body"] if row else "", **result})
    return out


if __name__ == "__main__":
    raise SystemExit(main())
