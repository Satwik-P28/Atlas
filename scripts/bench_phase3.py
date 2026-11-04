"""Reproducible Phase 3 benchmarks.

The 300-issuer universe is explicitly synthetic and is labelled as such. The five-issuer
workload uses whatever is stored in ``var/atlas.db`` (IBM SEC facts plus demonstration
issuers in the delivered database).
"""

from __future__ import annotations

import json
import statistics
import time
import tracemalloc
from datetime import date
from decimal import Decimal

from atlas.core.temporal import ReportingPeriod, availability_from_instant
from atlas.entities.master import SecurityMaster
from atlas.evidence.kernel import EvidenceKernel
from atlas.evidence.model import EvidenceRecord
from atlas.fec import ExecutionEngine, compile_model
from atlas.storage.db import Database
from atlas.storage.sources import ensure_default_sources
from atlas.terminal import metric_store, screener


def timed(fn, repeats: int = 1) -> float:
    values = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        values.append((time.perf_counter() - started) * 1000)
    return statistics.median(values)


def screen(db: Database) -> dict:
    return screener.run_screener(db, filters=[], limit=200)


def compiler_chain(size: int) -> dict:
    nodes = []
    previous = "x"
    for index in range(size):
        node_id = f"n{index}"
        nodes.append({"id": node_id, "op": "add", "inputs": [previous, previous] if index == 0 else [previous, "x"]})
        previous = node_id
    spec = {
        "schema_version": "atlas.model.v1", "name": f"chain-{size}", "interface": "graph",
        "inputs": [{"name": "x", "type": "Scalar"}], "nodes": nodes,
        "outputs": {"value": previous},
    }
    tracemalloc.start()
    started = time.perf_counter()
    model = compile_model(spec)
    compile_ms = (time.perf_counter() - started) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    engine = ExecutionEngine()
    started = time.perf_counter()
    result = engine.execute(model, {"x": 1})
    execute_ms = (time.perf_counter() - started) * 1000
    repeat_ms = timed(lambda: engine.execute(model, {"x": 1}), 5)
    return {
        "nodes": size, "compile_ms": round(compile_ms, 3),
        "compile_peak_kib": round(peak / 1024, 1), "execute_ms": round(execute_ms, 3),
        "cached_execute_median_ms": round(repeat_ms, 3),
        "output": result["outputs"]["value"],
    }


def synthetic_db(issuers: int) -> Database:
    db = Database(":memory:")
    db.migrate()
    ensure_default_sources(db)
    master = SecurityMaster(db)
    master.ensure_venue("XNAS", "Synthetic venue", country="US")
    kernel = EvidenceKernel(db)
    end = date(2023, 12, 31)
    start = date(2023, 1, 1)
    availability = availability_from_instant("2024-02-01T16:00:00Z", "synthetic.benchmark")
    concepts = {
        "revenue": 1000, "net_income": 100, "operating_income": 150, "assets": 2000,
        "liabilities": 800, "equity": 1200, "shares_outstanding": 100,
        "operating_cash_flow": 200, "capex": -50, "cash_and_equivalents": 200,
        "long_term_debt": 300, "short_term_debt": 100,
    }
    for index in range(issuers):
        issuer = master.register_issuer(
            legal_name=f"Synthetic Co {index:03d}", cik=f"9{index:09d}",
            source_id="atlas-synthetic",
        )
        security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
        listing = master.ensure_listing(security, "XNAS", valid_from="2020-01-01", is_primary=True)
        master.assign_ticker(listing, f"S{index:04d}", valid_from="2020-01-01",
                             confidence=0.2, status="unverified", source_id="atlas-synthetic")
        for concept, base in concepts.items():
            value = float(base) * (1 + (index % 17) / 100)
            kernel.ingest(EvidenceRecord.build(
                entity_id=issuer, entity_kind="issuer", concept=concept,
                source_id="atlas-synthetic", unit="shares" if concept == "shares_outstanding" else "USD",
                availability=availability,
                period=ReportingPeriod(end=end, start=None if concept in {"assets", "liabilities", "equity", "shares_outstanding", "cash_and_equivalents", "long_term_debt", "short_term_debt"} else start,
                                       fiscal_year=2023, fiscal_period="FY"),
                value=Decimal(str(value)), accession_number=f"SYN-{index:04d}",
                form_type="SYNTHETIC", filed_date="2024-02-01", observed_at="2024-02-01T16:00:00Z",
                quality="unverified", verification="unchecked", source_dataset="synthetic.benchmark",
                taxonomy="synthetic", source_concept=concept,
            ))
    return db


def main() -> None:
    report = {}
    real = Database("var/atlas.db", create=False)
    real.migrate()
    real.execute("DELETE FROM metric_snapshot")
    report["real_database"] = {
        "issuers": int(real.scalar("SELECT COUNT(*) FROM issuer", default=0) or 0),
        "evidence": int(real.scalar("SELECT COUNT(*) FROM evidence", default=0) or 0),
        "cold_screen_ms": round(timed(lambda: screen(real)), 2),
        "warm_screen_median_ms": round(timed(lambda: screen(real), 5), 2),
    }
    real.close()

    synthetic = synthetic_db(300)
    report["synthetic_300"] = {
        "label": "fully synthetic; not market coverage",
        "issuer_count": int(synthetic.scalar("SELECT COUNT(*) FROM issuer", default=0) or 0),
        "cold_screen_ms": round(timed(lambda: screen(synthetic)), 2),
        "warm_screen_median_ms": round(timed(lambda: screen(synthetic), 5), 2),
    }
    synthetic.close()

    report["compiler"] = [compiler_chain(size) for size in (10, 100, 1000)]
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
