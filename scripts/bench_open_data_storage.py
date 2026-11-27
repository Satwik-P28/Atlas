#!/usr/bin/env python3
"""Compare eager SQLite evidence storage with partitioned Parquet and a hybrid.

All architectures are built from the *same* SEC companyfacts archive and cover the
*same* companies (the first ``--companies`` members in the archive's deterministic
name order), so no result compares a complete database with a sampled columnar set.

Architectures
-------------
A ``sqlite``  eager integration through the production kernel (`integrate_companyfacts`)
B ``parquet`` partitioned Parquet/Zstandard queried in place with DuckDB
C ``hybrid``  the columnar dataset plus on-demand materialisation of single companies
D ``cdg``     evidence-preserving compression, only if a codec exists in the tree
              (none does; reported as not_applicable with the reason)

Each phase runs in its own subprocess when ``--phase all`` is used, so peak resident
memory is measured for that architecture alone rather than for the maxima of all.

Example
-------
    python scripts/bench_open_data_storage.py --phase all --companies 500 \
        --root /tmp/atlas_p4 --out artifacts/open_data_storage_benchmark.json
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.core.ids import normalize_cik  # noqa: E402
from atlas.open_data.columnar import (  # noqa: E402
    ColumnarEvidence, build_from_archive, extract_member, load_manifest, totals,
)


# ------------------------------------------------------------------------- measuring
def _rusage() -> dict[str, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "peak_rss_kb": int(usage.ru_maxrss),
        "cpu_user_seconds": round(usage.ru_utime, 3),
        "cpu_system_seconds": round(usage.ru_stime, 3),
    }


def _time(call: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    result = call()
    return result, round((time.perf_counter() - started) * 1000, 3)


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean_ms": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    ordered = sorted(values)
    def at(fraction: float) -> float:
        index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
        return round(ordered[index], 3)
    return {"mean_ms": round(sum(ordered) / len(ordered), 3), "p50_ms": at(0.5),
            "p95_ms": at(0.95), "max_ms": round(ordered[-1], 3)}


# ------------------------------------------------------------------------- fixtures
def _tracked_snapshot(store_root: Path) -> tuple[Path, str]:
    """The newest acquired companyfacts snapshot in a store."""
    from atlas.open_data.store import SnapshotStore

    store = SnapshotStore(store_root)
    snapshot = store.latest("sec.companyfacts")
    if snapshot is None:
        raise SystemExit(f"no sec.companyfacts snapshot in {store_root}")
    archive = next(snapshot.path / "files" / entry["path"] for entry in snapshot.files
                   if entry["name"].endswith("companyfacts.zip"))
    return archive, snapshot.snapshot_id


def _archive_members(archive: Path, limit: int) -> list[str]:
    import zipfile

    with zipfile.ZipFile(archive) as bundle:
        return sorted(name for name in bundle.namelist() if name.endswith(".json"))[:limit]


def _target_companies(archive: Path, limit: int) -> tuple[list[str], list[str]]:
    """The first ``limit`` members that carry a CIK, in archive name order.

    `integrate_companyfacts` resumes by counting processed CIKs, so its target set is
    the first N unique CIKs. The columnar build is given exactly these members, which
    is what keeps the two architectures comparable.
    """
    import zipfile

    ciks: list[str] = []
    members: list[str] = []
    seen: set[str] = set()
    with zipfile.ZipFile(archive) as bundle:
        for name in _archive_members(archive, len(_archive_members(archive, 10**9))):
            try:
                payload = json.loads(bundle.read(name))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            value = payload.get("cik")
            if value is None:
                continue
            cik = normalize_cik(str(value))
            if cik in seen:
                continue
            seen.add(cik)
            ciks.append(cik)
            members.append(name)
            if len(ciks) >= limit:
                break
    return ciks, members


def _concept(sqlite_db: Path) -> str:
    connection = sqlite3.connect(f"file:{sqlite_db}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT concept, COUNT(*) AS n FROM evidence WHERE value_numeric IS NOT NULL "
            "GROUP BY concept ORDER BY n DESC LIMIT 1").fetchone()
        return str(row[0]) if row else "revenue"
    finally:
        connection.close()


# ------------------------------------------------------------------------- SQLite
def _sqlite_queries(db_path: Path, ciks: list[str]) -> dict[str, Any]:
    def connect():
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        return connection

    def fetch(connection, sql: str, params=()):
        return connection.execute(sql, params).fetchall()

    sample = ciks[:20]
    concept = _concept(db_path)
    periods = ciks[:10]

    def company_lookup(cik: str):
        return fetch(connection, "SELECT e.concept, e.value_numeric, e.period_end, "
                                 "e.availability_time, e.accession_number "
                                 "FROM evidence e JOIN issuer i ON i.issuer_id=e.entity_id "
                                 "WHERE i.cik=? ORDER BY e.period_end DESC", (cik,))

    def statement(cik: str):
        period = fetch(connection, "SELECT e.period_end FROM evidence e JOIN issuer i "
                                   "ON i.issuer_id=e.entity_id WHERE i.cik=? "
                                   "ORDER BY e.period_end DESC LIMIT 1", (cik,))
        if not period:
            return []
        return fetch(connection,
                     "SELECT concept, value_numeric FROM (SELECT e.concept, e.value_numeric, "
                     "row_number() OVER (PARTITION BY e.concept ORDER BY e.availability_time DESC) rn "
                     "FROM evidence e JOIN issuer i ON i.issuer_id=e.entity_id "
                     "WHERE i.cik=? AND e.period_end=?) WHERE rn=1",
                     (cik, period[0][0]))

    def screen():
        return fetch(connection,
                     "SELECT i.cik, MAX(CAST(e.value_numeric AS REAL)) AS value "
                     "FROM evidence e JOIN issuer i ON i.issuer_id=e.entity_id "
                     "WHERE e.concept=? GROUP BY i.cik ORDER BY value DESC LIMIT 100",
                     (concept,))

    def point_in_time(cik: str):
        return fetch(connection,
                     "SELECT COUNT(*) FROM evidence e JOIN issuer i ON i.issuer_id=e.entity_id "
                     "WHERE i.cik=? AND (e.availability_time IS NULL OR e.availability_time <= ?)",
                     (cik, "2020-01-01T00:00:00Z"))

    def restatements(cik: str):
        return fetch(connection,
                     "SELECT e.concept, e.period_end, COUNT(DISTINCT e.accession_number) n "
                     "FROM evidence e JOIN issuer i ON i.issuer_id=e.entity_id "
                     "WHERE i.cik=? GROUP BY e.concept, e.period_end "
                     "HAVING n > 1 ORDER BY n DESC LIMIT 50", (cik,))

    results: dict[str, Any] = {}
    connection = connect()
    try:
        results["cold_company"] = _percentiles([_time(lambda c=c: company_lookup(c))[1] for c in sample])
        results["cold_statement"] = _percentiles([_time(lambda c=c: statement(c))[1] for c in periods])
        results["cold_screen"], results["cold_screen_ms"] = _time(screen)
        results["cold_point_in_time"] = _percentiles(
            [_time(lambda c=c: point_in_time(c))[1] for c in periods])
        results["cold_restatements"] = _percentiles(
            [_time(lambda c=c: restatements(c))[1] for c in periods])
    finally:
        connection.close()

    connection = connect()
    try:
        warm_samples = []
        for _ in range(3):
            warm_samples.append(_percentiles([_time(lambda c=c: company_lookup(c))[1] for c in sample]))
        results["warm_company"] = warm_samples[-1]
        results["warm_statement"] = _percentiles(
            [_time(lambda c=c: statement(c))[1] for c in periods])
        results["warm_screen"], results["warm_screen_ms"] = _time(screen)
    finally:
        connection.close()
    results["concept"] = concept
    return results


def phase_sqlite(args, archive: Path, snapshot_id: str) -> dict[str, Any]:
    from atlas.open_data.engine import AcquisitionEngine
    from atlas.open_data.integration import integrate_companyfacts

    workdir = Path(args.workdir) / "sqlite"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    database = workdir / "atlas.db"
    engine = AcquisitionEngine(store_root=Path(args.root) / "store",
                               index_path=workdir / "index.db")
    before = _rusage()
    started = time.perf_counter()
    result = integrate_companyfacts(
        engine, database, snapshot_id=snapshot_id, limit=args.companies,
        batch_size=500, checkpoint_dir=workdir / "checkpoints", tickers=False,
        verify_progress=False,
    )
    ingest_seconds = time.perf_counter() - started
    after = _rusage()
    engine.close()
    # Fold the WAL so the reported size is the durable database, not a transient log.
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    ciks, _ = _target_companies(archive, args.companies)
    queries = _sqlite_queries(database, ciks)
    stats = database.stat().st_size
    return {
        "architecture": "sqlite_eager",
        "companies": result["companies_total"],
        "records": result["records_parsed_total"],
        "database_bytes": stats,
        "bytes_per_record": round(stats / max(1, result["records_parsed_total"]), 2),
        "ingest_seconds": round(ingest_seconds, 2),
        "records_per_second": round(result["records_parsed_total"] / max(ingest_seconds, 1e-9), 1),
        "peak_rss_kb": after["peak_rss_kb"],
        "cpu_seconds": round((after["cpu_user_seconds"] - before["cpu_user_seconds"]) +
                             (after["cpu_system_seconds"] - before["cpu_system_seconds"]), 3),
        "queries": queries,
        "stopped_reason": result["stopped_reason"],
    }


# ------------------------------------------------------------------------ Parquet
def _parquet_queries(root: str | Path, ciks: list[str]) -> dict[str, Any]:
    columnar = ColumnarEvidence(root)
    sample = ciks[:20]
    periods = ciks[:10]
    results: dict[str, Any] = {}

    def concept_counts():
        return columnar.conn.execute(
            "SELECT concept, COUNT(*) FROM fact GROUP BY concept ORDER BY 2 DESC LIMIT 1").fetchone()

    concept = concept_counts()[0]
    results["cold_company"] = _percentiles([_time(lambda c=c: columnar.company(c))[1] for c in sample])
    results["cold_statement"] = _percentiles([_time(lambda c=c: columnar.statement(c))[1] for c in periods])
    results["cold_screen"], results["cold_screen_ms"] = _time(
        lambda: columnar.screen(concept=concept, fiscal_year=2023, limit=100))
    results["cold_point_in_time"] = _percentiles(
        [_time(lambda c=c: columnar.point_in_time(c, "2020-01-01T00:00:00Z"))[1] for c in periods])
    results["cold_restatements"] = _percentiles(
        [_time(lambda c=c: columnar.restatements(c))[1] for c in periods])
    columnar.close()

    columnar = ColumnarEvidence(root)
    results["warm_company"] = _percentiles([_time(lambda c=c: columnar.company(c))[1] for c in sample])
    results["warm_statement"] = _percentiles([_time(lambda c=c: columnar.statement(c))[1] for c in periods])
    results["warm_screen"], results["warm_screen_ms"] = _time(
        lambda: columnar.screen(concept=concept, fiscal_year=2023, limit=100))
    columnar.close()
    results["concept"] = concept
    return results


def phase_parquet(args, archive: Path, snapshot_id: str) -> dict[str, Any]:
    workdir = Path(args.workdir) / "parquet"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    ciks, members = _target_companies(archive, args.companies)
    before = _rusage()
    manifest = build_from_archive(archive, workdir, snapshot_id=snapshot_id,
                                  member_names=members, bucket_count=args.buckets,
                                  progress=False)
    after = _rusage()
    build_seconds = float(manifest["elapsed_seconds"])
    queries = _parquet_queries(workdir, ciks)
    stored = totals(workdir)
    # Exact source reconstruction is measured once; it reads the authoritative archive.
    member = extract_member(workdir, ciks[0])
    verify_sample = ColumnarEvidence(workdir).verify_sources(sample=min(25, len(ciks)))
    return {
        "architecture": "parquet_zstd_duckdb",
        "companies": manifest["companies"],
        "records": manifest["records"],
        "parquet_bytes": stored["parquet_bytes"],
        "manifest_bytes": stored["manifest_bytes"],
        "derived_bytes": stored["derived_bytes"],
        "archive_bytes": stored["archive_bytes"],
        "bytes_per_record": round(stored["parquet_bytes"] / max(1, manifest["records"]), 2),
        "files": stored["files"],
        "ingest_seconds": build_seconds,
        "records_per_second": round(manifest["records"] / max(build_seconds, 1e-9), 1),
        "peak_rss_kb": after["peak_rss_kb"],
        "cpu_seconds": round((after["cpu_user_seconds"] - before["cpu_user_seconds"]) +
                             (after["cpu_system_seconds"] - before["cpu_system_seconds"]), 3),
        "queries": queries,
        "exact_source_member": {"member": member["member"], "sha256": member["sha256"]},
        "source_reconstruction": verify_sample,
        "partitioning": manifest["partitioning"],
    }


# ------------------------------------------------------------------------- Hybrid
def phase_hybrid(args, archive: Path, snapshot_id: str) -> dict[str, Any]:
    columnar_root = Path(args.workdir) / "parquet"
    if not (columnar_root / "manifest.json").exists():
        build_from_archive(archive, columnar_root, snapshot_id=snapshot_id,
                           member_names=_target_companies(archive, args.companies)[1],
                           bucket_count=args.buckets)
    workdir = Path(args.workdir) / "hybrid"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True)
    database = workdir / "lazy.db"
    ciks, _ = _target_companies(archive, args.companies)
    chosen = ciks[:8]
    columnar = ColumnarEvidence(columnar_root)
    before = _rusage()
    started = time.perf_counter()
    materialised = [columnar.materialize(cik, database, snapshot_id=snapshot_id) for cik in chosen]
    materialise_seconds = time.perf_counter() - started
    after = _rusage()
    queries = _parquet_queries(columnar_root, ciks)
    columnar.close()
    size = database.stat().st_size
    return {
        "architecture": "hybrid_columnar_lazy_sqlite",
        "companies_indexed": int(load_manifest(columnar_root)["companies"]),
        "companies_materialised": len(chosen),
        "materialise_seconds": round(materialise_seconds, 3),
        "materialise_per_company_seconds": round(materialise_seconds / max(1, len(chosen)), 3),
        "lazy_database_bytes": size,
        "lazy_bytes_per_company": round(size / max(1, len(chosen)), 1),
        "records_materialised": sum(item["inserted"] + item["superseding"] for item in materialised),
        "peak_rss_kb": after["peak_rss_kb"],
        "cpu_seconds": round((after["cpu_user_seconds"] - before["cpu_user_seconds"]) +
                             (after["cpu_system_seconds"] - before["cpu_system_seconds"]), 3),
        "queries": queries,
        "materialised": materialised,
    }


def phase_cdg(args, archive: Path, snapshot_id: str) -> dict[str, Any]:
    found: list[str] = []
    for pattern in ("src/atlas/**/*cdg*", "src/atlas/**/*compression*"):
        found.extend(str(path) for path in ROOT.glob(pattern))
    return {
        "architecture": "cdg_evidence_preserving",
        "status": "not_applicable",
        "reason": (
            "No CDG codec or evidence-preserving compressor exists in this tree. "
            "Implementing a new codec was out of scope for a storage comparison and "
            "would not have a reproducible specification to measure against."),
        "candidate_modules": sorted(found),
    }


PHASES = {"sqlite": phase_sqlite, "parquet": phase_parquet,
          "hybrid": phase_hybrid, "cdg": phase_cdg}


def run_phase(name: str, args, archive: Path, snapshot_id: str) -> dict[str, Any]:
    os.makedirs(args.workdir, exist_ok=True)
    return PHASES[name](args, archive, snapshot_id)


def orchestrate(args) -> dict[str, Any]:
    archive, snapshot_id = _tracked_snapshot(Path(args.root) / "store")
    results: dict[str, Any] = {
        "schema": "atlas.open_data.storage_benchmark.v1",
        "source": {"dataset_id": "sec.companyfacts", "snapshot_id": snapshot_id,
                   "archive": str(archive), "archive_bytes": archive.stat().st_size,
                   "companies": args.companies, "bucket_count": args.buckets},
        "costs": {"usd": 0.0, "note": "local CPU and disk only; no paid infrastructure"},
    }
    phases = ["sqlite", "parquet", "hybrid"] if args.phase == "all" else [args.phase]
    if args.phase == "all":
        phases.append("cdg")
    started = time.perf_counter()
    for name in phases:
        print(f"running phase {name} ...", flush=True)
        command = [sys.executable, str(Path(__file__)), "--phase", name,
                   "--root", args.root, "--workdir", args.workdir,
                   "--companies", str(args.companies), "--buckets", str(args.buckets),
                   "--subprocess-result", str(Path(args.workdir) / f"result-{name}.json")]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            results[name] = {"error": completed.stderr.strip()[-4000:]}
            continue
        results[name] = json.loads(Path(args.workdir, f"result-{name}.json").read_text())
    results["wall_seconds"] = round(time.perf_counter() - started, 1)
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["all", *PHASES], default="all")
    parser.add_argument("--root", default="/tmp/atlas_p4",
                        help="open-data root containing store/ with the SEC snapshot")
    parser.add_argument("--workdir", default="/tmp/atlas_p4/bench")
    parser.add_argument("--companies", type=int, default=500)
    parser.add_argument("--buckets", type=int, default=16)
    parser.add_argument("--out", default=str(ROOT / "artifacts/open_data_storage_benchmark.json"))
    parser.add_argument("--subprocess-result", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.phase == "all":
        payload = orchestrate(args)
    else:
        archive, snapshot_id = _tracked_snapshot(Path(args.root) / "store")
        payload = run_phase(args.phase, args, archive, snapshot_id)
    if args.phase == "all":
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"out": str(target), "phases": list(payload)}, indent=2))
    elif args.subprocess_result:
        Path(args.subprocess_result).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
