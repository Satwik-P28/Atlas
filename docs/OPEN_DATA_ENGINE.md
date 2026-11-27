# Atlas Data Engine

The Data Engine acquires, validates, stores and integrates public financial data. It is
deliberately separate from the evidence kernel's schema: raw provider payloads have a
different lifecycle and scale from normalised, point-in-time issuer facts. The kernel
remains the authority for issuer evidence; the open-data index is the authority for
dataset acquisition, coverage and provenance.

## What it guarantees

| Guarantee | Mechanism |
| --- | --- |
| Default deny | A dataset without a reviewed `rights_class`, licence and evidence date cannot be acquired or distributed. |
| Exact source bytes | Every file is stored content-addressed by SHA-256; the raw snapshot is the authority. |
| Immutable snapshots | Blobs are chmod `0444`; snapshots are published with one directory rename; existing snapshot ids are never overwritten. |
| No silent replacement | An identical observation is skipped; a changed value becomes a new `revision_seq` that supersedes the old row. Old values remain. |
| Honest time semantics | Observation, provider-revision, publication and ingestion times are separate columns. Missing publication dates are `NULL`, never invented. |
| Validated publication | A failed structural check quarantines the staging directory; nothing enters the dataset directory. |
| Reproducibility | Each snapshot has a canonical `manifest.json` and a `manifest.sha256` sidecar; `atlas data verify` recomputes every file hash. |
| No re-downloading unchanged bulk data | ETag / Last-Modified / length are checkpointed and checked with `HEAD` before a bulk transfer. |

## Architecture

```
registry.json ──► rights policy ──► acquisition engine ──► content-addressed store
                                         │                        │
                                         ├── adapter ──► observations ──► SQLite index
                                         │                        │
                                         └── manifest ────────────┴──► coverage dashboard
                                                                     │
                                          SEC company facts ──► evidence kernel (bridge)
```

### Registry and rights

`data/open_data/registry.json` is generated from `scripts/build_open_data_registry.py`.
Every entry records the provider, official source, download endpoint, licence, licence
URL, review date, commercial/redistribution/modification permissions, attribution,
third-party exclusions, geography, historical coverage, update frequency,
authentication, expected size, schema version, ingestion status and adapter.

The six classes are:

| Class | Acquire | Analyse | Publish |
| --- | --- | --- | --- |
| `public_domain` | yes | yes | yes |
| `permissive` | yes | yes | yes |
| `redistributable_conditions` | yes | yes | yes, after conditions and exclusions |
| `local_use_only` | yes | yes | no |
| `restricted` | no | no | no |
| `unverified` | no | no | no |

Published packages additionally require `redistribution=true`, `commercial_use=true`, a
review less than 365 days old and no uncleared third-party exclusions. `FRED` is
classified `local_use_only` because its terms prohibit extraction and redistribution of
third-party series; source-of-record agencies (BLS, BEA, Treasury, Federal Reserve)
are acquired directly instead. Market-vendor and FINRA entries are retained as explicit
negative results so the exclusion is auditable.

### Acquisition flow

1. Resolve the registry entry and evaluate the rights decision.
2. Check disk headroom and the provider validator (`HEAD`).
3. Download to a `.staging-*` directory with streaming SHA-256, a byte budget,
   retries with exponential backoff, `Retry-After`, per-host rate limits and HTTP
   Range resume.
4. Validate magic bytes, JSON parsing or tabular headers; inspect archives for
   traversal, absolute paths, links, special files, duplicate names, member count and
   compression-bomb ratios.
5. Run the adapter to count records/entities and extract typed observations.
6. Write a manifest with source, retrieval, rights, validation, stats and file hashes.
7. Atomically publish the snapshot, index it and ingest observations.
8. On any failure, move staging to `quarantine/` with a reason; record the failed run.

### Storage layout

```
var/open_data/
  blobs/sha256/<aa>/<sha256>          immutable source bytes
  datasets/<dataset_id>/<snapshot_id>/
      files/...                       hard links to blobs
      manifest.json
      manifest.sha256
  quarantine/<dataset_id>/<stamp>/quarantine.json
  checkpoints/<dataset_id>.json
  atlas_open_data.db                  acquisition/observation index
```

`atlas data storage` reports logical bytes, unique blob bytes, checkpoints and
quarantine count. Identical bytes from a restated upstream file are stored once.

### Time semantics in observations

`observation` separates:

* `obs_date`, `period_start`, `period_end` — the provider's observation period;
* `provider_revision_at` — a provider revision/filing date when one exists;
* `published_at` — only when the provider publishes an availability timestamp;
* `ingested_at` — when Atlas retrieved the bytes;
* `availability_basis` — why a publication time is known or unknown.

`atlas data query --as-of` filters on `COALESCE(published_at, ingested_at)`, so an
observation whose publication time is unknown never appears in a historical as-of query
before Atlas actually acquired it. This is conservative, not a vintage archive.

### Adapters

| Adapter | Formats | Notes |
| --- | --- | --- |
| `tabular` | CSV, TSV | wide (yield curves) and narrow (BLS series) layouts |
| `fiscal_api` | JSON | Treasury Fiscal Data pagination with total-count checks |
| `json_api` | JSON | offset or `links.next` pagination (FDIC, GLEIF, FDA) |
| `worldbank` | JSON | World Bank indicator pages |
| `sec_companyfacts` | ZIP of JSON | full fact census, bounded observation extraction |
| `sec_submissions` | ZIP of JSON | filer and filing census |
| `sec_financial_statements` | ZIP of TSV | quarterly FSDS, notes, Forms 3/4/5, 13F, N-PORT, N-CEN |
| `cftc` | ZIP of CSV | commitments-of-traders archives |
| `eia_bulk` | ZIP of JSON-lines | EIA bulk series |
| `archive` | any safe archive | structural validation and counts |

Adapters never coerce a missing value to zero, never convert currencies, and never
infer a publication date. Dates before 1900 or more than two years ahead are counted as
implausible, and any future period end is counted separately; both stay in the raw
snapshot but are excluded from advertised coverage. The raw bytes are never rewritten.

## CLI

```bash
atlas data list
atlas data search treasury
atlas data coverage
atlas data sync sec.company_tickers
atlas data sync treasury
atlas data sync macro --automated --max-bytes 50000000
atlas data sync --all-open
atlas data verify
atlas data audit-rights --strict
atlas data storage
atlas data benchmark treasury.nominal_yields
atlas data status
atlas data query --dataset treasury.debt_to_penny --start 2026-01-01 --limit 10
atlas data query --dataset sec.companyfacts --as-of 2024-01-01
atlas data integrate sec-facts --limit 25 --atlas-db var/atlas.db
atlas data dashboard --out artifacts/open_data_dashboard.html
atlas data export-manifest sec.submissions
atlas data adopt sec.companyfacts --snapshot <snapshot-id>  # recovery: re-index stored bytes only
```

`sync` accepts provider groups: `sec`, `treasury`, `macro`, `banking`, `energy`,
`cftc`, `identifiers`. `--automated` applies the public-job rights policy; unverified
datasets are skipped. `--max-bytes` bounds each transfer. `--dry-run` prints selection.

## Integration with Atlas

Two integration paths exist because the data has two shapes:

1. **Issuer evidence.** `atlas data integrate sec-facts` streams a company-facts
   snapshot through the existing, tested `atlas.ingestion.sec_companyfacts` normaliser
   and writes into the evidence kernel. Issuer identity uses the existing
   `SecurityMaster`; the source is the existing `sec-edgar` source entry. The bridge is
   bounded (`--limit`, `--cik`) because the full archive contains tens of millions of
   facts.
2. **Macro, rates, banking and alternative series.** `open_data.observations` are
   queryable through `atlas data query` and the Python API
   `atlas.open_data.integration.observation_rows`. Research code can consume them
   directly without pretending they are issuer facts.

The existing evidence schema is unchanged (still version 14). The open-data index has
its own schema version and can be attached or exported independently.

## Automation

* `.github/workflows/open-data-validation.yml` — registry validation, rights audit,
  offline engine tests including adversarial archives, no-bulk-files-in-Git check.
* `.github/workflows/open-data-acquire.yml` — manual `workflow_dispatch` with dataset
  selection, smoke/bulk mode, byte budget, force, explicit publish toggle, disk check,
  verification, manifest export and artifact upload.
* `.github/workflows/open-data-scheduled.yml` — weekly small incremental acquisition
  only; no multi-gigabyte archives and no publication.
* `scripts/build_open_data_package.py` — rights-gated local package builder; uploads
  nothing.

See [OPEN_DATA_DISTRIBUTION.md](OPEN_DATA_DISTRIBUTION.md) for channel limits and the
release process, and [OPEN_DATA_ACQUISITION_REPORT.md](OPEN_DATA_ACQUISITION_REPORT.md)
for measured results.

## CDG research decision

The CDG evidence-retrieval repository does contain working implementations, not only
prose: `experiments/round-31/snapshot_store.py` (independently compressed Zstd frames
with exact source-byte reconstruction and generation-bound receipts) and
`experiments/round-32/incremental_store.py` (content-addressed frame reuse across
versions). An earlier note that the project had "no codec in tree" was wrong and is
corrected here.

The implementations are still not integrated, and this engine does not add their
frame/index machinery, because no matched evaluation exists on Atlas's own workload. Its
published results are bounded: small text corpora, no peer-reviewed claim, and several
experiments where the conventional control (native SQLite/FTS5 or plain Zstd) is equal or
better (R29 records a negative result on read-time). No measured CDG result applies to a
1.4 GB financial archive or a 127 million-fact census, and Atlas's archive requirement is
much weaker than CDG's target: the SEC publishes immutable archives, so exact historical
reconstruction is already satisfied by keeping the source bytes and a SHA-256 per member.

A matched experiment would need successive real SEC snapshots and a conventional
control (raw archive, Zstd, per-file Zstd, content-defined chunk dedup) on the same
corpus. That has not been run. The legitimate candidate for later work remains
contentless FTS5 for evidence search, not storage of raw provider archives.

## Reproduction

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev,columnar,open-data]'
.venv/bin/python scripts/build_open_data_registry.py --check
.venv/bin/python scripts/audit_open_data.py --strict
.venv/bin/python scripts/audit_open_data.py --live --samples --strict
.venv/bin/python -m pytest tests/test_open_data_engine.py tests/test_open_data_bootstrap.py
.venv/bin/atlas data sync sec.company_tickers treasury.nominal_yields
.venv/bin/atlas data verify
.venv/bin/atlas data dashboard
```

## Columnar evidence queries

A built columnar dataset answers without being imported into SQLite:

```bash
atlas data columnar --root var/open_data/columnar summary
atlas data columnar --root var/open_data/columnar companies "berkshire"
atlas data columnar --root var/open_data/columnar statement 0001067983 --as-of 2024-06-30T00:00:00Z
atlas data columnar --root var/open_data/columnar screen --concept revenue \
  --fiscal-year 2023 --period annual --currency USD --unit USD --minimum 1000000000
atlas data columnar --root var/open_data/columnar restatements 0000320193
atlas data columnar --root var/open_data/columnar availability 0000320193
atlas data columnar --root var/open_data/columnar materialize 0000320193 --atlas-db var/atlas.db
```

`materialize` is the bridge to every SQLite-backed interface: the issuer is imported from
the exact archived bytes, transactionally, and then statements, comparisons, valuations
and the terminal API answer for it as usual.

The same reads are exposed to MCP clients without accepting a filesystem path from the
caller — the dataset root is operator configuration:

```bash
atlas mcp --columnar-root var/open_data/columnar
# tools: search_columnar_companies, query_columnar_evidence, screen_columnar
```

Historical reads exclude observations whose public availability is unknown or only
modelled, and report how many were excluded. Screening refuses mixed units, currencies,
durations and scopes rather than ranking incomparable numbers, and returns every refusal
with its reason. Restatements are keyed by the full observation identity (concept, unit,
currency, scope, duration, period and fiscal period), so an annual figure is never
confused with its fourth quarter and a repeated comparative is not a revision.
