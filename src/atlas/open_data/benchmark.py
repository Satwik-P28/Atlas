"""Storage benchmarks with explicit measurements.

Every number returned here is measured in this process. The module does not claim a
speed-up from the CDG evidence-retrieval research; that work is documented as a
candidate, and is only adopted if a future benchmark shows a benefit on Atlas data.
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import sqlite3
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from .engine import AcquisitionEngine


def _rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _timed(action: Callable[[], Any]) -> tuple[float, Any]:
    start = time.perf_counter()
    value = action()
    return time.perf_counter() - start, value


def benchmark_dataset(engine: AcquisitionEngine, dataset_id: str, *, queries: int = 200) -> dict[str, Any]:
    snapshot = engine.store.latest(dataset_id)
    if snapshot is None:
        raise FileNotFoundError(f"no snapshot for {dataset_id}")
    raw_files = [snapshot.path / "files" / entry["path"] for entry in snapshot.files]
    raw_bytes = sum(path.stat().st_size for path in raw_files)
    workdir = Path(tempfile.mkdtemp(prefix="atlas-bench-"))
    results: dict[str, Any] = {
        "dataset": dataset_id,
        "snapshot_id": snapshot.snapshot_id,
        "raw_bytes": raw_bytes,
        "raw_files": len(raw_files),
        "peak_rss_mb": round(_rss_mb(), 1),
        "measurements": {},
        "limits": [],
    }
    try:
        # --- zstandard -------------------------------------------------------
        try:
            import zstandard as zstd
            source = max(raw_files, key=lambda p: p.stat().st_size)
            compressed = workdir / (source.name + ".zst")
            def compress() -> int:
                cctx = zstd.ZstdCompressor(level=6, threads=2)
                written = 0
                with source.open("rb") as src, compressed.open("wb") as dst:
                    while chunk := src.read(4 << 20):
                        out = cctx.compress(chunk)
                        written += len(out)
                        dst.write(out)
                return written
            elapsed, written = _timed(compress)
            decompressed = workdir / (source.name + ".out")
            def decompress() -> int:
                dctx = zstd.ZstdDecompressor()
                count = 0
                with compressed.open("rb") as src, decompressed.open("wb") as dst:
                    reader = dctx.stream_reader(src)
                    while chunk := reader.read(4 << 20):
                        count += len(chunk)
                        dst.write(chunk)
                return count
            dec_elapsed, count = _timed(decompress)
            results["measurements"]["zstd"] = {
                "source_bytes": source.stat().st_size,
                "stored_bytes": written,
                "ratio": round(source.stat().st_size / written, 3) if written else None,
                "compress_seconds": round(elapsed, 3),
                "decompress_seconds": round(dec_elapsed, 3),
                "compress_mb_s": round(source.stat().st_size / 1e6 / elapsed, 2) if elapsed else None,
                "decompress_mb_s": round(count / 1e6 / dec_elapsed, 2) if dec_elapsed else None,
                "exact_roundtrip": count == source.stat().st_size,
            }
        except ImportError:
            results["limits"].append("zstandard is not installed")

        # --- Parquet from indexed observations -------------------------------
        rows = engine.index.observations(dataset_id, limit=2_000_000)
        if rows:
            try:
                import pyarrow as pa
                import pyarrow.parquet as pq
                parquet = workdir / "observations.parquet"
                def write_parquet() -> int:
                    pq.write_table(pa.Table.from_pylist(rows), parquet, compression="zstd")
                    return parquet.stat().st_size
                parquet_elapsed, parquet_bytes = _timed(write_parquet)
                def read_parquet() -> int:
                    return pq.read_table(parquet).num_rows
                read_elapsed, read_rows = _timed(read_parquet)
                results["measurements"]["parquet"] = {
                    "rows": len(rows),
                    "stored_bytes": parquet_bytes,
                    "write_seconds": round(parquet_elapsed, 3),
                    "read_seconds": round(read_elapsed, 3),
                    "roundtrip_rows": read_rows,
                }
                try:
                    import duckdb
                    connection = duckdb.connect()
                    def duck_query() -> Any:
                        return connection.execute(
                            "SELECT series_key, COUNT(*), MIN(obs_date), MAX(obs_date) "
                            "FROM read_parquet(?) GROUP BY series_key", [str(parquet)]
                        ).fetchall()
                    duck_elapsed, duck_rows = _timed(duck_query)
                    results["measurements"]["duckdb_parquet"] = {
                        "seconds": round(duck_elapsed, 3), "groups": len(duck_rows),
                        "rows_scanned": len(rows),
                    }
                    connection.close()
                except ImportError:
                    results["limits"].append("duckdb is not installed")
            except ImportError:
                results["limits"].append("pyarrow is not installed")

        # --- SQLite random retrieval ----------------------------------------
        if rows:
            connection = sqlite3.connect(engine.index.path)
            connection.row_factory = sqlite3.Row
            sample = [rows[i] for i in range(0, len(rows), max(1, len(rows) // max(1, queries)))][:queries]
            def random_queries() -> int:
                count = 0
                for row in sample:
                    found = connection.execute(
                        "SELECT observation_id FROM observation WHERE dataset_id=? AND series_key=? "
                        "AND obs_date IS ? ORDER BY revision_seq DESC LIMIT 1",
                        (dataset_id, row["series_key"], row["obs_date"]),
                    ).fetchone()
                    count += 1 if found else 0
                return count
            elapsed, found = _timed(random_queries)
            results["measurements"]["sqlite_random"] = {
                "queries": len(sample), "found": found, "seconds": round(elapsed, 4),
                "queries_per_second": round(len(sample) / elapsed, 1) if elapsed else None,
            }
            connection.close()
        results["peak_rss_mb"] = round(_rss_mb(), 1)
        results["benchmark_workspace_mb"] = round(
            sum(p.stat().st_size for p in workdir.rglob("*") if p.is_file()) / 1e6, 2)
        return results
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def benchmark_all(engine: AcquisitionEngine, *, queries: int = 100) -> dict[str, Any]:
    results = []
    for dataset in engine.registry:
        if engine.store.latest(dataset.id) is None:
            continue
        try:
            results.append(benchmark_dataset(engine, dataset.id, queries=queries))
        except Exception as exc:  # a benchmark failure is evidence, not a crash
            results.append({"dataset": dataset.id, "error": f"{type(exc).__name__}: {exc}"})
    return {"datasets": len(results), "results": results, "generated_at": _timestamp()}


def _timestamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
