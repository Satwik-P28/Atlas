"""Prospective holdout: paths, preregistration hashing and analysis helpers.

This module exists so the holdout run neither reuses nor edits the development paths. The
development evaluation keeps ``fixtures/answer_semantics/questions.json`` and
``artifacts/answer_semantics/evaluation.json``; the prospective cohort gets its own corpus,
questions, facts, manifest, database, artifacts and report.

Nothing here selects an answer. It hashes frozen inputs, aggregates scored results per issuer
and computes the paired / cluster statistics declared in the preregistration.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import subprocess
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "fixtures" / "answer_semantics"
ARTIFACTS = ROOT / "artifacts" / "answer_semantics"

PROTOCOL_PATH = FIXTURES / "holdout_protocol.json"
PLAN_PATH = FIXTURES / "holdout_plan.json"
UNIVERSE_PATH = FIXTURES / "holdout_universe.json"
CORPUS_PATH = FIXTURES / "holdout_corpus.json"
QUESTIONS_PATH = FIXTURES / "holdout_questions.json"
FACTS_PATH = FIXTURES / "holdout_facts.json"
LEDGER_PATH = FIXTURES / "holdout_ledger.json"
FREEZE_PATH = FIXTURES / "holdout_freeze.json"
MANIFEST_PATH = ARTIFACTS / "holdout_source_manifest.json"
SELECTION_AUDIT_PATH = ARTIFACTS / "holdout_selection_audit.json"
OUTPUT_PATH = ARTIFACTS / "holdout_evaluation.json"
REPLAY_PATH = ARTIFACTS / "holdout_replay.json"
DB_PATH = ROOT / "var" / "answer_semantics" / "holdout" / "holdout.db"
SNAPSHOTS = ROOT / "var" / "answer_semantics" / "holdout" / "snapshots"

#: Inputs whose exact bytes the preregistration covers. Editing any of them after the freeze
#: would silently turn the cohort back into a development set.
AUTHOR_SCRIPT = "scripts/answer_semantics_holdout_author_gold.py"
FROZEN_INPUTS: tuple[str, ...] = tuple(
    str(path.relative_to(ROOT))
    for path in (PROTOCOL_PATH, PLAN_PATH, UNIVERSE_PATH, CORPUS_PATH, QUESTIONS_PATH,
                 FACTS_PATH, LEDGER_PATH, MANIFEST_PATH)) + (AUTHOR_SCRIPT,)

#: Resolution code whose bytes the preregistration covers. A change here between the freeze and
#: the first scored run would mean the run measured a different system than the one declared.
FROZEN_CODE: tuple[str, ...] = (
    "src/atlas/research/answer_semantics.py",
    "src/atlas/research/geometry_resolution.py",
    "src/atlas/research/financial_answers.py",
    "src/atlas/research/financial_concepts.py",
    "src/atlas/research/financial_verification.py",
    "src/atlas/research/table_geometry.py",
    "src/atlas/research/table_cells.py",
    "src/atlas/research/knowledge.py",
    "scripts/answer_semantics_holdout_evaluate.py",
    "scripts/answer_semantics_holdout_freeze.py",
    "src/atlas/research/holdout.py",
)

BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261123


def canonical_json(payload: Any) -> str:
    """Deterministic serialisation used for every committed hash."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_hashes(root: Path = ROOT, paths: Iterable[str] = FROZEN_INPUTS) -> dict[str, str]:
    return {relative: file_digest(root / relative) for relative in paths}


def code_hashes(root: Path = ROOT, paths: Iterable[str] = FROZEN_CODE) -> dict[str, str]:
    return {relative: file_digest(root / relative) for relative in paths}


def gold_digest(questions: dict[str, Any], facts: dict[str, Any], ledger: dict[str, Any],
                corpus: dict[str, Any], protocol: dict[str, Any]) -> str:
    """One hash over every authored decision, independent of JSON formatting."""
    return digest_payload({
        "protocol": protocol,
        "questions": questions,
        "facts": facts,
        "ledger": ledger,
        "corpus": corpus,
    })


# --------------------------------------------------------------------------- analysis
def _paired_flags(results: Sequence[dict[str, Any]]) -> dict[str, bool]:
    return {item["id"]: bool(item.get("correct")) for item in results}


def issuer_table(results: Sequence[dict[str, Any]],
                 questions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-issuer counts. Questions from one filing are not independent observations."""
    issuers: dict[str, dict[str, Any]] = {}
    for runner in ("baseline", "geometry"):
        for item in results:
            if item["runner"] != runner:
                continue
            meta = questions[item["id"]]
            row = issuers.setdefault(meta["cik"], {
                "cik": meta["cik"], "issuer": meta["issuer"], "questions": 0,
                "answerable": 0, "abstention": 0,
                "baseline_correct": 0, "geometry_correct": 0,
                "baseline_false": 0, "geometry_false": 0,
                "baseline_citation_failures": 0, "geometry_citation_failures": 0,
                "baseline_justified": 0, "geometry_justified": 0,
                "baseline_unsupported": 0, "geometry_unsupported": 0,
            })
            if runner == "baseline":
                row["questions"] += 1
            if item["gold_class"] == "xbrl_verified":
                if runner == "baseline":
                    row["answerable"] += 1
                if item.get("status") == "correct":
                    row[f"{runner}_correct"] += 1
                if item.get("status") == "false_answer":
                    row[f"{runner}_false"] += 1
                if item.get("status") == "citation_failure":
                    row[f"{runner}_citation_failures"] += 1
            else:
                if runner == "baseline":
                    row["abstention"] += 1
                if item.get("status") == "justified_abstention":
                    row[f"{runner}_justified"] += 1
                if item.get("status") == "unsupported_confident_answer":
                    row[f"{runner}_unsupported"] += 1
    return [row for _, row in sorted(issuers.items())]


def _binomial_two_sided(successes: int, trials: int) -> float | None:
    """Exact two-sided sign test on the discordant pairs (no normal approximation)."""
    if trials == 0:
        return None
    tail = sum(math.comb(trials, k) for k in range(0, successes + 1)) / (2 ** trials)
    return round(min(1.0, 2 * tail), 4)


def paired_comparison(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    baseline = _paired_flags([item for item in results if item["runner"] == "baseline"])
    geometry = _paired_flags([item for item in results if item["runner"] == "geometry"])
    ids = sorted(set(baseline) & set(geometry))
    both = sum(1 for key in ids if baseline[key] and geometry[key])
    baseline_only = sum(1 for key in ids if baseline[key] and not geometry[key])
    geometry_only = sum(1 for key in ids if geometry[key] and not baseline[key])
    neither = sum(1 for key in ids if not baseline[key] and not geometry[key])
    return {
        "paired_questions": len(ids),
        "both_correct": both,
        "baseline_only_correct": baseline_only,
        "geometry_only_correct": geometry_only,
        "neither_correct": neither,
        "difference_geometry_minus_baseline": round((geometry_only - baseline_only) / len(ids), 4)
        if ids else None,
        "exact_sign_test_p_two_sided": _binomial_two_sided(min(baseline_only, geometry_only),
                                                           baseline_only + geometry_only),
        "note": ("Questions from one filing are correlated; the sign test treats them as exchangeable "
                 "only within the paired design and is reported with that caveat. The cluster "
                 "interval below is the primary uncertainty statement."),
    }


def cluster_bootstrap(results: Sequence[dict[str, Any]],
                      questions: dict[str, dict[str, Any]],
                      resamples: int = BOOTSTRAP_RESAMPLES,
                      seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Issuer-cluster bootstrap interval for the paired exact-answer-rate difference.

    Resampling clusters (issuers) rather than questions keeps correlated answers from one
    filing together. With twelve clusters the interval is wide and coarse by construction.
    """
    baseline = _paired_flags([item for item in results if item["runner"] == "baseline"])
    geometry = _paired_flags([item for item in results if item["runner"] == "geometry"])
    by_issuer: dict[str, list[str]] = {}
    for key, meta in questions.items():
        by_issuer.setdefault(meta["cik"], []).append(key)
    issuers = sorted(by_issuer)
    if not issuers or not baseline:
        return {"issuers": 0, "resamples": 0, "interval": None}
    rng = random.Random(seed)
    differences: list[float] = []
    for _ in range(resamples):
        sample: list[str] = []
        for _ in range(len(issuers)):
            sample.extend(by_issuer[issuers[rng.randrange(len(issuers))]])
        denominator = len(sample)
        if denominator == 0:
            continue
        base = sum(1 for key in sample if baseline.get(key))
        geom = sum(1 for key in sample if geometry.get(key))
        differences.append((geom - base) / denominator)
    differences.sort()

    def percentile(fraction: float) -> float | None:
        if not differences:
            return None
        index = min(len(differences) - 1, max(0, int(round(fraction * (len(differences) - 1)))))
        return round(differences[index], 4)

    return {
        "issuers": len(issuers),
        "resamples": len(differences),
        "seed": seed,
        "observed_difference": round(
            (sum(1 for key in baseline if geometry.get(key)) - sum(1 for key in baseline if baseline[key]))
            / len(baseline), 4),
        "interval_95": [percentile(0.025), percentile(0.975)],
        "caveat": ("Twelve issuer clusters, unequal question counts per issuer and paired questions "
                   "within a filing: the interval is descriptive, not a licence for a precise "
                   "population claim."),
    }


def amortised_cost(build_ms: dict[str, Any], results: Sequence[dict[str, Any]],
                   ingest_ms: float | None = None) -> dict[str, Any]:
    """Warm per-question latency plus the one-time preprocessing spread over the questions."""
    geometry = [item["elapsed_ms"] for item in results if item["runner"] == "geometry"]
    baseline = [item["elapsed_ms"] for item in results if item["runner"] == "baseline"]
    count = max(1, len(geometry))
    geometry_build = float(build_ms.get("geometry_tables") or 0.0) + float(ingest_ms or 0.0)
    baseline_build = float(build_ms.get("baseline_flattened_cells") or 0.0) + float(ingest_ms or 0.0)
    return {
        "questions": count,
        "baseline_warm_mean_ms": round(sum(baseline) / max(1, len(baseline)), 3),
        "geometry_warm_mean_ms": round(sum(geometry) / count, 3),
        "baseline_cold_build_ms": round(baseline_build, 3),
        "geometry_cold_build_ms": round(geometry_build, 3),
        "baseline_amortised_ms_per_question": round(
            sum(baseline) / max(1, len(baseline)) + baseline_build / count, 3),
        "geometry_amortised_ms_per_question": round(
            sum(geometry) / count + geometry_build / count, 3),
        "note": ("Preprocessing is counted once per arm for the whole cohort and divided by the "
                 "scored question count. Ingestion is shared by both arms and is reported "
                 "separately so a reader can remove it."),
    }


__all__ = ["ROOT", "FIXTURES", "ARTIFACTS", "PROTOCOL_PATH", "PLAN_PATH", "UNIVERSE_PATH",
           "CORPUS_PATH", "QUESTIONS_PATH", "FACTS_PATH", "LEDGER_PATH", "FREEZE_PATH",
           "MANIFEST_PATH", "SELECTION_AUDIT_PATH", "OUTPUT_PATH", "REPLAY_PATH", "DB_PATH",
           "SNAPSHOTS", "FROZEN_INPUTS", "FROZEN_CODE", "canonical_json", "digest_payload",
           "file_digest", "input_hashes", "code_hashes", "gold_digest", "issuer_table",
           "paired_comparison", "cluster_bootstrap", "amortised_cost"]
