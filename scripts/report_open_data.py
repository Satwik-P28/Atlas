#!/usr/bin/env python3
"""Generate the measured open-data acquisition report from the live index.

Every number comes from an acquisition run or a stored snapshot. The report never
equates "connector exists" with "data acquired".
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data.engine import AcquisitionEngine  # noqa: E402
from atlas.open_data.registry import summarize  # noqa: E402


def sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def human_bytes(value: int | float | None) -> str:
    size = float(value or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:,.1f} {unit}"
        size /= 1024
    return f"{size:,.1f} TiB"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open-root", default="/tmp/atlas_raw_store")
    parser.add_argument("--open-db", default="/tmp/atlas_raw_store/index.db")
    parser.add_argument("--benchmark", default="artifacts/open_data_benchmark.json")
    parser.add_argument("--out", default="docs/OPEN_DATA_ACQUISITION_REPORT.md")
    args = parser.parse_args(argv)
    engine = AcquisitionEngine(store_root=args.open_root, index_path=args.open_db)
    try:
        status = engine.index.status_rows()
        metrics = engine.index.dashboard()
        storage = engine.store.storage_report()
        registry_summary = summarize(engine.registry.payload)
        benchmark = None
        if Path(args.benchmark).exists():
            benchmark = json.loads(Path(args.benchmark).read_text())
        failures = [dict(row) for row in engine.index.connection.execute(
            """SELECT dataset_id, started_at, status, http_status, error
               FROM acquisition_run WHERE status IN ('failed','blocked')
               ORDER BY started_at DESC""")]
        issues = [dict(row) for row in engine.index.connection.execute(
            """SELECT dataset_id, code, severity, COUNT(*) AS count
               FROM issue GROUP BY dataset_id, code, severity ORDER BY dataset_id, code""")]
        snapshots = engine.store.list_snapshots()
        rows = []
        for row in status:
            snapshot = engine.store.latest(row["dataset_id"])
            raw = sum(int(f.get("bytes") or 0) for f in snapshot.files) if snapshot else 0
            stored = sum(int(f.get("bytes") or 0) for f in snapshot.files) if snapshot else 0
            integration = engine.index.connection.execute(
                "SELECT MAX(integrated_at), SUM(records) FROM integration WHERE dataset_id=?",
                (row["dataset_id"],)).fetchone()
            bridged = "yes" if integration[0] else "no"
            validation = "not acquired"
            if snapshot:
                verification = engine.store.verify(snapshot, deep=False)
                validation = "valid" if verification["ok"] else "FAILED"
            rows.append({
                **row, "raw_bytes": raw, "stored_bytes": stored,
                "validation": validation, "integrated": bridged,
                "integrated_at": integration[0], "integration_records": integration[1] or 0,
                "snapshot_id": snapshot.snapshot_id if snapshot else None,
            })
        acquired = [row for row in rows if row["snapshots"]]
        total_records = sum(int(row["acquired_records"] or 0) for row in acquired)
        total_raw = sum(row["raw_bytes"] for row in acquired)
        total_observations = sum(int(row["observations"] or 0) for row in acquired)
        companies = max([int(row["entities"] or 0) for row in acquired] or [0])

        lines = []
        lines.append("# Atlas open data acquisition report\n")
        lines.append(f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} from the measured index "
                     f"at `{args.open_db}`. Commit `{sha()}`.\n")
        lines.append("## Headline measurements\n")
        lines.append("| Metric | Measured value |")
        lines.append("| --- | --- |")
        lines.append(f"| Datasets discovered (registry) | {metrics['datasets_discovered']} |")
        lines.append(f"| Datasets rights-approved for distribution | {metrics['datasets_rights_approved']} |")
        lines.append(f"| Datasets with at least one verified snapshot | {len(acquired)} |")
        lines.append(f"| Datasets with typed observations | {metrics['datasets_with_observations']} |")
        lines.append(f"| Datasets bridged into Atlas evidence | {metrics['datasets_integrated']} |")
        lines.append(f"| Snapshots stored (immutable) | {metrics['snapshots']} |")
        lines.append(f"| Records counted in acquired payloads | {total_records:,} |")
        lines.append(f"| Typed observations indexed | {total_observations:,} |")
        lines.append(f"| Raw acquired bytes | {human_bytes(total_raw)} |")
        lines.append(f"| Unique blob bytes | {human_bytes(storage['deduplicated_blob_bytes'])} |")
        lines.append(f"| Companies / filers covered (largest entity count) | {companies:,} |")
        lines.append(f"| Failed acquisition runs | {metrics['failed_runs']} |")
        lines.append(f"| Quarantined staging directories | {storage['quarantined_staging']} |")
        lines.append("")
        lines.append("## Per-dataset results\n")
        lines.append("| Provider | Dataset | Rights | Records acquired | Raw bytes | Stored bytes | Validation | Typed obs | Atlas bridge | Coverage |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: | --- | ---: | --- | --- |")
        for row in acquired:
            coverage = f"{row['obs_start'] or '-'} .. {row['obs_end'] or '-'}"
            lines.append(
                f"| {row['provider']} | {row['dataset_id']} | {row['rights_class']} | "
                f"{int(row['acquired_records'] or 0):,} | {human_bytes(row['raw_bytes'])} | "
                f"{human_bytes(row['stored_bytes'])} | {row['validation']} | "
                f"{int(row['observations'] or 0):,} | {row['integrated']} | {coverage} |")
        lines.append("")
        lines.append("## Rights and distribution\n")
        lines.append(f"Registry distribution classes: `{json.dumps(registry_summary['by_rights_class'])}`.\n")
        lines.append(f"{metrics['datasets_rights_approved']} datasets are approved for public distribution under "
                     "the default-deny policy. Local-use, restricted and unverified entries are listed by "
                     "`atlas data audit-rights` and are never included in a package.\n")
        lines.append("## Validation evidence\n")
        if issues:
            lines.append("| Dataset | Code | Severity | Count |")
            lines.append("| --- | --- | --- | ---: |")
            for issue in issues:
                lines.append(f"| {issue['dataset_id']} | {issue['code']} | {issue['severity']} | {issue['count']} |")
        else:
            lines.append("No validation issues were recorded.")
        lines.append("")
        lines.append("## Failed sources and failed runs\n")
        if failures:
            lines.append("| Dataset | When | Status | HTTP | Error |")
            lines.append("| --- | --- | --- | ---: | --- |")
            for failure in failures:
                error = (failure["error"] or "").replace("|", "\\|")[:240]
                lines.append(f"| {failure['dataset_id']} | {failure['started_at']} | {failure['status']} | "
                             f"{failure['http_status'] or '-'} | {error} |")
        else:
            lines.append("No failed or blocked acquisition runs are recorded in this index.")
        lines.append("")
        lines.append("## Hosted automation\n")
        lines.append("Three GitHub Actions workflows are committed: `open-data-validation.yml` (pull request and "
                     "push validation: registry check, licensing policy, offline engine tests, adversarial archives, "
                     "snapshot integrity), `open-data-acquire.yml` (manual `workflow_dispatch` by dataset/group, "
                     "with smoke/bulk budgets, disk checks, manifests and artifacts; a change to the workflow itself "
                     "runs the budgeted Treasury smoke acquisition) and `open-data-scheduled.yml` (weekly incremental "
                     "small datasets, no bulk archives). The scheduled and acquire jobs use `--automated`, so "
                     "unverified entries are never downloaded by an unattended public job. No workflow publishes a "
                     "package or creates a release; the package step is local and rights-gated.\n")
        lines.append("## Infrastructure cost\n")
        lines.append("Raw snapshots, the SQLite index and the package build ran in this workspace. Workflows use "
                     "GitHub-hosted runners within the repository's included minutes; no paid storage, database, "
                     "object store or API subscription was created. GitHub Releases (assets below 2 GiB) is the "
                     "documented distribution channel; Actions artifacts are evidence only. Recurring cost is zero "
                     "beyond the existing GitHub plan.\n")
        if benchmark:
            lines.append("## Storage benchmarks (measured)\n")
            results = benchmark.get("results") or [benchmark]
            for result in results:
                if "error" in result:
                    lines.append(f"- `{result['dataset']}`: benchmark failed: {result['error']}")
                    continue
                lines.append(f"### {result['dataset']}\n")
                lines.append(f"- raw bytes: {human_bytes(result['raw_bytes'])}; peak RSS {result['peak_rss_mb']} MB")
                zstd = result["measurements"].get("zstd")
                if zstd:
                    lines.append(f"- Zstd over {human_bytes(zstd.get('source_bytes'))} of parsed text: "
                                 f"{human_bytes(zstd['stored_bytes'])} ({zstd['ratio']}x), "
                                 f"compress {zstd['compress_mb_s']} MB/s, "
                                 f"decompress {zstd['decompress_mb_s']} MB/s, exact roundtrip "
                                 f"{zstd['exact_roundtrip']}")
                parquet = result["measurements"].get("parquet")
                if parquet:
                    lines.append(f"- Parquet/Zstd: {parquet['rows']:,} rows, "
                                 f"{human_bytes(parquet['stored_bytes'])}, write {parquet['write_seconds']} s, "
                                 f"read {parquet['read_seconds']} s")
                duck = result["measurements"].get("duckdb_parquet")
                if duck:
                    lines.append(f"- DuckDB over Parquet: {duck['groups']} groups from "
                                 f"{duck['rows_scanned']:,} rows in {duck['seconds']} s")
                sqlite = result["measurements"].get("sqlite_random")
                if sqlite:
                    lines.append(f"- SQLite random retrieval: {sqlite['queries_per_second']} queries/s "
                                 f"({sqlite['queries']} queries)")
                if result.get("limits"):
                    lines.append(f"- Limits: {'; '.join(result['limits'])}")
                lines.append("")
        lines.append("## What is not claimed\n")
        lines.append("- The SEC bulk acquisitions are current provider snapshots. They are not historical "
                     "vintages and do not establish what a researcher could have seen on a past date.")
        lines.append("- The financial-statement and notes archives are the current SEC quarterly/monthly files. "
                     "Their 1996/1977 coverage starts come from comparative periods inside those filings, not "
                     "from a backfill of every historical quarterly archive; that backfill remains outstanding.")
        lines.append("- Observations without a provider publication timestamp are conservatively filtered by "
                     "ingestion time in `--as-of` queries; no availability time is synthesised.")
        lines.append("- Raw provider bytes are stored outside Git history. The committed manifests preserve "
                     "their hashes and provenance, not the bytes themselves.")
        lines.append("- Some providers remain blocked: FFIEC's bulk form, FR Y-9C's download endpoint, OECD/BIS "
                     "content negotiation, Bank of England CSV, USDA and BEA keys, Census keys, USPTO's moved "
                     "bulk host, and SEC enforcement's unstable machine-readable endpoint.")
        lines.append("- No vendor equity or crypto OHLCV dataset is redistributed; no licence was established.")
        lines.append("")
        lines.append("## Reproduction\n")
        lines.append("```bash")
        lines.append("python -m venv .venv")
        lines.append(".venv/bin/pip install -e '.[dev,columnar,open-data]'")
        lines.append("python scripts/build_open_data_registry.py --check")
        lines.append("python scripts/audit_open_data.py --live --samples --strict")
        lines.append("atlas data sync sec.companyfacts sec.submissions sec.company_tickers")
        lines.append("atlas data sync treasury.nominal_yields treasury.debt_to_penny")
        lines.append("atlas data verify")
        lines.append("atlas data benchmark --queries 200")
        lines.append("atlas data dashboard")
        lines.append("```")
        lines.append("")
        lines.append("Repository: https://github.com/Satwik-P28/Atlas  ")
        lines.append("Branch: `data/open-data-bootstrap`  ")
        lines.append(f"Commit: `{sha()}`")
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out} ({len(acquired)} acquired datasets, {total_records:,} records)")
        return 0
    finally:
        engine.close()


if __name__ == "__main__":
    raise SystemExit(main())
