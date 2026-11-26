# Phase 10.4 — certification status (v0.2.0-beta.1)

Branch `release/v0.2.0-beta.1-final`, built on `integration/phase10.3` at `7151240`. Nothing here
is a roadmap: this page records what was executed, what it produced, and what was not attempted.

## Executed

| Stage | What ran | Result |
|---|---|---|
| 1. Product acceptance | `scripts/accept_phase10_4.py` against a real `atlas serve` on a real demonstration database | **30/30 steps pass**, 0 not run |
| 2. Performance | `scripts/benchmark_phase10_4.py`, 15 samples per query workload on this VM | measured, no optimisation claimed |
| 7. PDF/research export | 34/34 memo figures extracted verbatim from the 11-page PDF; manifest hash equals the served bytes | pass |
| 9. Security | dependency scan (previous run: clean), host guard, rights/export gates | unchanged; no new finding |
| 12. Artifacts | rebuilt from the final commit | see release readiness |

### The flagship journey (Stage 1)

One process, one database, one script: demo → palette → company → statements → filings → question
→ certificate → independent verification → evidence follow → arithmetic recomputation →
valuation → assumptions → scenarios → comparison (refusal) → save → PDF → JSON → export
verification → reproduction on a second database → MCP.

Cross-surface agreement was checked rather than assumed: the HTTP certificate, the MCP tool result
and the PDF text all report **21,690** for the same fiscal-2023 gross profit, and the parsed filing
table independently recomputes 48,200 − 26,510 = 21,690. Reproducing on a freshly built database
yields the identical value and the identical `source_table_sha256`; document/table/cell ids are
database-local and differ, which the report states instead of pretending ids are content-addressed.

### Measured performance (this VM, Python 3.12, demonstration corpus)

| Workload | p50 | p95 | n |
|---|---|---|---|
| Command palette search | 6.5 ms | 8.3 ms | 15 |
| Financial statement retrieval | 182 ms | 212 ms | 15 |
| Company detail | 8.3 ms | 11.0 ms | 15 |
| Answer certificate | 9.8 ms | 23.7 ms | 5 |
| Company comparison | 7.8 ms | 13.6 ms | 5 |
| DCF valuation | 22.0 ms | 51.0 ms | 5 |
| PDF report (11 pages) | 19.1 ms | 32.8 ms | 5 |
| JSON export | 6.7 ms | 12.3 ms | 5 |
| MCP tool call | 5.5 ms | 14.4 ms | 10 |
| Application startup | 1.09 s | — | 1 |
| `atlas demo` (cold build) | 7.2 s | — | 1 |

The historical geometry figures (24.3 s cold / 45 ms warm / 111 ms per question / 706 MB) are a
different workload on a different machine and are not compared to these rows.

## Defects found and fixed in this phase

1. **The offline demo could not answer a single question.** Its Apple payload is XBRL facts; the
   answer engine reads parsed statement tables, and the demo shipped none. A new user could install
   Atlas, run the whole demonstration and never see a certificate. The demo now ingests a
   project-authored synthetic 10-K (every figure invented and labelled so on its face) and prints
   the answer, its source cell and the certificate fingerprint.
2. **An unrelated import blocked every report export.** The equity workspace listed every source in
   the database as its own provenance, so a `user_responsibility` CSV anywhere in the database made
   `rights.redistributable` false for every memo. Provenance now lists only the sources the company's
   evidence, bars, filings and documents actually come from.
3. **Project-authored documents could not declare their rights.** `ingest_document` hard-coded the
   copyright holder; it now accepts a holder and licence and fails closed when neither is given.

## Not attempted in this phase

Named so nobody reads the table above as covering them:

- **Research monitoring / Sentinel subscriptions** (Stage 3) — not implemented. The existing
  change-detection service reports which claims a changed source affects; there is no subscription
  store, scheduler, inbox or refresh loop. Nothing here claims otherwise.
- **Cross-period comparison** (Stage 4) — not implemented; the comparison workspace still compares
  one period across companies and refuses incompatible periods.
- **Firefox and WebKit** (Stage 5) — not run. Chromium journeys pass in hosted CI; the acceptance
  above drove HTTP, CLI, PDF and MCP, not a browser.
- **Independent MCP SDK client** (Stage 6) — not run. The protocol was exercised by our own client;
  the notification-without-reply bug that exercise exposed is fixed, but interoperability with an
  official SDK remains unproven.
- **Historical data remediation** (Stage 8) — unchanged: nine restricted files remain reachable in
  history and no rewrite was authorised.
- **Software licence** (Stage 8.5) — unchanged: no licence applied, decision is the maintainer's.
- **Landing page and launch materials** (Stage 11) — not produced in this phase.
- **External beta evaluation** (Stage 13) — not run; no participants.
- **Optimisation experiments** (Stage 2.2) — not attempted. Caches were not added; the numbers are
  a baseline.

## Known limitation recorded by this phase

The statements grid is evidence-backed (XBRL facts). A document ingested only into the knowledge
layer — as the demonstration's synthetic filing is — resolves answers and certificates and appears
in filing search, but its rows do not appear in the statements grid. That is a read-model gap, not a
correctness defect: the answer is bound to a verified cell of the parsed table and the arithmetic is
independently recomputed.
