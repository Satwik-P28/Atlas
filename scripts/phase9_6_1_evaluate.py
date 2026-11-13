"""Phase 9.6.1 evaluation runner: methodology version 9.6.1.

Writes two artifacts from one run:

* ``artifacts/phase9_6_1_evaluation.json`` — sanitized: identifiers, ranks, flags, counts,
  metric values and a rights-safe fingerprint. Safe to commit.
* ``var/phase9_6_1_eval_trace.json`` — full local trace, including the licensed question and
  answer text, for reproduction. Never committed; a guard test enforces that.

Thresholds are declared before the run and are version-specific. The Phase 9.6.0 thresholds and
scores are unchanged; this is a separate evaluation, not a retroactive pass.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research import financebench  # noqa: E402
from atlas.research import evaluation_v2 as ev  # noqa: E402
from atlas.research.evaluation import load_questions  # noqa: E402
from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

METHODOLOGY_VERSION = "9.6.1"
THRESHOLDS = {
    "citation_integrity": 1.0,
    "issuer_integrity": 1.0,
    "future_leak_rate": 0.0,
    "cross_issuer_rate": 0.0,
    "document_recall@5": 0.60,
    "answer_presence@5": 0.40,
    "abstention_precision": 0.80,
    "abstention_recall": 0.70,
    "false_abstention_rate": 0.10,
}

# Development negatives: used to compare policies. Fixed before the holdout was run.
DEV_NEGATIVES = [
    "What was the 2019 revenue from the penguin conservation subsidiary?",
    "Which Antarctic mining licence did the company disclose in 2021?",
    "How much did the company spend on lunar habitat depreciation?",
    "What was the bitcoin mining rig impairment in fiscal 2020?",
    "Describe the company's submarine cable joint venture with Atlantis.",
    "What dividend was paid to holders of the preferred series Z?",
    "How many employees worked in the zero-gravity manufacturing division?",
    "What was the revenue from the teleportation segment in 2022?",
]

# Holdout negatives: authored but not inspected or used while choosing the policy. Run once.
HOLDOUT_NEGATIVES = [
    "What were the costs of the orbital launch pad in fiscal 2019?",
    "How much goodwill was attributed to the dragon fruit beverage division?",
    "What was the volcanic ash remediation provision at year end?",
    "Which director resigned over the antarctic drilling programme?",
    "How many shares were issued to the moon base pension trust?",
    "What was the impairment of the telepathic interface patent?",
    "What rent did the company pay for its underwater data centre?",
    "What was the fair value of the lithium unicorn warrant?",
]

POLICIES = ("term_absence", "coverage")


def fetch_rows(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def main() -> int:
    rows_path = Path("/tmp/financebench_rows.json")
    rows = financebench.open_source_rows(fetch_rows(rows_path))
    db = Database("var/phase9_6.db")
    engine = KnowledgeEngine(db)
    questions, exclusions = load_questions(rows, db)
    rows_by_id = {str(row["financebench_id"]): row for row in rows}
    config = {
        "methodology_version": METHODOLOGY_VERSION,
        "k": 10,
        "policy": "public_available",
        "support_policy": "balanced",
        "metrics": sorted(THRESHOLDS),
        "question_count": len(questions),
        "exclusion_count": len(exclusions),
    }
    payload: dict = {
        "schema": "atlas.phase9_6_1.evaluation.v1",
        "methodology_version": METHODOLOGY_VERSION,
        "retrieval_version": ev.RETRIEVAL_VERSION,
        "scoring_version": ev.SCORING_VERSION,
        "dataset": {
            **financebench.manifest(rows),
            "revision": "2026-11-13",
            "license_note": "evaluation only; question and answer text stay outside Git",
        },
        "evaluation_fingerprint": ev.evaluation_fingerprint(questions, config),
        "configuration": config,
        "thresholds": THRESHOLDS,
        "corpus": engine.stats(),
        "exclusions": exclusions,
        "questions_evaluated": len(questions),
        "methods": {},
        "abstention": {},
        "gates": {},
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "random_seed": None,
            "gpu": False,
        },
    }
    traces: dict = {"questions": {}, "records": {}}
    for method in ("bm25", "lexical_improved"):
        summary, evaluated = ev.evaluate(engine, questions, method=method, k=10,
                                         rows_by_id=rows_by_id)
        payload["methods"][method] = summary
        traces["records"][method] = [record for record in summary["records"]]
        traces["questions"] = {item.question_id: {"question": item.question,
                                                 "answer": item.answer,
                                                 "evidence": item.annotations.get("evidence")}
                               for item in questions}
        positives = [record["abstained"] for record in summary["records"]]
        negatives: dict[str, list[bool]] = {}
        for policy in POLICIES:
            negatives[policy] = []
            for question in DEV_NEGATIVES:
                result = engine.search(question, limit=5,
                                       support_policy="strict" if policy == "term_absence"
                                       else "coverage")
                negatives[policy].append(bool(result["abstained"]))
            payload["abstention"].setdefault("dev", {})[policy] = ev.abstention_metrics(
                positives, negatives[policy])
    # One policy is selected on development data only, then run once on the holdout.
    dev = payload["abstention"]["dev"]
    chosen = max(POLICIES, key=lambda p: ((dev[p]["precision"] or 0) + (dev[p]["recall"] or 0)))
    payload["abstention"]["chosen_policy"] = chosen
    payload["abstention"]["selection_basis"] = "development set only (precision + recall)"
    holdout_flags = []
    for question in HOLDOUT_NEGATIVES:
        result = engine.search(question, limit=5,
                               support_policy="strict" if chosen == "term_absence" else "coverage")
        holdout_flags.append(bool(result["abstained"]))
    payload["abstention"]["holdout"] = ev.abstention_metrics([], holdout_flags)
    payload["abstention"]["holdout"]["note"] = (
        "Negatives only: no untouched answerable holdout exists, so recall here is unanswerable "
        "recall, not balanced abstention accuracy."
    )

    baseline = payload["methods"]["bm25"]["metrics"]
    challenger = payload["methods"]["lexical_improved"]["metrics"]
    best = {key: max((baseline[key] or 0), (challenger[key] or 0))
            for key in ("document_recall@5", "answer_presence@5")}
    payload["gates"] = {
        "citation_integrity": all(
            payload["methods"][m]["metrics"]["citation_integrity"] == 1.0
            for m in ("bm25", "lexical_improved")),
        "issuer_integrity": all(
            payload["methods"][m]["metrics"]["issuer_integrity"] == 1.0
            for m in ("bm25", "lexical_improved")),
        "no_future_leak": all(
            payload["methods"][m]["metrics"]["future_leak_rate"] == 0.0
            for m in ("bm25", "lexical_improved")),
        "no_cross_issuer": all(
            payload["methods"][m]["metrics"]["cross_issuer_rate"] == 0.0
            for m in ("bm25", "lexical_improved")),
        "document_recall@5": best["document_recall@5"] >= THRESHOLDS["document_recall@5"],
        "answer_presence@5": best["answer_presence@5"] >= THRESHOLDS["answer_presence@5"],
        "abstention": (
            (dev[chosen]["precision"] or 0) >= THRESHOLDS["abstention_precision"]
            and (dev[chosen]["recall"] or 0) >= THRESHOLDS["abstention_recall"]
            and (dev[chosen]["false_abstention_rate"] or 0) <= THRESHOLDS["false_abstention_rate"]
        ),
    }
    payload["limitations"] = [
        "The 112 FinanceBench questions were already exposed to Phase 9.6 engineering decisions; "
        "they are not an untouched holdout.",
        "No untouched answerable abstention holdout exists; only negatives were held out.",
        "Gold evidence is PDF-page anchored, so span recall is not_evaluable against SEC HTML.",
        "No human adjudication of evidence relevance or claim entailment was performed.",
    ]

    Path("artifacts").mkdir(exist_ok=True)
    Path("var").mkdir(exist_ok=True)
    Path("var/phase9_6_1_eval_trace.json").write_text(json.dumps(traces))
    Path("artifacts/phase9_6_1_evaluation.json").write_text(
        json.dumps(ev.sanitize(payload), indent=2))
    for key, method in payload["methods"].items():
        print(key, json.dumps(method["metrics"], indent=2))
    print("abstention", json.dumps({k: v for k, v in payload["abstention"].items()
                                   if k != "dev"}, indent=2))
    print("gates", json.dumps(payload["gates"], indent=2))
    return 0 if all(payload["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
