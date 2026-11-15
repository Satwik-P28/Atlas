# Phase 9.6 — Temporal Integrity

## Provenance recorded per document

| Field | Meaning |
| --- | --- |
| `period_of_report` | fiscal period the filing covers |
| `filing_date` | EDGAR filing date (date precision) |
| `acceptance_time` | EDGAR acceptance timestamp |
| `availability_time` | `acceptance_time + SEC_PUBLICATION_LAG_SECONDS` (900 s) |
| `availability_precision` | how precise the availability claim is |
| `ingestion_time` | when Atlas stored the bytes |
| `accession`, `is_amendment`, `amends` | document identity and amendment relationship |

**Why the lag exists.** EDGAR acceptance is when the submission was received, not when the public
could read it. Treating acceptance as availability would let a research query "know" a filing
minutes before it was publicly retrievable. Atlas therefore stores availability as
acceptance + 900 s and records `availability_basis='sec_acceptance_plus_publication_lag'`. That
is a conservative convention, not a measured publication instant; filings whose true availability
is unknown are recorded as uncertain rather than given invented precision.

## Policies

* `public_available` — a document is usable when `availability_time <= cutoff`. This is the
  default and the only policy used in the Phase 9.6 evaluation.
* `atlas_ingested` — a document is usable when Atlas had actually ingested it at the cutoff.
  This is stricter when ingestion lagged and is what reproduces "what did the system know then".

Both policies are exercised by the evaluator; every question record carries the cutoff and
policy used, and every returned document carries its `availability_time`, so a leak can be
audited from the artifact rather than trusted from a summary.

## Measured outcome

* Future-leak rate: **0.0000** for both retrieval methods over 112 questions.
* Cross-issuer contamination: **0.0000**.
* The evaluator recomputes availability per returned passage rather than assuming the SQL filter
  worked, so a filter regression would surface as a non-zero leak rate.

## Case-study cutoff

Both companies were read at the same cutoff, `2021-06-30T00:00:00Z`. Boeing's retrieved annual
report is FY2019 (`0000012927-19-000010`) and Lockheed Martin's is FY2020
(`0000936468-21-000013`): the latest available annual report before that cutoff differs by issuer,
and the case study states this rather than implying period equivalence.

## Gaps (not repaired in 9.6)

* No new adversarial boundary tests were added for the exact acceptance/availability second, for
  amendments published after a cutoff, or for a corpus that grows between two identical queries.
  The evaluator measures leaks on real data, but these property tests remain outstanding.
* `availability_precision` is recorded for date-only sources but the intraday reconstruction path
  refuses rather than interpolating; that refusal is documented, not tested end-to-end.
