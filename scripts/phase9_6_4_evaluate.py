"""Phase 9.6.4 evaluation: concept-aware localization on the full eligible corpus.

Differences from 9.6.3 (which remain unchanged as history):

* every eligible question is classified once, by answer shape and question intent, without
  reference to whether Atlas succeeded;
* a value match alone is no longer credited: the concept must resolve to one cell first;
* financial and non-financial tables are reported separately, because the 9.6.2 "unparseable"
  count was dominated by tables of contents and executive-bio tables;
* abstention is measured on hard negatives constructed from the real corpus;
* successful resolutions exercise the bound FEC path (bind + lookup_bound), not a second
  corpus-wide row-label search;
* metric denominators that are zero yield null (not-evaluable), never a perfect score.

Licensed question and answer text is never written to the artifact.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import sys
import traceback
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research import financebench  # noqa: E402
from atlas.research.evaluation import load_questions  # noqa: E402
from atlas.research.financial_answers import FinancialAnswerEngine  # noqa: E402
from atlas.research.financial_concepts import CONCEPTS, ConceptResolver, bind  # noqa: E402
from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.research.table_cells import classify_table, extract_cells  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

METHODOLOGY_VERSION = "9.6.4"
THRESHOLDS = {
    "concept_resolution_rate": 0.30,
    "cell_localization_rate": 0.20,
    "answer_correctness": 0.80,
    "citation_integrity": 1.0,
    "abstention_precision": 0.80,
    "false_assertion_rate": 0.10,
}
_MAGNITUDE = {"thousand": 3, "million": 6, "billion": 9, "trillion": 12}
ARITHMETIC = re.compile(
    r"percent|percentage|%|change|grow|increase|decrease|margin|ratio|cagr|relative to",
    re.IGNORECASE)

# Distinct from gate failure (1) and unavailable reference data (2).
EXIT_UNEXPECTED = 3


def answer_number(text: str) -> Decimal | None:
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
    return value * (Decimal(10) ** _MAGNITUDE.get((match.group(2) or "").lower(), 0))


def wilson(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def rate(numerator: int, denominator: int) -> float | None:
    """Integer rate with an explicit not-evaluable result for a zero denominator."""
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def classify(question) -> tuple[str, str | None]:
    text = question.answer.strip()
    if re.match(r"^(yes|no)\b", text, re.IGNORECASE):
        return "yes_no", None
    number = answer_number(text)
    intent = "arithmetic" if ARITHMETIC.search(question.question) else "direct"
    if number is None:
        return "narrative", None
    concept = detect_concept(question.question)
    return (f"numeric_{intent}", concept)


def detect_concept(text: str) -> str | None:
    lowered = text.lower()
    best, best_len = None, 0
    for key, concept in CONCEPTS.items():
        for alias in concept.aliases:
            if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", lowered) and len(alias) > best_len:
                best, best_len = key, len(alias)
    return best


def matches(value: str | None, scale: int | None, answer: Decimal) -> bool:
    if value is None:
        return False
    raw = Decimal(value)
    scales = [raw]
    if scale is not None:
        scales.append(raw * (Decimal(10) ** scale))
    for candidate in scales:
        if candidate == answer:
            return True
        if answer != 0 and abs((candidate - answer) / answer) <= Decimal("0.005"):
            return True
    return False


def confusion_rates(*, true_positives: int, false_positives: int,
                    true_negatives: int, false_negatives: int) -> dict[str, float | None]:
    """Hand-checkable confusion-matrix rates. Zero denominators are not-evaluable."""
    asserted = true_positives + false_positives
    abstained = true_negatives + false_negatives
    answerable = true_positives + false_negatives
    unanswerable = true_negatives + false_positives
    return {
        "assertion_precision": rate(true_positives, asserted),
        "abstention_precision": rate(true_negatives, abstained),
        "answerable_recall": rate(true_positives, answerable),
        "unanswerable_recall": rate(true_negatives, unanswerable),
        "false_assertion_rate": rate(false_positives, unanswerable),
        "false_abstention_rate": rate(false_negatives, answerable),
    }


class CachedEngine(FinancialAnswerEngine):
    """Extract each issuer's cells once; apply the cutoff per request."""

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self._cache: dict[str, list] = {}

    def cells(self, issuer_id: str, cutoff: str | None):  # type: ignore[override]
        if issuer_id not in self._cache:
            self._cache[issuer_id] = super().cells(issuer_id, None)
        return [cell for cell in self._cache[issuer_id]
                if not cutoff or not cell.availability_time or cell.availability_time <= cutoff]


def table_taxonomy(db: Database, engine: KnowledgeEngine, documents: list[str]) -> dict:
    totals = Counter()
    reasons: Counter = Counter()
    per_kind: dict[str, Counter] = {"financial": Counter(), "non_financial": Counter(),
                                    "unknown": Counter()}
    for document_id in documents:
        for table in engine.tables(document_id=document_id, limit=50):
            cells = extract_cells(table, document={
                "document_id": document_id, "accession": table["accession"],
                "availability_time": table.get("availability_time"),
                "availability_precision": "observed", "rights": table.get("rights")})
            kind, _why = classify_table(table, cells)
            per_kind[kind]["tables"] += 1
            for cell in cells:
                totals["cells"] += 1
                per_kind[kind]["cells"] += 1
                if cell.status == "verified":
                    totals["verified"] += 1
                    per_kind[kind]["verified"] += 1
                elif cell.reason:
                    reasons[cell.reason] += 1
                    per_kind[kind][f"reason:{cell.reason}"] += 1
    financial = per_kind["financial"]
    return {
        "tables_by_kind": {kind: counts["tables"] for kind, counts in per_kind.items()},
        "cells_by_kind": {kind: counts["cells"] for kind, counts in per_kind.items()},
        "verified_by_kind": {kind: counts["verified"] for kind, counts in per_kind.items()},
        "financial_verified_rate": rate(financial["verified"], financial["cells"]),
        "all_table_verified_rate": rate(totals["verified"], totals["cells"]),
        "unresolved_reasons": dict(reasons.most_common(10)),
    }


INPUT_PATH = Path(os.environ.get("ATLAS_FINANCEBENCH_ROWS", "/tmp/financebench_rows.json"))


def gate_exit_code(gates: dict[str, bool]) -> int:
    """Mandatory gates: any unmet gate is a failing process exit."""
    return 0 if gates and all(gates.values()) else 1


def unavailable_artifact(reason: str) -> dict:
    return {
        "schema": "atlas.phase9_6_4.evaluation.v1",
        "methodology_version": METHODOLOGY_VERSION,
        "evaluation_status": "unavailable_reference_data",
        "reason": reason,
        "counts": {"attempted": 0, "answered": 0, "correct": 0, "negatives": 0},
        "metrics": {},
        "gates": {"eligible_population": False, "reference_data_available": False},
        "limitations": ["Reference questions are licensed and are not stored in the repository."],
    }


def write_artifact(payload: dict[str, Any], path: Path | None = None) -> Path:
    target = path or Path("artifacts/phase9_6_4_evaluation.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Never persist licensed question/answer text if a caller accidentally attached it.
    sanitized = json.loads(json.dumps(payload, default=str))
    for key in ("questions", "answers", "licensed_text", "raw_rows"):
        sanitized.pop(key, None)
    target.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n")
    return target


def main() -> int:
    try:
        return _evaluate()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - distinct exit for unexpected failures
        payload = {
            "schema": "atlas.phase9_6_4.evaluation.v1",
            "methodology_version": METHODOLOGY_VERSION,
            "evaluation_status": "unexpected_error",
            "reason": f"{type(exc).__name__}: {exc}",
            "diagnostics": {"exception_type": type(exc).__name__,
                            "traceback_tail": traceback.format_exc()[-2000:]},
            "gates": {"eligible_population": False},
            "limitations": ["Evaluation aborted on an unexpected execution error."],
        }
        write_artifact(payload)
        print(json.dumps({"error": payload["reason"], "exit": EXIT_UNEXPECTED}, indent=2))
        return EXIT_UNEXPECTED


def _evaluate() -> int:
    corpus = Database("var/phase9_6.db")
    knowledge = KnowledgeEngine(corpus)
    try:
        raw_rows = json.loads(INPUT_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as error:
        payload = unavailable_artifact(f"{type(error).__name__}: {INPUT_PATH}")
        write_artifact(payload)
        print(json.dumps({"error": payload["reason"], "gates": payload["gates"]}, indent=2))
        return 2
    rows = financebench.open_source_rows(raw_rows)
    questions, exclusions = load_questions(rows, corpus)
    answers = CachedEngine(knowledge)
    resolver = ConceptResolver(knowledge)
    resolver.answers = answers

    categories: dict[str, Counter] = {}
    document_ids: set[str] = set()
    concept_resolved = 0
    localized = 0
    value_coincidence = 0
    answered = correct = incorrect = abstained = unsupported = citation_failures = 0
    period_failures = 0
    # Confusion-matrix populations are classified independently of success.
    # answerable positives: eligible numeric_direct questions with a reference number.
    true_positives = false_positives = true_negatives = false_negatives = 0
    answerable_total = 0

    for question in questions:
        category, concept = classify(question)
        bucket = categories.setdefault(category, Counter())
        bucket["eligible"] += 1
        document_id = question.target_document_id
        if document_id:
            document_ids.add(document_id)
        if concept is None or not question.issuer_id or not document_id:
            unsupported += 1
            bucket["unsupported"] += 1
            continue
        if category == "numeric_arithmetic":
            # The compiler supports these, but mapping an open question to specific operands and
            # periods is not evaluated here. Counting them as answered lookups would manufacture
            # false "incorrect" results.
            unsupported += 1
            bucket["unsupported"] += 1
            bucket["arithmetic_operand_mapping_not_evaluated"] += 1
            continue
        bucket["attempted"] += 1
        year_match = re.search(r"(19|20)\d{2}", str(question.period or ""))
        year = year_match.group(0) if year_match else None
        if year is None:
            unsupported += 1
            bucket["unsupported"] += 1
            continue
        reference = answer_number(question.answer)
        cutoff = str(question.availability_time or "2100-01-01T00:00:00Z")
        answerable = reference is not None
        if answerable:
            answerable_total += 1
        resolution = resolver.resolve(question.issuer_id, concept, year, cutoff)
        if resolution.status != "resolved":
            abstained += 1
            bucket[f"abstained:{resolution.status}"] += 1
            if answerable:
                false_negatives += 1
            continue
        concept_resolved += 1
        bucket["concept_resolved"] += 1
        cell = resolution.cell
        if cell is None:
            if answerable:
                false_negatives += 1
            continue
        if cell.availability_time and cell.availability_time > cutoff:
            period_failures += 1
            abstained += 1
            bucket["period_failure"] += 1
            if answerable:
                false_negatives += 1
            continue
        if reference is not None and matches(cell.value, cell.scale, reference):
            localized += 1
            bucket["cell_localized"] += 1
        try:
            unit = knowledge.unit(cell.unit_id)
            body = (unit.get("body") or "").encode("utf-8")
            if not unit.get("sha256") or hashlib.sha256(body).hexdigest() != unit["sha256"]:
                citation_failures += 1
        except Exception:  # noqa: BLE001
            citation_failures += 1
        # Bound path: preserve the resolved evidence identity; do not re-search by row label.
        binding = bind(resolution, question.issuer_id, concept)
        if binding is None:
            abstained += 1
            bucket["abstained:bind"] += 1
            if answerable:
                false_negatives += 1
            continue
        result = answers.lookup_bound(binding, cutoff)
        if result.get("outcome") != "answered":
            abstained += 1
            bucket["abstained:lookup_bound"] += 1
            if answerable:
                false_negatives += 1
            continue
        answered += 1
        bucket["answered"] += 1
        if reference is not None and matches(result["value"], 0, reference):
            correct += 1
            bucket["correct"] += 1
            true_positives += 1
        else:
            incorrect += 1
            bucket["incorrect"] += 1
            # An assertion on an answerable question that fails the reference is still an
            # assertion; count it as a false positive against the reference, not a false abstention.
            false_positives += 1
        # Old, weaker metric: a value coincidence anywhere in the target filing.
        for candidate in answers.cells(question.issuer_id, cutoff):
            if (candidate.document_id == document_id and reference is not None
                    and matches(candidate.value, candidate.scale, reference)):
                value_coincidence += 1
                break

    # Hard negatives constructed from the real corpus. They are not human-reviewed.
    issuers = sorted({q.issuer_id for q in questions if q.issuer_id})
    negative_log: list[dict] = []
    historical_answered = historical_total = 0
    constructed_unanswerable = 0
    for issuer_id in issuers[:12]:
        years = sorted({row["period_of_report"][:4] for row in corpus.query(
            "SELECT DISTINCT period_of_report FROM knowledge_document "
            "WHERE issuer_id = ? AND form_type = '10-K'", (issuer_id,))
            if row["period_of_report"]})
        historical_total += 1
        historical = (resolver.resolve(issuer_id, "revenue", years[0], "2100-01-01T00:00:00Z")
                      if years else None)
        historical_answered += bool(historical and historical.status == "resolved")
        negative_log.append({"class": "historical_year_available",
                             "issuer_id": issuer_id, "period": years[0] if years else None,
                             "status": historical.status if historical else "no_filing",
                             "counted_as": "positive"})
        undisclosed = answers.lookup(issuer_id, "2100-01-01T00:00:00Z", metric="ebitda",
                                     period="2020")
        constructed_unanswerable += 1
        if undisclosed["outcome"] == "abstained":
            true_negatives += 1
        else:
            false_positives += 1
        negative_log.append({"class": "undisclosed_metric", "issuer_id": issuer_id,
                             "status": undisclosed["outcome"]})
        early = answers.lookup(issuer_id, "1990-01-01T00:00:00Z", metric="revenue", period="2020")
        constructed_unanswerable += 1
        if early["outcome"] == "abstained":
            true_negatives += 1
        else:
            false_positives += 1
        negative_log.append({"class": "cutoff_before_availability", "issuer_id": issuer_id,
                             "status": early["outcome"]})

    attempted = sum(bucket["attempted"] for bucket in categories.values())
    confusion = confusion_rates(
        true_positives=true_positives, false_positives=false_positives,
        true_negatives=true_negatives, false_negatives=false_negatives)
    negatives = constructed_unanswerable
    metrics = {
        "document_recall@5": 0.9732,  # carried from 9.6.1; same corpus, same questions
        "concept_resolution_rate": rate(concept_resolved, attempted),
        "cell_localization_rate": rate(localized, concept_resolved),
        "value_coincidence_rate": rate(value_coincidence, attempted),
        "answer_correctness_among_answered": rate(correct, answered),
        "answer_coverage": rate(answered, attempted),
        "correct_over_all_attempted": rate(correct, attempted),
        "citation_integrity": (
            None if concept_resolved == 0
            else rate(concept_resolved - citation_failures, concept_resolved)),
        "abstention_precision": confusion["abstention_precision"],
        "assertion_precision": confusion["assertion_precision"],
        "unanswerable_recall": confusion["unanswerable_recall"],
        "answerable_recall": confusion["answerable_recall"],
        "historical_answer_rate": rate(historical_answered, historical_total),
        "false_assertion_rate": confusion["false_assertion_rate"],
        "false_assertions": false_positives,
        "false_abstention_rate": confusion["false_abstention_rate"],
        "false_abstentions": false_negatives,
        "period_failure_rate": rate(period_failures, concept_resolved),
        "confusion": {
            "true_positives": true_positives,
            "false_positives": false_positives,
            "true_negatives": true_negatives,
            "false_negatives": false_negatives,
            "answerable_total": answerable_total,
            "constructed_unanswerable": constructed_unanswerable,
        },
    }

    def gate_ge(metric_key: str, threshold_key: str) -> bool:
        value = metrics[metric_key]
        return value is not None and value >= THRESHOLDS[threshold_key]

    def gate_le(metric_key: str, threshold_key: str) -> bool:
        value = metrics[metric_key]
        return value is not None and value <= THRESHOLDS[threshold_key]

    gates = {
        "eligible_population": attempted > 0 and negatives > 0,
        "concept_resolution": gate_ge("concept_resolution_rate", "concept_resolution_rate"),
        "cell_localization": gate_ge("cell_localization_rate", "cell_localization_rate"),
        "answer_correctness": gate_ge("answer_correctness_among_answered", "answer_correctness"),
        "citation_integrity": gate_ge("citation_integrity", "citation_integrity"),
        "abstention_precision": gate_ge("abstention_precision", "abstention_precision"),
        "false_assertions": gate_le("false_assertion_rate", "false_assertion_rate"),
    }
    payload = {
        "schema": "atlas.phase9_6_4.evaluation.v1",
        "methodology_version": METHODOLOGY_VERSION,
        "supersedes": "atlas.phase9_6_3.evaluation.v1",
        "historical_results_preserved": [
            "phase9_6_evaluation.json", "phase9_6_1_evaluation.json", "phase9_6_2_evaluation.json"],
        "question_count": len(questions),
        "exclusion_count": len(exclusions),
        "attempted": attempted,
        "counts": {
            "concept_resolved": concept_resolved, "cell_localized": localized,
            "answered": answered, "correct": correct, "incorrect": incorrect,
            "abstained": abstained, "unsupported": unsupported,
            "citation_failures": citation_failures, "period_failures": period_failures,
            "true_positives": true_positives, "false_positives": false_positives,
            "true_negatives": true_negatives, "false_negatives": false_negatives,
            "negatives": negatives,
        },
        "categories": {name: dict(bucket) for name, bucket in sorted(categories.items())},
        "metrics": metrics,
        "uncertainty": {
            "concept_resolution_rate": wilson(concept_resolved, attempted),
            "cell_localization_rate": wilson(localized, concept_resolved),
            "answer_correctness_among_answered": wilson(correct, answered),
        },
        "thresholds": THRESHOLDS,
        "gates": gates,
        "tables": table_taxonomy(corpus, knowledge, sorted(document_ids)),
        "negative_log": negative_log,
        "preregistration": {
            "declared_before_run": True,
            "concept_resolution": "question text must map to one registered concept via an alias; "
                                  "aliases are candidates, not proof",
            "cell_localization": "the resolved cell for the question's concept and period must "
                                 "carry the reference value at its stated scale",
            "answer_correctness": "the bound answer engine must return the reference value for the "
                                  "resolved binding without a second corpus search",
            "abstention": "constructed corpus negatives: undisclosed metric and pre-filing cutoff",
            "metrics": "zero denominators are null (not-evaluable), never perfect scores",
        },
        "limitations": [
            "No XBRL fact table exists in this corpus, so concept identity is lexical plus "
            "statement/segment context, not XBRL-verified.",
            "FinanceBench annotations are PDF evidence spans; they cannot be aligned to SEC HTML "
            "coordinates, so table-level annotation alignment is not evaluated.",
            "The abstention negatives are deterministic constructions, not a human-reviewed "
            "holdout; no untouched mixed holdout was established.",
            "Correctness among answered cases and correct-over-all-attempted are reported "
            "separately; neither is a substitute for the other.",
        ],
        "environment": {"python": platform.python_version(), "platform": platform.platform()},
    }
    write_artifact(payload)
    print(json.dumps({"metrics": metrics, "gates": gates,
                      "tables": payload["tables"]["financial_verified_rate"]}, indent=2))
    failed = sorted(name for name, passed in gates.items() if not passed)
    if failed:
        print("MANDATORY GATE FAILURE: " + ", ".join(failed))
    return gate_exit_code(gates)


if __name__ == "__main__":
    raise SystemExit(main())
