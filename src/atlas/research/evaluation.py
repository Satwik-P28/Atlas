"""Independent retrieval evaluation over externally annotated questions.

The questions, reference answers and evidence come from FinanceBench's OPEN_SOURCE sample
(CC-BY-NC-4.0). Atlas did not author them and cannot tune them. What Atlas controls is the
corpus (real EDGAR filings), the retrieval methods and the scoring rules — all of which are
recorded per question so a failure can be attributed rather than averaged away.

Three verdicts are kept separate, because they fail for different reasons:

* **Citation integrity** — the returned passage resolves, hashes, spans and belongs to the
  issuer. This is a mechanical property; it must be 1.0.
* **Answer presence** — the reference answer string/number actually occurs in a retrieved
  passage. This is a retrieval property, not proof of understanding.
* **Claim support** — deliberately *not* asserted here. A number appearing in a passage does
  not establish that a claimed conclusion follows from it, and no LLM judge is used.
"""

from __future__ import annotations

import hashlib
import re
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..storage.db import Database
from .financebench import cik_for
from .knowledge import KnowledgeEngine

DOC_TYPES = {"10k": "10-K", "10q": "10-Q", "8k": "8-K", "Earnings": "8-K"}
_NUM = re.compile(r"-?\d[\d,]*\.?\d*")
_WORD = re.compile(r"[a-z]{4,}")


@dataclass(slots=True)
class Question:
    question_id: str
    company: str
    doc_type: str
    period: str
    question: str
    answer: str
    target_document_id: str | None
    issuer_id: str | None
    cutoff: str | None
    availability_time: str | None
    target_accession: str | None
    external_source: str = "PatronusAI/financebench:OPEN_SOURCE"
    annotations: dict[str, Any] = field(default_factory=dict)


def load_questions(
    rows: Iterable[dict[str, Any]], db: Database
) -> tuple[list[Question], list[dict[str, Any]]]:
    """Join external questions to ingested documents; record every exclusion with a reason."""
    questions: list[Question] = []
    exclusions: list[dict[str, Any]] = []
    for row in rows:
        if row.get("dataset_subset_label") != "OPEN_SOURCE":
            exclusions.append({"id": row.get("financebench_id"), "reason": "subset_not_open_source"})
            continue
        doc_type = str(row.get("doc_type"))
        if doc_type not in DOC_TYPES:
            exclusions.append({"id": row.get("financebench_id"), "reason": "unknown_doc_type"})
            continue
        if doc_type != "10k":
            exclusions.append({"id": row.get("financebench_id"),
                               "reason": "document_type_outside_ingested_scope",
                               "doc_type": doc_type})
            continue
        cik = cik_for(str(row.get("company")))
        issuer = (db.query_one("SELECT issuer_id FROM issuer WHERE cik = ?", (cik,))
                  if cik else None)
        target = None
        if issuer:
            target = db.query_one(
                "SELECT document_id, accession, availability_time, availability_precision "
                "FROM knowledge_document WHERE issuer_id = ? AND form_type = '10-K' "
                "AND period_of_report LIKE ? ORDER BY availability_time LIMIT 1",
                (issuer["issuer_id"], f"{row.get('doc_period')}%"),
            )
        if target is None:
            exclusions.append({"id": row.get("financebench_id"), "reason": "no_matching_ingested_document",
                               "company": row.get("company"), "period": row.get("doc_period")})
            continue
        questions.append(Question(
            question_id=str(row.get("financebench_id")),
            company=str(row.get("company")),
            doc_type=doc_type,
            period=str(row.get("doc_period")),
            question=str(row.get("question")),
            answer=str(row.get("answer")),
            target_document_id=target["document_id"],
            issuer_id=issuer["issuer_id"],
            cutoff=target["availability_time"],
            availability_time=target["availability_time"],
            target_accession=target["accession"],
            annotations={"question_type": row.get("question_type"),
                         "doc_name": row.get("doc_name"),
                         "evidence": str(row.get("evidence") or "")},
        ))
    return questions, exclusions


def numbers(value: str) -> list[str]:
    """Normalise reference numbers so "$1,577.00" and "1577" compare equal.

    Trailing zeros are trimmed and signs dropped; scaling ("$1.58 billion" vs "1,580") is
    deliberately *not* inferred, because guessing a unit would inflate the metric.
    """
    out: list[str] = []
    for match in _NUM.findall(value):
        cleaned = match.replace(",", "").lstrip("-").strip()
        if "." in cleaned:
            cleaned = cleaned.rstrip("0").rstrip(".")
        if not cleaned or cleaned in {"0", "."}:
            continue
        out.append(cleaned)
    return out


def answer_present(answer: str, text: str) -> bool:
    """Does the reference answer occur in this passage?

    Numbers are compared with separators removed and trailing zeros trimmed; word answers need
    most of their content words present. This is a *presence* test, deliberately not an
    entailment claim.
    """
    flat = text.replace(",", "")
    candidates = numbers(answer)
    if candidates:
        for candidate in candidates:
            # Digit boundaries: "157" must not match inside "15770".
            pattern = re.compile(rf"(?<![\d.]){re.escape(candidate)}(?![\d])")
            if pattern.search(flat):
                return True
        return False
    words = _WORD.findall(answer.lower())
    if not words:
        return False
    hits = sum(1 for word in words if word in text.lower())
    return hits / len(words) >= 0.6


def _integrity(engine: KnowledgeEngine, unit_id: str, issuer_id: str,
              cutoff: str) -> dict[str, Any]:
    row = engine.db.query_one(
        "SELECT u.body, u.sha256, u.char_start, u.char_end, d.issuer_id, d.availability_time "
        "FROM knowledge_unit u JOIN knowledge_document d ON d.document_id = u.document_id "
        "WHERE u.unit_id = ?", (unit_id,),
    )
    if row is None:
        return {"resolves": False, "reason": "passage_missing"}
    digest = hashlib.sha256(row["body"].encode("utf-8")).hexdigest()
    if digest != row["sha256"]:
        return {"resolves": False, "reason": "passage_corruption"}
    return {
        "resolves": True,
        "issuer_match": row["issuer_id"] == issuer_id,
        "span": [row["char_start"], row["char_end"]],
        "available_at_cutoff": row["availability_time"] <= cutoff,
    }


def evaluate(
    engine: KnowledgeEngine,
    questions: list[Question],
    *,
    method: str,
    k: int = 10,
    policy: str = "public_available",
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for item in questions:
        started = time.perf_counter()
        search = engine.search(item.question, issuer_id=item.issuer_id, cutoff=item.cutoff,
                               policy=policy, limit=k, mode=method)
        latency = (time.perf_counter() - started) * 1000
        top = search["results"]
        target_rank = next(
            (index + 1 for index, result in enumerate(top)
             if result["document_id"] == item.target_document_id), None,
        )
        answer_rank = None
        bodies: list[str] = []
        for index, result in enumerate(top):
            body = engine.db.query_one("SELECT body FROM knowledge_unit WHERE unit_id = ?",
                                       (result["unit_id"],))
            bodies.append(body["body"] if body else "")
            if answer_rank is None and body and answer_present(item.answer, body["body"]):
                answer_rank = index + 1
        # Whether the annotated evidence passage is reachable at all, independent of whether its
        # value can be read out. An answer that is computed (a ratio, a margin) never appears
        # verbatim; its inputs do.
        evidence = item.annotations.get("evidence") or ""
        evidence_localized = bool(evidence) and answer_present(evidence, " ".join(bodies))
        integrity = (_integrity(engine, top[0]["unit_id"], item.issuer_id or "", item.cutoff or "")
                     if top else {"resolves": False, "reason": "no_results"})
        future = [result["accession"] for result in top
                  if item.cutoff and result["availability_time"] > item.cutoff]
        cross = [result["issuer_id"] for result in top if result["issuer_id"] != item.issuer_id]
        failure = None
        if search["abstained"]:
            failure = "abstained_with_available_evidence"
        elif target_rank is None:
            failure = "target_document_not_in_top_k"
        elif answer_rank is None:
            failure = "answer_not_present_in_retrieved_passages"
        records.append({
            "question_id": item.question_id, "company": item.company, "period": item.period,
            "method": method, "question": item.question, "answer": item.answer,
            "target_document_id": item.target_document_id, "target_accession": item.target_accession,
            "cutoff": item.cutoff, "policy": policy,
            "returned_documents": [result["accession"] for result in top],
            "target_rank": target_rank, "answer_rank": answer_rank,
            "answer_in_top_k": answer_rank is not None,
            "evidence_localized": evidence_localized,
            "target_in_top_k": target_rank is not None,
            "citation_integrity": integrity,
            "future_document_returned": future,
            "cross_issuer_returned": cross,
            "abstained": search["abstained"],
            "abstention_reason": search["abstention_reason"],
            "match_expression": search["plan"].get("match_expression"),
            "failure": failure,
            "latency_ms": round(latency, 2),
            "question_type": item.annotations.get("question_type"),
        })
    return summarise(records, k=k)


def summarise(records: list[dict[str, Any]], *, k: int) -> dict[str, Any]:
    total = len(records)
    def rate(predicate) -> float | None:
        if not total:
            return None
        return round(sum(1 for record in records if predicate(record)) / total, 4)
    answered = [record for record in records if not record["abstained"]]
    latencies = sorted(record["latency_ms"] for record in records)
    integrity_failures = [record for record in records
                          if not record["citation_integrity"].get("resolves")]
    metrics = {
        "questions_scored": total,
        "questions_answered": len(answered),
        f"target_document_recall_at_{k}": rate(lambda r: r["target_in_top_k"]),
        f"answer_presence_recall_at_{k}": rate(lambda r: r["answer_in_top_k"]),
        "correct_document_rate_at_1": rate(lambda r: r["target_rank"] == 1),
        "mrr": round(statistics.fmean(1 / r["target_rank"] for r in records if r["target_rank"]), 4)
        if any(r["target_rank"] for r in records) else None,
        "evidence_localization_rate": rate(lambda r: r["evidence_localized"]),
        "citation_integrity_rate": rate(lambda r: r["citation_integrity"].get("resolves")),
        "citation_integrity_failures": len(integrity_failures),
        "future_leak_rate": rate(lambda r: bool(r["future_document_returned"])),
        "cross_issuer_rate": rate(lambda r: bool(r["cross_issuer_returned"])),
        "abstention_rate": rate(lambda r: r["abstained"]),
        "failure_counts": {
            reason: sum(1 for record in records if record["failure"] == reason)
            for reason in sorted({record["failure"] for record in records if record["failure"]})
        },
        "latency_ms_p50": round(statistics.median(latencies), 2) if latencies else None,
        "latency_ms_p95": latencies[max(0, int(len(latencies) * 0.95) - 1)] if latencies else None,
    }
    return {"metrics": metrics, "records": records}


def abstention_probe(engine: KnowledgeEngine, negatives: list[dict[str, str]], *,
                     method: str) -> dict[str, Any]:
    """Abstention precision/recall on questions with no supporting passage.

    Negatives are authored for this phase and labelled ``self_authored``: they test behaviour,
    they are not an independent benchmark of answer correctness.
    """
    rows = []
    for item in negatives:
        search = engine.search(item["question"], issuer_id=item.get("issuer_id"),
                               cutoff=item.get("cutoff"), limit=5, mode=method,
                               support_policy="strict")
        rows.append({"question": item["question"], "abstained": search["abstained"],
                     "reason": search["abstention_reason"], "count": search["count"]})
    abstained = sum(1 for row in rows if row["abstained"])
    return {
        "label": "self_authored",
        "negatives": len(rows),
        "abstained": abstained,
        "recall": round(abstained / len(rows), 4) if rows else None,
        "support_policy": "strict",
        "rows": rows,
    }


__all__ = ["Question", "load_questions", "evaluate", "summarise", "answer_present",
           "abstention_probe", "numbers"]
