"""Phase 9.6.3 evaluation: concept-aware localization on the full eligible corpus.

Differences from 9.6.2 (which remain unchanged as history):

* every eligible question is classified once, by answer shape and question intent, without
  reference to whether Atlas succeeded;
* a value match alone is no longer credited: the concept must resolve to one cell first;
* financial and non-financial tables are reported separately, because the 9.6.2 "unparseable"
  count was dominated by tables of contents and executive-bio tables;
* abstention is measured on hard negatives constructed from the real corpus.

Licensed question and answer text is never written to the artifact.
"""

from __future__ import annotations

import json
import math
import platform
import re
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research import financebench  # noqa: E402
from atlas.research.evaluation import load_questions  # noqa: E402
from atlas.research.financial_answers import FinancialAnswerEngine  # noqa: E402
from atlas.research.financial_concepts import CONCEPTS, ConceptResolver  # noqa: E402
from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.research.table_cells import classify_table, extract_cells  # noqa: E402
from atlas.storage.db import Database  # noqa: E402

METHODOLOGY_VERSION = "9.6.3"
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
    for candidate in ([raw, raw * (Decimal(10) ** scale)] if scale else [raw]):
        if candidate == answer:
            return True
        if answer != 0 and abs((candidate - answer) / answer) <= Decimal("0.005"):
            return True
    return False


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
        "financial_verified_rate": round(financial["verified"] / financial["cells"], 4)
        if financial["cells"] else None,
        "all_table_verified_rate": round(totals["verified"] / totals["cells"], 4)
        if totals["cells"] else None,
        "unresolved_reasons": dict(reasons.most_common(10)),
    }


def main() -> int:
    corpus = Database("var/phase9_6.db")
    knowledge = KnowledgeEngine(corpus)
    rows = financebench.open_source_rows(json.loads(Path("/tmp/financebench_rows.json").read_text()))
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
    positives_answered = positives = 0
    negatives = negatives_abstained = 0

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
        resolution = resolver.resolve(question.issuer_id, concept, year, cutoff)
        if resolution.status != "resolved":
            abstained += 1
            bucket[f"abstained:{resolution.status}"] += 1
            negatives += 1 if resolution.status in {"vintage_conflict", "ambiguous"} else 0
            continue
        concept_resolved += 1
        bucket["concept_resolved"] += 1
        cell = resolution.cell
        if cell is None:
            continue
        if cell.availability_time and cell.availability_time > cutoff:
            period_failures += 1
            abstained += 1
            bucket["period_failure"] += 1
            continue
        if reference is not None and matches(cell.value, cell.scale, reference):
            localized += 1
            bucket["cell_localized"] += 1
        try:
            if knowledge.unit(cell.unit_id).get("sha256"):
                pass
            else:
                citation_failures += 1
        except Exception:  # noqa: BLE001
            citation_failures += 1
        result = answers.lookup(question.issuer_id, cutoff, metric=cell.row_label, period=year)
        if result.get("outcome") != "answered":
            abstained += 1
            bucket["abstained:lookup"] += 1
            continue
        answered += 1
        bucket["answered"] += 1
        if reference is not None and matches(result["value"], 0, reference):
            correct += 1
            bucket["correct"] += 1
            positives += 1
            positives_answered += 1
        else:
            incorrect += 1
            bucket["incorrect"] += 1
        # Old, weaker metric: a value coincidence anywhere in the target filing.
        for candidate in answers.cells(question.issuer_id, cutoff):
            if (candidate.document_id == document_id and reference is not None
                    and matches(candidate.value, candidate.scale, reference)):
                value_coincidence += 1
                break

    # Hard negatives constructed from the real corpus: wrong year, undisclosed metric, and a
    # cutoff before the filing existed. They are not human-reviewed and the artifact says so.
    issuers = sorted({q.issuer_id for q in questions if q.issuer_id})
    negatives_abstained = 0
    negatives = 0
    for issuer_id in issuers[:12]:
        resolution = resolver.resolve(issuer_id, "revenue", "2017", "2100-01-01T00:00:00Z")
        negatives += 1
        negatives_abstained += resolution.status != "resolved"
        lookup = answers.lookup(issuer_id, "2100-01-01T00:00:00Z", metric="ebitda", period="2020")
        negatives += 1
        negatives_abstained += lookup["outcome"] == "abstained"
        early = answers.lookup(issuer_id, "1990-01-01T00:00:00Z", metric="revenue", period="2020")
        negatives += 1
        negatives_abstained += early["outcome"] == "abstained"

    attempted = sum(bucket["attempted"] for bucket in categories.values())
    metrics = {
        "document_recall@5": 0.9732,  # carried from 9.6.1; same corpus, same questions
        "concept_resolution_rate": round(concept_resolved / max(1, attempted), 4),
        "cell_localization_rate": round(localized / max(1, concept_resolved), 4),
        "value_coincidence_rate": round(value_coincidence / max(1, attempted), 4),
        "answer_correctness_among_answered": round(correct / max(1, answered), 4),
        "answer_coverage": round(answered / max(1, attempted), 4),
        "correct_over_all_attempted": round(correct / max(1, attempted), 4),
        "citation_integrity": round(1 - citation_failures / max(1, concept_resolved), 4),
        "abstention_precision": round(negatives_abstained / max(1, negatives), 4),
        "abstention_recall": round(positives_answered / max(1, positives), 4),
        "false_assertion_rate": round((negatives - negatives_abstained) / max(1, negatives), 4),
        "false_abstention_rate": round(1 - positives_answered / max(1, positives), 4),
        "period_failure_rate": round(period_failures / max(1, concept_resolved), 4),
    }
    gates = {
        "concept_resolution": metrics["concept_resolution_rate"]
        >= THRESHOLDS["concept_resolution_rate"],
        "cell_localization": metrics["cell_localization_rate"] >= THRESHOLDS["cell_localization_rate"],
        "answer_correctness": metrics["answer_correctness_among_answered"]
        >= THRESHOLDS["answer_correctness"],
        "citation_integrity": metrics["citation_integrity"] >= THRESHOLDS["citation_integrity"],
        "abstention_precision": metrics["abstention_precision"]
        >= THRESHOLDS["abstention_precision"],
        "false_assertions": metrics["false_assertion_rate"] <= THRESHOLDS["false_assertion_rate"],
    }
    payload = {
        "schema": "atlas.phase9_6_3.evaluation.v1",
        "methodology_version": METHODOLOGY_VERSION,
        "supersedes": None,
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
            "positives": positives, "negatives": negatives,
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
        "preregistration": {
            "declared_before_run": True,
            "concept_resolution": "question text must map to one registered concept via an alias; "
                                  "aliases are candidates, not proof",
            "cell_localization": "the resolved cell for the question's concept and period must "
                                 "carry the reference value at its stated scale",
            "answer_correctness": "the answer engine must return the reference value for the "
                                  "resolved row label and period",
            "abstention": "constructed corpus negatives: wrong year, undisclosed metric, and "
                          "pre-filing cutoff",
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
    Path("artifacts/phase9_6_3_evaluation.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"metrics": metrics, "gates": gates,
                      "tables": payload["tables"]["financial_verified_rate"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
