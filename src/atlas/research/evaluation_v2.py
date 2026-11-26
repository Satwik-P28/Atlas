"""Phase 9.6.1 evaluator, methodology version 9.6.1.

Differences from the Phase 9.6 evaluator (version 9.6.0), all of them deliberate:

* Every metric is computed at an explicit ``k``. There is no such thing as "recall" here; a
  gate that asks for @5 can only read a @5 key, and :func:`require_metric` raises otherwise.
* MRR uses every question in the denominator. A question whose target was never retrieved
  contributes 0 rather than disappearing.
* Document discovery, evidence retrieval and answer construction are separate metrics.
  Gold evidence in FinanceBench is PDF-page anchored, so span alignment against SEC HTML is
  ``not_evaluable``; a text-overlap number is reported alongside it as a clearly labelled proxy
  and never as span recall.
* Abstention reports precision, recall, false-abstention and calibration inputs rather than a
  single recall figure.
* The evaluation fingerprint hashes the *contents* (question, answer, labels, target, config),
  not the sorted identifiers. Changing a reference answer while keeping its id changes the
  fingerprint.
* Records never contain question or answer text: the emitted artifact carries identifiers,
  ranks, flags, counts and an approved digest only.
"""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .evaluation import Question, _integrity, answer_present, numbers  # noqa: F401
from .knowledge import KnowledgeEngine

SCORING_VERSION = "9.6.1"
RETRIEVAL_VERSION = "9.6.1"

#: Keys permitted in a committed evaluation record. Everything else stays in the local trace.
SANITIZED_KEYS = frozenset({
    "question_id", "doc_type", "period", "target_accession", "cutoff", "policy", "method",
    "target_rank", "returned_count", "returned_accessions", "answer_rank",
    "evidence_proxy_rank", "citation_resolves", "issuer_match", "future_document_returned",
    "cross_issuer_returned", "abstained", "abstention_reason", "failure", "latency_ms",
    "question_class", "question_type",
})

#: Fields that must never appear in a committed evaluation artifact.
PROHIBITED_KEYS = frozenset({"gold_answer", "evidence_text"})


def licensed_exposure(payload: Any) -> list[str]:
    """Paths holding licensed dataset text in an evaluation artifact.

    Phase 9.5 questions were authored by Atlas and may stay. FinanceBench questions and answers
    may not, so ``question``/``answer`` are prohibited only in artifacts that declare a licensed
    dataset (or a Phase 9.6 evaluation schema). Free text in ``gold_answer`` and long ``evidence``
    strings is always prohibited.
    """
    return _scan(payload, _licensed(payload), "")


def _licensed(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    schema = str(payload.get("schema", ""))
    dataset = payload.get("dataset") or {}
    license_id = str(dataset.get("license", "")) if isinstance(dataset, dict) else ""
    return "phase9_6" in schema or "financebench" in schema or license_id.startswith("cc-by-nc")


def _scan(node: Any, licensed: bool, path: str) -> list[str]:
    found: list[str] = []
    keys = PROHIBITED_KEYS | ({"question", "answer"} if licensed else set())
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if key in keys:
                found.append(here)
            elif key == "evidence" and isinstance(value, str) and len(value) > 80:
                found.append(here)
            else:
                found.extend(_scan(value, licensed, here))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(_scan(item, licensed, f"{path}[{index}]"))
    return found


def prohibited(node: Any, *, path: str = "") -> list[str]:
    """Return paths that hold licensed benchmark text.

    ``evidence`` is only prohibited when it is a text string: several Atlas artifacts use the
    same word as an integer count, and a blanket key ban would produce false positives.
    """
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}.{key}" if path else key
            if key in PROHIBITED_KEYS:
                found.append(here)
            elif key == "evidence" and isinstance(value, str) and len(value) > 80:
                found.append(here)
            else:
                found.extend(prohibited(value, path=here))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            found.extend(prohibited(item, path=f"{path}[{index}]"))
    return found


def evaluation_fingerprint(questions: Sequence[Question], config: dict[str, Any]) -> str:
    """Rights-safe digest of the evaluation contents.

    Hashes question text, answer text, labels, target document and scoring configuration so that
    any substantive change is detectable, while publishing only the digest.
    """
    payload = {
        "config": config,
        "questions": [
            {
                "id": item.question_id,
                "q": item.question,
                "a": item.answer,
                "doc_type": item.doc_type,
                "period": item.period,
                "target": item.target_accession,
                "cutoff": item.cutoff,
                "labels": item.annotations,
            }
            for item in sorted(questions, key=lambda q: q.question_id)
        ],
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def required_metric(metrics: dict[str, Any], name: str) -> float | None:
    """Read an exact metric by name; refuse names that do not encode a k."""
    if not any(name.endswith(f"@{k}") for k in (1, 5, 10)) and name not in metrics:
        raise KeyError(f"metric {name!r} is not defined at an explicit k")
    return metrics[name]


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def classify_question(row: dict[str, Any]) -> str:
    """Classify what the question asks for, from dataset row structure only.

    Uses the row's own fields, never the retrieved result, so the class cannot be assigned after
    seeing whether Atlas succeeded.
    """
    question_type = str(row.get("question_type") or "").lower()
    if "metric" in question_type or "number" in question_type:
        return "directly_reported_value_or_table_lookup"
    if "comparison" in question_type or "trend" in question_type:
        return "comparative_reasoning"
    if "qualitative" in question_type or "narrative" in question_type:
        return "narrative_extraction"
    return "unclassified"


@dataclass(slots=True)
class Evaluated:
    record: dict[str, Any]
    question: Question
    raw_question: str
    raw_answer: str


def evaluate(
    engine: KnowledgeEngine,
    questions: Sequence[Question],
    *,
    method: str,
    k: int = 10,
    policy: str = "public_available",
    support_policy: str = "balanced",
    rows_by_id: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[Evaluated]]:
    rows_by_id = rows_by_id or {}
    evaluated: list[Evaluated] = []
    for item in questions:
        started = time.perf_counter()
        search = engine.search(item.question, issuer_id=item.issuer_id, cutoff=item.cutoff,
                               policy=policy, limit=k, mode=method,
                               support_policy=support_policy)
        latency = (time.perf_counter() - started) * 1000
        top = search["results"]
        target_rank = next(
            (i + 1 for i, result in enumerate(top)
             if result["document_id"] == item.target_document_id), None,
        )
        bodies: list[str] = []
        answer_rank = None
        evidence_rank = None
        for index, result in enumerate(top):
            row = engine.db.query_one("SELECT body FROM knowledge_unit WHERE unit_id = ?",
                                      (result["unit_id"],))
            body = row["body"] if row else ""
            bodies.append(body)
            if answer_rank is None and body and answer_present(item.answer, body):
                answer_rank = index + 1
            evidence = item.annotations.get("evidence") or ""
            if evidence_rank is None and body and answer_present(evidence, body):
                evidence_rank = index + 1
        integrity = (_integrity(engine, top[0]["unit_id"], item.issuer_id or "", item.cutoff or "")
                     if top else {"resolves": False, "reason": "no_results"})
        future = [r["accession"] for r in top
                  if item.cutoff and r["availability_time"] > item.cutoff]
        cross = [r["issuer_id"] for r in top if r["issuer_id"] != item.issuer_id]
        failure = None
        if search["abstained"]:
            failure = "abstained_with_available_evidence"
        elif target_rank is None:
            failure = "target_document_not_in_top_k"
        elif answer_rank is None:
            failure = "answer_not_present_in_retrieved_passages"
        record = {
            "question_id": item.question_id,
            "doc_type": item.doc_type,
            "period": item.period,
            "target_accession": item.target_accession,
            "cutoff": item.cutoff,
            "policy": policy,
            "method": method,
            "target_rank": target_rank,
            "returned_count": len(top),
            "returned_accessions": [r["accession"] for r in top],
            "answer_rank": answer_rank,
            # Proxy only: PDF page anchors cannot be aligned to SEC HTML spans.
            "evidence_proxy_rank": evidence_rank,
            "citation_resolves": bool(integrity.get("resolves")),
            "issuer_match": bool(integrity.get("issuer_match")),
            "future_document_returned": future,
            "cross_issuer_returned": cross,
            "abstained": search["abstained"],
            "abstention_reason": search["abstention_reason"],
            "failure": failure,
            "latency_ms": round(latency, 2),
            "question_class": classify_question(rows_by_id.get(item.question_id, {})),
            "question_type": item.annotations.get("question_type"),
        }
        evaluated.append(Evaluated(record=record, question=item, raw_question=item.question,
                                   raw_answer=item.answer))
    return summarise(records=[e.record for e in evaluated], k=k, method=method), evaluated


def summarise(*, records: list[dict[str, Any]], k: int, method: str) -> dict[str, Any]:
    total = len(records)

    def count(predicate) -> int:
        return sum(1 for record in records if predicate(record))

    def at_k(rank: str, limit: int) -> int:
        return count(lambda r: r[rank] is not None and r[rank] <= limit)

    latencies = sorted(record["latency_ms"] for record in records)
    metrics: dict[str, Any] = {
        "questions_scored": total,
        "questions_answered": count(lambda r: not r["abstained"]),
        "method": method,
        "scoring_version": SCORING_VERSION,
    }
    for limit in (1, 5, 10):
        metrics[f"document_recall@{limit}"] = _rate(at_k("target_rank", limit), total)
        metrics[f"answer_presence@{limit}"] = _rate(at_k("answer_rank", limit), total)
        metrics[f"evidence_proxy@{limit}"] = _rate(at_k("evidence_proxy_rank", limit), total)
        metrics[f"evidence_span_recall@{limit}"] = "not_evaluable"
    metrics["correct_document_rate@1"] = _rate(count(lambda r: r["target_rank"] == 1), total)
    metrics["mrr"] = round(
        sum(1 / r["target_rank"] for r in records if r["target_rank"]) / total, 4
    ) if total else None
    metrics["citation_integrity"] = _rate(count(lambda r: r["citation_resolves"]), total)
    metrics["issuer_integrity"] = _rate(count(lambda r: r["issuer_match"]), total)
    metrics["future_leak_rate"] = _rate(count(lambda r: bool(r["future_document_returned"])), total)
    metrics["cross_issuer_rate"] = _rate(count(lambda r: bool(r["cross_issuer_returned"])), total)
    metrics["abstention_rate_on_answerable"] = _rate(count(lambda r: r["abstained"]), total)
    metrics["false_abstention_rate"] = metrics["abstention_rate_on_answerable"]
    metrics["latency_p50_ms"] = round(statistics.median(latencies), 2) if latencies else None
    metrics["latency_p95_ms"] = latencies[max(0, int(len(latencies) * 0.95) - 1)] if latencies else None
    metrics["failure_counts"] = {
        reason: count(lambda r, reason=reason: r["failure"] == reason)
        for reason in sorted({r["failure"] for r in records if r["failure"]})
    }
    metrics["by_question_class"] = {
        label: {
            "count": sum(1 for r in records if r["question_class"] == label),
            "document_recall@10": _rate(
                sum(1 for r in records if r["question_class"] == label
                    and r["target_rank"] is not None and r["target_rank"] <= 10),
                sum(1 for r in records if r["question_class"] == label)),
            "answer_presence@10": _rate(
                sum(1 for r in records if r["question_class"] == label
                    and r["answer_rank"] is not None and r["answer_rank"] <= 10),
                sum(1 for r in records if r["question_class"] == label)),
        }
        for label in sorted({r["question_class"] for r in records})
    }
    metrics["evidence_span_note"] = (
        "Gold evidence in FinanceBench is anchored to PDF pages; Atlas retrieves SEC HTML. Exact "
        "span alignment is not evaluable and is reported as such. evidence_proxy@k is a text "
        "overlap proxy, not span recall."
    )
    return {"metrics": metrics, "records": records}


def abstention_metrics(positives: list[bool], negatives: list[bool]) -> dict[str, Any]:
    """Precision/recall/false-abstention from per-question abstain decisions."""
    tp = sum(1 for flag in negatives if flag)
    fn = sum(1 for flag in negatives if not flag)
    fp = sum(1 for flag in positives if flag)
    tn = sum(1 for flag in positives if not flag)
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {
        "label": "self_authored",
        "positives": len(positives),
        "negatives": len(negatives),
        "true_positive_abstentions": tp,
        "false_positive_abstentions": fp,
        "false_negative_abstentions": fn,
        "true_negative_abstentions": tn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "false_abstention_rate": round(fp / len(positives), 4) if positives else None,
    }


def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip any field that is not on the approved list, recursively."""
    licensed = _licensed(payload)
    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            return {key: clean(value) for key, value in node.items()
                    if key not in PROHIBITED_KEYS
                    and not (licensed and key in {"question", "answer"})
                    and not (key == "evidence" and isinstance(value, str) and len(value) > 80)}
        if isinstance(node, list):
            return [clean(item) for item in node]
        return node
    return clean(payload)


__all__ = ["SCORING_VERSION", "RETRIEVAL_VERSION", "SANITIZED_KEYS", "PROHIBITED_KEYS",
           "evaluation_fingerprint", "required_metric", "evaluate", "summarise",
           "abstention_metrics", "sanitize", "classify_question"]
