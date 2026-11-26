"""Profile the answer-semantics pipeline stage by stage, on this machine.

The point is to replace guesses ("geometry is slow because HTML") with measurements that can be
compared: parsing, table geometry, statement classification, concept matching, candidate
selection, verification, memory, cold and warm latency, and repeated-query throughput.

Nothing here changes an answer. It re-uses the frozen twelve-issuer cohort as a warm corpus and
prints the historical first-run numbers alongside, because they were measured on the same VM.

Usage::

    python scripts/answer_semantics_profile.py
    python scripts/answer_semantics_profile.py --out artifacts/answer_semantics/hardening_profile.json
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.research import answer_semantics, holdout  # noqa: E402
from atlas.research.financial_concepts import CONCEPTS, ConceptResolver  # noqa: E402
from atlas.research.financial_verification import evaluate as verify_evaluate  # noqa: E402
from atlas.research.geometry_resolution import GeometryDocument, GeometryResolver  # noqa: E402
from atlas.research.knowledge import KnowledgeEngine  # noqa: E402
from atlas.research.table_geometry import parse_tables  # noqa: E402

DEFAULT_OUT = holdout.ARTIFACTS / "hardening_profile.json"
#: From the frozen first-run artifact (same VM, different session).
HISTORICAL = {"baseline_cold_ms": 9089.823, "geometry_cold_ms": 36783.261,
              "baseline_warm_mean_ms": 67.628, "geometry_warm_mean_ms": 46.836,
              "build_baseline_ms": 2345.0, "build_geometry_ms": 30039.0}


def _timed(function, *args, **kwargs) -> tuple[Any, float]:
    started = time.perf_counter()
    value = function(*args, **kwargs)
    return value, round((time.perf_counter() - started) * 1000, 3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    manifest = json.loads(holdout.MANIFEST_PATH.read_text())
    questions = json.loads(holdout.QUESTIONS_PATH.read_text())["questions"]
    snapshots = holdout.SNAPSHOTS
    payloads = {filing["accession"]: (snapshots / f"{filing['accession']}.html").read_bytes()
                for filing in manifest["filings"]}

    # Timing passes run without tracemalloc: allocation tracing multiplies parse time and would
    # turn the latency numbers into a measurement of the profiler.
    import atlas.research.table_geometry as geometry_module
    geometry_module._parse_cached.cache_clear()
    raw_tables, parse_ms = _timed(lambda: {acc: parse_tables(data) for acc, data in payloads.items()})
    documents = {acc: GeometryDocument.from_html(data, accession=acc, cik=filing["cik"])
                 for filing in manifest["filings"]
                 for acc, data in [(filing["accession"], payloads[filing["accession"]])]}
    cold_ms = parse_ms
    warmed, warm_parse_ms = _timed(lambda: {acc: parse_tables(data) for acc, data in payloads.items()})
    assert all(len(warmed[acc]) == len(raw_tables[acc]) for acc in raw_tables)

    geometry_module._parse_cached.cache_clear()
    tracemalloc.start()
    for acc, data in payloads.items():
        parse_tables(data)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    from atlas.research.statement_scope import classify
    titles = [table.statement_title for tables in raw_tables.values() for table in tables]
    _classified, classification_ms = _timed(lambda: [classify(title) for title in titles])
    resolver = GeometryResolver(documents.values())
    lookups: list[float] = []
    failures = 0
    for question in questions:
        scope = {"cutoff": question["cutoff"], "cik": question["issuer_cik"],
                 "accession": question["accession"]} if question["scope"] == "accession" else \
                {"cutoff": question["cutoff"], "cik": question["issuer_cik"]}
        resolution, elapsed = _timed(resolver.resolve, question["concept"], question["period"], **scope)
        lookups.append(elapsed)
        failures += resolution.status != "resolved"

    verification_ms = 0.0
    verified = 0
    for question in questions:
        if question["operator"] == "lookup":
            continue
        citations = question["expect"].get("citations") or []
        raws = [item.get("raw") for item in citations]
        if len(raws) < 2 or any(raw is None for raw in raws):
            continue
        _value, elapsed = _timed(verify_evaluate, question["operator"], raws)
        verification_ms += elapsed
        verified += 1

    baseline_started = time.perf_counter()
    from atlas.storage.db import Database
    database = Database(str(holdout.DB_PATH))
    knowledge = KnowledgeEngine(database)
    answers = answer_semantics._baseline_cells_engine(knowledge)
    for cik in sorted({question["issuer_cik"] for question in questions}):
        issuer = answer_semantics.issuer_id_for(database, cik)
        if issuer:
            answers.cells(issuer, None)
    baseline_build_ms = round((time.perf_counter() - baseline_started) * 1000, 3)
    concept_resolver = ConceptResolver(knowledge)
    baseline_lookups: list[float] = []
    for question in questions:
        issuer = answer_semantics.issuer_id_for(database, question["issuer_cik"])
        if issuer is None:
            continue
        _resolution, elapsed = _timed(concept_resolver.resolve, issuer, question["concept"],
                                      question["period"], question["cutoff"])
        baseline_lookups.append(elapsed)

    first = questions[0]
    repeated_started = time.perf_counter()
    for _ in range(20):
        resolver.resolve(first["concept"], first["period"], accession=first["accession"],
                         cik=first["issuer_cik"], cutoff=first["cutoff"])
    throughput_ms = round((time.perf_counter() - repeated_started) * 1000 / 20, 3)

    report = {
        "schema": "atlas.answer_semantics.hardening_profile.v1",
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "machine": {"platform": platform.platform(), "python": platform.python_version(),
                    "note": "single VM, single process; compare only like with like"},
        "corpus": {"accessions": len(payloads), "questions": len(questions)},
        "stages_ms": {
            "html_parse_cold": parse_ms,
            "html_parse_warm_cached": warm_parse_ms,
            "statement_classification": classification_ms,
            "geometry_build_cold": cold_ms,
            "baseline_cell_extraction": baseline_build_ms,
            "geometry_resolution_total": round(sum(lookups), 3),
            "geometry_resolution_mean": round(statistics.fmean(lookups), 3) if lookups else None,
            "verification_total": round(verification_ms, 3),
            "verification_cases": verified,
            "repeated_query_mean": throughput_ms,
        },
        "diagnostics": {"geometry_unresolved": failures,
                        "baseline_questions_measured": len(baseline_lookups)},
        "memory": {"peak_tracemalloc_mb": round(peak / 1e6, 1),
                   "note": "geometry tables for all twelve filings, one process"},
        "historical_first_run": HISTORICAL,
        "comparison": {
            "geometry_cold_ms_delta": round(cold_ms - HISTORICAL["geometry_cold_ms"], 3),
            "baseline_warm_mean_ms": round(statistics.fmean(baseline_lookups), 3)
            if baseline_lookups else None,
            "geometry_warm_mean_ms": round(statistics.fmean(lookups), 3) if lookups else None,
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["stages_ms"], indent=1))
    print(f"peak {report['memory']['peak_tracemalloc_mb']} MB; wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
