# Columnar evidence storage

`src/atlas/open_data/columnar.py` is the Phase IV storage layer: a partitioned Parquet
dataset queried in place with DuckDB, plus lazy per-company materialisation into the
normal SQLite schema. It exists because the eager architecture is not portable: the
Phase III integration produced a 5.79 GB database for 2,000 companies and 4.7 million
records, which is roughly 4.7 GB more than most personal computers want to dedicate to
one dataset.

Measured comparison: `artifacts/open_data_storage_benchmark.json`.
Phase report: `docs/OPEN_DATA_PHASE_IV_REPORT.md`.

## Why this layout

| Decision | Choice | Reason |
| --- | --- | --- |
| Encoding | Parquet, Zstandard, one row group per flush | Columnar compression is what closes the 29x byte gap; a row-group per 50 companies keeps memory bounded without creating thousands of tiny files. |
| Primary partition | CIK bucket, `int(cik) % buckets` | Company-centric research is the dominant workload. A bucket is deterministic, so a rebuild lands in the same files and a bucket file can be replaced without rewriting the dataset. |
| Bucket count | 16 for the 500-company comparison set, 256 for the full universe | Measured at full scale: 256 files of ~4.6 MB give a 9.5 ms company lookup but a 1.9 s full scan; 16 files of ~67 MB give a 25 ms lookup and a 1.2 s scan. Research is company-centric, so the production layout is 256. |
| Fiscal-year partition | No | A company is the retrieval unit; year pruning is a predicate DuckDB already pushes into the column statistics, and partitioning by year would multiply files ~15x and duplicate company reads. |
| Concept family partition | No | Screening spans concepts, and a concept column with dictionary encoding is smaller than a concept partition tree. |
| Accession partition | No | Accessions are high-cardinality (millions) and every accessioned fact is needed for restatement resolution and exact reconstruction. |
| Snapshot partition | No, but recorded | One dataset describes one immutable snapshot (`manifest.archive`), so a new snapshot is a new dataset directory, not a mixed tree. Mixing snapshots in one tree would silently produce non-reproducible answers. |

The file name encodes the bucket (`evidence/cik_bucket=NN/part-000.parquet`). A company
lookup opens exactly the one file its CIK hashes to, using the manifest's file-to-bucket
map; a query that filters only on `cik` over the whole glob reads all 256 files and was
measured at 1.2 s per lookup at full-universe scale. `screen()` still scans every file,
which is the cost of a cross-company query and is reported below.

## What is preserved

Every row carries: `cik`, `entity_name`, `member`, `concept`, `value_numeric` (canonical
decimal text), `unit`, `unit_kind`, `currency`, `period_start`, `period_end`,
`period_type`, `fiscal_year`, `fiscal_period`, `availability_time`,
`availability_precision`, `availability_basis`, `filed_date`, `acceptance_datetime`,
`accession_number`, `form_type`, `revision_kind`, `quality`, `taxonomy`,
`source_concept`, `source_url`, `content_hash`, `source_snapshot`, `ingest_seq`.

So the dataset keeps exact values and units, both reporting and availability timestamps,
the source member hash, accession identity, restatement lineage, historical company
identity per filing, and explicit missing/unsupported markers. It does not keep the raw
JSON blob; exact reconstruction reads the authoritative archive and is checked by
`verify_sources()` and `extract_member()`.

`manifest.json` holds the archive hash and byte count, one entry per member with its
SHA-256 and record count, the file list with per-file row counts, the partitioning
descriptor, rejected members with reasons, and the record/company totals. It is the
reconciliation contract for the dataset.

## Query API

```python
from atlas.open_data.columnar import ColumnarEvidence, build_from_archive, totals

build_from_archive(archive_zip, "data/columnar", snapshot_id="2026-11-26")

with ColumnarEvidence("data/columnar") as evidence:
    evidence.company("0000320193")                       # every fact, newest availability first
    evidence.statement("0000320193", period_end="2025-09-27")
    evidence.screen(concept="revenue", fiscal_year=2025, minimum=1e9, limit=50)
    evidence.point_in_time("0000320193", "2025-11-01T00:00:00Z", "revenue")
    evidence.restatements("0000320193")
    evidence.materialize("0000320193", "research.sqlite")  # canonical SQLite rows for one company
```

`statement()` resolves one value per concept for the requested period. A fiscal year end
is also the end of a fourth quarter, so the same concept can carry a 3-month and a
12-month value for one date; the statement prefers the annual duration, then an instant
(balance-sheet) value, and only falls back to shorter periods when the issuer reports
nothing else. Without that rule the "latest availability" row for annual revenue was
sometimes the Q4 figure filed later, which the Phase IV financial validation caught
(252 concept comparisons disagreed with the source before the fix, 0 after).

## Caches and reproducibility

- The DuckDB connection is a read-only view over the files; there is no cache to
  invalidate. Replacing a bucket file and re-running a query is the invalidation unit.
- `materialize()` writes a normal Atlas SQLite database using the same migration path as
  an online install, so a materialised company is queryable by the kernel and valuation
  code without the archive. The database records the source snapshot and member hash for
  the company, and materialising the same company twice is idempotent.
- Lazy materialisation is bounded: each call adds one company (measured 0.65 s and
  ~4.2 MB), and nothing is written unless requested.

## Measured cost

Matched 500-company slice of `sec.companyfacts` (1,353,397 records, 1.43 GB archive):

| | Eager SQLite | Parquet + DuckDB |
| --- | --- | --- |
| Stored bytes | 1,672 MB | 57.6 MB (29x smaller) |
| Bytes per record | 1,235 | 42.6 |
| Build time | 318 s (4,249 rec/s) | 105 s (12,844 rec/s) |
| Peak RSS | 145 MB | 459 MB |
| Company lookup | 4.5 ms | 24 ms |
| Full-year screen | 300 ms | 52 ms |
| Point-in-time | 1.1 ms | 22 ms |
| Restatements | 2.2 ms | 30 ms |
| Exact source reconstruction | n/a (archive is the source) | 25/25 members byte-identical |

The columnar path is slower per-company by ~20 ms and faster on any workload that scans
across companies; it is 29x smaller on disk, which is the property that decides whether
the complete universe fits on a personal computer. That is why the production read path
is Parquet and SQLite is the materialisation and kernel target rather than the primary
store.

Memory during a build is dominated by one flush buffer plus Arrow overhead; the limit is
`FLUSH_COMPANIES = 50`, and the measured peak at 500 companies was 459 MB. Build cost is
linear in members read: 0.21 s per company for the first 500 (large issuers) and 0.092 s
per company averaged over the whole universe, i.e. 31.5 minutes for 20,558 members.

## Full-universe result

Built from the same `20261126T193010-9af78904` archive (`sha256 f39d0bef…5e8f`), with every
member processed:

| | Full universe |
| --- | --- |
| Members indexed | 20,558 (70 rejected for unparseable JSON or no CIK) |
| Companies with canonical facts | 17,083 |
| Records | 24,822,801 |
| Stored bytes | 1,167,267,980 Parquet + 4,281,163 manifest (1.17 GB) |
| Build time | 1,891 s (31.5 min), one process |
| Files | 256 |

Research workloads on that dataset (`artifacts/open_data_full_universe.json`):

| Workload | 256 buckets | 16 buckets |
| --- | --- | --- |
| Open dataset | 1,946 ms | 615 ms |
| Random company lookup | 9.5 ms mean, 8.2 ms p50 | 25.3 ms mean, 24.1 ms p50 |
| Financial statement for a company | 10.9 ms | 26.2 ms |
| Point-in-time snapshot | 9.9 ms | 27.0 ms |
| Restatement resolution | 15.1 ms | 32.0 ms |
| Cross-company screen (revenue, FY2024, top 100) | 1,916 ms | 1,195 ms |

The full universe fits in 1.17 GB, and a company can be researched in about 10 ms without
importing anything; materialising that one company into SQLite takes 0.6 s and 4.2 MB.

## Limits

- Parquet lookups pay a fixed ~20 ms query-planning and file-open cost; the eager SQLite
  path is faster for a single company already in a local database.
- The dataset stores canonical facts, not the raw payload, so anything the normaliser
  does not map (undocumented tags, non-USD units) is present only as an unsupported or
  missing marker; `extract_member()` and the archive remain the authority.
- The benchmark is a 500-company slice, not the full universe; full-universe build time
  and disk use are extrapolated from the measured per-company rate and the archive size.
