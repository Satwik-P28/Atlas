# ADR 0008 — Complete SEC filing history and incremental archive sync

- **Status**: accepted (Phase 1.1)
- **Date**: 2026-11-04

## Context

Phase 1 ingested only `filings.recent` (~1,000 filings) and reported the archives listed
in `filings.files` as "not fetched". That was honest but not neutral: company facts whose
accession was older than `recent` had no filing metadata, so their public availability
fell back to **date precision** (end-of-day UTC on the filed date) instead of the exact SEC
acceptance timestamp. For Apple that was 1,997 of 5,737 facts — a third of the dataset
whose intraday point-in-time behaviour was weaker than it needed to be.

## Decision

1. **Fetch every archive SEC advertises.** `SecIngestor.sync` follows each entry in
   `filings.files`, subject to the same rate limit and raw-document storage as any other
   request. `--no-history` exists for callers who explicitly want the shallow sync, and
   `--history-limit N` bounds it.
2. **Parse the real layout, and prove it.** Archive documents are *not* shaped like
   `filings.recent`: the live files are a flat map of parallel arrays at the top level,
   with no `filings` wrapper. `sec_history.parse_history_payload` accepts that shape, a
   `filings` wrapper holding a list of objects, and a top-level list, and records which
   layout it saw. Tests assert the live layout against four real issuers.
3. **Ingest archives before facts.** Availability resolution needs the archive's
   acceptance timestamps, so history is upserted first and the fact parser receives a
   filing index rebuilt **from storage** (`FilingRepository.filing_index`).
4. **Incremental by content hash.** `submissions_file` stores the archive's SHA-256 and
   raw-document id. An archive whose bytes are unchanged is skipped. Re-parsing would be
   idempotent anyway (filings upsert on accession); the hash makes the skip safe rather
   than merely convenient.
5. **Never claim completeness without coverage.** `HistoryCoverage` reports expected,
   recorded and missing archives plus advertised versus stored row counts. A shortfall is
   an explicit issue (`filing_history_incomplete`), not a silent gap.

## Evidence (measured)

Apple, CIK 0000320193, from the archived payloads:

| Metric | Before | After |
|---|---|---|
| Filings stored | 1,001 | 2,272 |
| Facts with `exact` availability | 3,740 | **5,737** |
| Facts with `date` availability | 1,997 | **0** |
| Facts with `unknown` availability | 0 | 0 |
| Archive coverage | 0 of 1 | 1 of 1, rows 1,271/1,271 |

## Consequences

* A first sync costs one extra request per archive (Apple: 1). The archives are large
  (200–310 KB each) but fetched once and cached.
* An archive that fails mid-sync is recorded as an issue and leaves coverage incomplete;
  the rest of the sync still completes.
* Archives are immutable in practice, so repeated syncs do no parsing work. If SEC
  revises an archive, the hash changes and it is re-parsed; filings still upsert.
* The advertised count is compared with the parsed row count. A mismatch is reported, not
  reconciled — the archive or the descriptor is stale and either could be wrong.
* Pre-1994 history does not exist in EDGAR's submissions API, and issuers whose filings
  predate XBRL will still produce no facts for those years. The filing list is complete;
  the fact coverage is limited by XBRL availability, not by this change.
