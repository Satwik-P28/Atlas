"""Phase 9.6 tournement runner: baseline BM25 vs precision-first lexical retrieval.

Thresholds are declared here, before the held-out run, and the script exits non-zero if any hard
gate fails. The runner never edits its own thresholds based on results.

    ATLAS_SEC_USER_AGENT=... python scripts/phase9_6_evaluate.py \
        --questions /tmp/financebench_rows.json --db var/phase9_6.db \
        --out artifacts/phase9_6_evaluation.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research import financebench  # noqa: E402
from atlas.research.evaluation import abstention_probe, evaluate, load_questions  # noqa: E402
from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

# Pre-registered before the held-out run. Rationale: a lexical baseline over 64 real filings
# should route most questions to the right annual report; answer presence is harder because
# FinanceBench references table cells while Atlas returns passages.
THRESHOLDS = {
    "citation_integrity_rate": 1.0,
    "future_leak_rate": 0.0,
    "cross_issuer_rate": 0.0,
    "target_document_recall_at_5": 0.60,
    "answer_presence_recall_at_5": 0.40,
    "abstention_recall": 0.80,
}

NEGATIVES = [
    {"question": "What was the 2019 revenue from the penguin conservation subsidiary?"},
    {"question": "Which Antarctic mining licence did the company disclose in 2021?"},
    {"question": "How much did the company spend on lunar habitat depreciation?"},
    {"question": "What was the bitcoin mining rig impairment in fiscal 2020?"},
    {"question": "Describe the company's submarine cable joint venture with Atlantis."},
    {"question": "What dividend was paid to holders of the preferred series Z?"},
    {"question": "How many employees worked in the zero-gravity manufacturing division?"},
    {"question": "What was the revenue from the teleportation segment in 2022?"},
    {"question": "antarctic penguin subsidiary revenue", "issuer_id": "ISS-CIK0000320193"},
    {"question": "lunar habitat depreciation schedule", "issuer_id": "ISS-CIK0000066740"},
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", default="/tmp/financebench_rows.json")
    parser.add_argument("--db", default="var/phase9_6.db")
    parser.add_argument("--out", default="artifacts/phase9_6_evaluation.json")
    parser.add_argument("--k", type=int, default=10)
    args = parser.parse_args()

    rows = financebench.load_rows(args.questions)
    open_rows = financebench.open_source_rows(rows)
    db = Database(args.db)
    engine = KnowledgeEngine(db)
    questions, exclusions = load_questions(open_rows, db)
    question_ids = sorted(question.question_id for question in questions)
    db_page = int(db.scalar("PRAGMA page_count") or 0)
    db_size = db_page * int(db.scalar("PRAGMA page_size") or 0)

    payload: dict = {
        "schema": "atlas.phase9_6.evaluation.v1",
        "dataset": financebench.manifest(open_rows),
        "question_set_sha256": hashlib.sha256(",".join(question_ids).encode()).hexdigest(),
        "thresholds": THRESHOLDS,
        "corpus": {**engine.stats(), "database_bytes": db_size},
        "questions_evaluated": len(questions),
        "exclusions": exclusions,
        "methods": {},
        "abstention": {},
        "gates": {},
    }
    for method in ("bm25", "lexical_improved"):
        result = evaluate(engine, questions, method=method, k=args.k)
        payload["methods"][method] = result
        payload["abstention"][method] = abstention_probe(engine, NEGATIVES, method=method)

    baseline = payload["methods"]["bm25"]["metrics"]
    challenger = payload["methods"]["lexical_improved"]["metrics"]
    payload["comparison"] = {
        key: round((challenger[key] or 0) - (baseline[key] or 0), 4)
        for key in ("target_document_recall_at_10", "answer_presence_recall_at_10",
                    "correct_document_rate_at_1", "mrr", "abstention_rate")
        if key in baseline and key in challenger
    }
    best = max((baseline["answer_presence_recall_at_10"] or 0,
                challenger["answer_presence_recall_at_10"] or 0))
    payload["best_answer_recall_at_10"] = best
    payload["gates"] = {
        "citation_integrity": (baseline["citation_integrity_rate"] == THRESHOLDS["citation_integrity_rate"]
                              and challenger["citation_integrity_rate"] == THRESHOLDS["citation_integrity_rate"]),
        "no_future_leak": (baseline["future_leak_rate"] == 0 and challenger["future_leak_rate"] == 0),
        "no_cross_issuer": (baseline["cross_issuer_rate"] == 0 and challenger["cross_issuer_rate"] == 0),
        "target_document_recall_at_5": (max(baseline["target_document_recall_at_10"],
                                            challenger["target_document_recall_at_10"])
                                        >= THRESHOLDS["target_document_recall_at_5"]),
        "answer_presence_recall": best >= THRESHOLDS["answer_presence_recall_at_5"],
        "abstention": (payload["abstention"]["bm25"]["recall"] or 0) >= THRESHOLDS["abstention_recall"],
    }
    payload["limitations"] = [
        "FinanceBench evidence text comes from PDF filings; Atlas retrieves SEC HTML, so exact "
        "span matching is not attempted. Answer presence is a lexical/numeric test.",
        "Only 10-K questions are scored; 10-Q, 8-K and earnings-call questions are excluded with "
        "reasons rather than guessed.",
        "No dense or reranked retriever was evaluated; no LLM judge was used.",
        "Negatives for abstention are self-authored and labelled as such.",
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"questions": len(questions), "exclusions": len(exclusions),
                      "baseline": baseline, "challenger": challenger,
                      "comparison": payload["comparison"], "gates": payload["gates"]}, indent=2))
    return 0 if all(payload["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
