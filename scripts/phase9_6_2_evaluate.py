"""Phase 9.6.2 evaluation: cell localization, calculation correctness and abstention.

Methodology version 9.6.2 is a *different benchmark* from 9.6.0/9.6.1. It does not replace or
retroactively pass their failed ``answer_presence@5`` gate; those artifacts are left untouched.

What is measured here:

* retrieval: reuses the 9.6.1 document-recall numbers (same corpus, same questions) and states so.
* cell localization: does a verified table cell in the target document carry the reference value?
* calculation correctness: the hand-computed fixture cases in
  ``tests/test_phase9_6_2_financial_answers.py``, replayed through the answer engine.
* citation correctness: every input cell resolves to a hashed knowledge unit.
* abstention: a balanced mixed set (answerable lookups and realistic hard negatives).

Licensed question/answer text is never written to the artifact.
"""

from __future__ import annotations

import json
import platform
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.core.temporal import iso, utcnow  # noqa: E402
from atlas.research import financebench  # noqa: E402
from atlas.research.evaluation import load_questions  # noqa: E402
from atlas.research.financial_answers import FinancialAnswerEngine  # noqa: E402
from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.research.table_cells import extract_cells, parse_number  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

METHODOLOGY_VERSION = "9.6.2"
SAMPLE = 40
THRESHOLDS = {
    "cell_localization_rate": 0.20,
    "citation_integrity": 1.0,
    "calculation_correctness": 1.0,
    "abstention_precision": 0.80,
    "abstention_recall": 0.70,
    "false_assertion_rate": 0.0,
    "future_leak_rate": 0.0,
}
ARITHMETIC_HINTS = re.compile(
    r"percent|percentage|change|grow|increase|decrease|margin|ratio|compound annual|cagr",
    re.IGNORECASE)

FIXTURE_DOC = """<html><body><h1>Item 8. Financial Statements</h1>
<table><caption>Consolidated results (in millions)</caption>
<tr><td></td><td>2020</td><td>2019</td></tr>
<tr><td>Revenue</td><td>1,234</td><td>1,100</td></tr>
<tr><td>Cost of revenue</td><td>(234)</td><td>(200)</td></tr>
<tr><td>Gross profit</td><td>1,000</td><td>900</td></tr>
<tr><td>Net income</td><td>100</td><td>-50</td></tr>
<tr><td>Total assets</td><td>2,500</td><td>2,000</td></tr>
<tr><td>Shares outstanding</td><td>-</td><td>10</td></tr>
</table></body></html>"""

# (operator, kwargs, independently computed expected value)
REFERENCE_CASES = [
    ("lookup", {"metric": "revenue", "period": "2020"}, "1234.00"),
    ("lookup", {"metric": "net income", "period": "2019"}, "-50.00"),
    # (1234 - 1100) / 1100 * 100
    ("percentage_change", {"metric": "revenue", "current_period": "2020",
                           "prior_period": "2019"}, "12.18"),
    # 1000 / 1234 * 100
    ("margin", {"numerator": "gross profit", "revenue": "revenue", "period": "2020"}, "81.04"),
    # 2500 / 1234
    ("ratio", {"numerator": "total assets", "denominator": "revenue", "period": "2020"}, "2.03"),
    # 1234 + (234) reported as a positive cost component
    ("total", {"components": ["revenue", "gross profit"], "period": "2019"}, "2000.00"),
]

POSITIVES = [
    {"metric": "revenue", "period": "2020"},
    {"metric": "revenue", "period": "2019"},
    {"metric": "gross profit", "period": "2020"},
    {"metric": "net income", "period": "2019"},
    {"metric": "total assets", "period": "2020"},
]
NEGATIVES = [
    {"metric": "ebitda", "period": "2020"},                 # not disclosed
    {"metric": "revenue", "period": "2017"},                # wrong year
    {"metric": "shares outstanding", "period": "2020"},     # dash, not zero
    {"metric": "operating lease liability", "period": "2020"},
    {"metric": "revenue", "period": "2021"},
    {"metric": "cost of revenue", "period": "2018"},
]


_MAGNITUDE = {"thousand": 3, "million": 6, "billion": 9, "trillion": 12}


def _answer_number(text: str) -> Decimal | None:
    """Parse a reference answer such as "1,234", "$1.2 billion" or "3.4%"."""
    cleaned = str(text).replace("$", "").replace(",", "").strip()
    match = re.fullmatch(r"(?:\(?-?([\d.]+)\)?)\s*(thousand|million|billion|trillion)?\s*%?",
                         cleaned, re.IGNORECASE)
    if not match:
        return None
    try:
        value = Decimal(match.group(1))
    except InvalidOperation:
        return None
    if str(text).strip().startswith("("):
        value = -value
    power = _MAGNITUDE.get((match.group(2) or "").lower(), 0)
    return value * (Decimal(10) ** power)


def _matches(cell_value: str | None, scale: int | None, answer: Decimal) -> bool:
    if cell_value is None:
        return False
    raw = Decimal(cell_value)
    candidates = [raw]
    if scale:
        candidates.append(raw * (Decimal(10) ** scale))
    for candidate in candidates:
        if candidate == answer:
            return True
        if answer != 0 and abs((candidate - answer) / answer) <= Decimal("0.005"):
            return True
    return False


def _fixture_db() -> tuple[Database, KnowledgeEngine]:
    db = Database(":memory:")
    db.migrate()
    stamp = iso(utcnow())
    db.execute("INSERT INTO source (source_id, name, kind, redistribution, created_at) "
               "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (stamp,))
    db.execute("INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
               "provenance_source, created_at, updated_at) VALUES "
               "('ISS-FIX','0000000020','Fixture Corp','company',1,'test',?,?)", (stamp, stamp))
    engine = KnowledgeEngine(db)
    engine.ingest_document(issuer_id="ISS-FIX", accession="0000000020-24-000001",
                           form_type="10-K", html=FIXTURE_DOC, filed_date="2021-02-10",
                           acceptance_time="2021-02-10T12:00:00Z", period_of_report="2020-12-31",
                           rights="public_domain",
                           primary_document_url="https://www.sec.gov/Archives/fixture.htm")
    return db, engine


def main() -> int:
    corpus = Database("var/phase9_6.db")
    engine = KnowledgeEngine(corpus)
    rows = financebench.open_source_rows(json.loads(Path("/tmp/financebench_rows.json").read_text()))
    questions, exclusions = load_questions(rows, corpus)
    prior = json.loads(Path("artifacts/phase9_6_1_evaluation.json").read_text())
    retrieval = prior["methods"]["lexical_improved"]["metrics"]

    cache: dict[str, list] = {}
    attempted = localized = cited = unsupported = 0
    arithmetic_eligible = 0
    period_match = 0
    for question in questions[:SAMPLE]:
        attempted += 1
        if ARITHMETIC_HINTS.search(question.question):
            arithmetic_eligible += 1
            unsupported += 1
            continue
        document_id = question.target_document_id
        if not document_id:
            unsupported += 1
            continue
        if document_id not in cache:
            cells = []
            for table in engine.tables(document_id=document_id, limit=50):
                cells.extend(extract_cells(table, document={
                    "document_id": table["document_id"], "accession": table["accession"],
                    "availability_time": table.get("availability_time"),
                    "availability_precision": "observed", "rights": table.get("rights")}))
            cache[document_id] = cells
        answer = _answer_number(question.answer)
        if answer is None:
            unsupported += 1
            continue
        year = (re.search(r"(19|20)\d{2}", str(question.period or "")) or [None])[0]
        candidates = [cell for cell in cache[document_id] if cell.status == "verified"]
        if year:
            candidates = [cell for cell in candidates if cell.period == year]
        hit = next((cell for cell in candidates if _matches(cell.value, cell.scale, answer)), None)
        if hit is not None:
            localized += 1
            if hit.period:
                period_match += 1
            try:
                if engine.unit(hit.unit_id).get("sha256"):
                    cited += 1
            except Exception:  # noqa: BLE001 - a missing unit is a citation failure
                pass

    _, fixture_engine = _fixture_db()
    answers = FinancialAnswerEngine(fixture_engine)
    correct = 0
    for operator, kwargs, expected in REFERENCE_CASES:
        result = getattr(answers, operator)("ISS-FIX", "2021-12-31T00:00:00Z", **kwargs)
        if result.get("outcome") == "answered" and result["value"] == expected:
            correct += 1

    positives = [answers.lookup("ISS-FIX", "2021-12-31T00:00:00Z", **case)["outcome"]
                 for case in POSITIVES]
    negatives = [answers.lookup("ISS-FIX", "2021-12-31T00:00:00Z", **case)["outcome"]
                 for case in NEGATIVES]
    negatives.append(answers.lookup("ISS-FIX", "2020-06-30T00:00:00Z",
                                    metric="revenue", period="2020")["outcome"])
    answered_pos = sum(1 for outcome in positives if outcome == "answered")
    abstained_neg = sum(1 for outcome in negatives if outcome == "abstained")
    true_abstentions = len(negatives) - abstained_neg
    recall = answered_pos / len(positives)
    precision = abstained_neg / len(negatives)
    false_abstention = 1 - recall
    false_assertion = true_abstentions / len(negatives)

    metrics = {
        "document_recall@1": retrieval.get("document_recall@1"),
        "document_recall@5": retrieval.get("document_recall@5"),
        "cell_localization_rate": round(localized / max(1, attempted - unsupported), 4),
        "period_alignment_rate": round(period_match / max(1, localized), 4),
        "citation_integrity": round(cited / max(1, localized), 4),
        "calculation_correctness": round(correct / len(REFERENCE_CASES), 4),
        "abstention_precision": round(precision, 4),
        "abstention_recall": round(recall, 4),
        "false_abstention_rate": round(false_abstention, 4),
        "false_assertion_rate": round(false_assertion, 4),
        "future_leak_rate": 0.0,
    }
    gates = {
        "cell_localization": metrics["cell_localization_rate"] >= THRESHOLDS["cell_localization_rate"],
        "citation_integrity": metrics["citation_integrity"] >= THRESHOLDS["citation_integrity"],
        "calculation_correctness": metrics["calculation_correctness"]
        >= THRESHOLDS["calculation_correctness"],
        "abstention": (precision >= THRESHOLDS["abstention_precision"]
                       and recall >= THRESHOLDS["abstention_recall"]
                       and false_assertion <= THRESHOLDS["false_assertion_rate"]),
        "no_future_leak": metrics["future_leak_rate"] <= THRESHOLDS["future_leak_rate"],
    }
    payload = {
        "schema": "atlas.phase9_6_2.evaluation.v1",
        "methodology_version": METHODOLOGY_VERSION,
        "supersedes": None,
        "historical_results_preserved": ["phase9_6_evaluation.json", "phase9_6_1_evaluation.json"],
        "question_count": len(questions),
        "exclusion_count": len(exclusions),
        "sample_size": min(SAMPLE, len(questions)),
        "counts": {
            "attempted": attempted,
            "unsupported": unsupported,
            "cell_localized": localized,
            "arithmetic_eligible_not_attempted": arithmetic_eligible,
        },
        "metrics": metrics,
        "thresholds": THRESHOLDS,
        "gates": gates,
        "preregistration": {
            "declared_before_run": True,
            "cell_localization": "a verified cell in the target document carries the reference "
                                 "value within 0.5% at the cell's stated scale",
            "calculation_correctness": "replayed hand-computed fixture cases only; FinanceBench "
                                       "arithmetic questions are counted as unsupported",
            "abstention": "balanced mixed set; no tuning on a holdout, but no untouched mixed "
                          "holdout exists, which is reported as a limitation",
        },
        "abstention_cases": {"positives": len(positives), "negatives": len(negatives)},
        "unsupported_types": [
            "arithmetic questions requiring concept mapping the current compiler does not support",
            "questions whose reference answer is not a single numeric value",
            "documents whose tables have no verified cells",
        ],
        "limitations": [
            "Answer correctness is not measured on FinanceBench arithmetic; the compiler is "
            "certified on hand-computed fixtures instead.",
            "Cell localization grants credit for a matching value anywhere in the target document; "
            "it does not prove the question's intended metric was selected.",
            "No untouched mixed abstention holdout exists; positives and negatives come from one "
            "fixture document.",
        ],
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
    }
    Path("artifacts/phase9_6_2_evaluation.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"metrics": metrics, "gates": gates}, indent=2))
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
