# FOCUS Architecture

## Source-to-answer chain

```
SEC EDGAR HTML
   │  scripts/focus_build_corpus.py        (network, archives exact bytes)
   ▼
knowledge_document ── availability_time ── sha256 ── primary_document_url
   │  atlas/research/knowledge.py          (flatten HTML → units, tables, cells)
   ▼
verified cells (period, scale, currency, coordinates, raw)
   │  atlas/research/table_cells.py
   ▼
concept resolution ── statement family + entity scope ── conflict refusal
   │  atlas/research/financial_concepts.py  →  ResolvedFinancialInput
   ▼
Financial-Economic Compiler ──┬── atlas/research/financial_verification.py (Fraction)
                              │
                              ▼
                   atlas.research_certificate.v1
                              │  atlas/research/certificate.py
                              ▼
                     certificate_verify.py
                     ├── arithmetic pass (independent re-parse)
                     └── source pass (pinned manifest + archived bytes)
                              │
                              ▼
        SOURCE_VERIFIED / ARITHMETIC_VERIFIED / SOURCE_UNVERIFIED / INVALID
```

## Four levels, two passes

`certificate_verify.py` runs two passes that are deliberately not allowed to help each other.

The **arithmetic pass** reads only the certificate. It re-parses each binding's `raw` string and applies
the declared operator, producing an independent value. It also verifies the fingerprint and the internal
consistency of `value_exact` / `value` / `display_places` / `economic_amount`.

The **source pass** reads only external evidence: a pinned manifest (`atlas.focus_source_manifest.v1`)
mapping `(document digest, table digest, row, column)` to the raw text, label, period, scale, currency,
accession, form type and issuer CIK that were observed when the anchor was created, plus the original
document bytes. Every certificate binding must match a manifest entry, and every document digest must
match the bytes on disk.

A certificate that passes arithmetic but was never compared against external evidence is
`ARITHMETIC_VERIFIED`, never `SOURCE_VERIFIED`. That distinction is the point of the module.

## Why the manifest is a cell map, not a document list

Document and table ids are regenerated on every ingestion, so a manifest keyed by them would break on
every rebuild while proving nothing extra. Cells are keyed by `(table_sha256, row, column)`, which is
stable across re-ingestion of the same bytes and survives a re-sorted id space. Two consequences:

- A re-ingested corpus produces the same manifest, so the anchor is reproducible.
- Any change to the table content changes `table_sha256`, so a changed table cannot silently inherit
  old trust.

## Trust boundaries

| Boundary | Inside | Outside |
|----------|--------|---------|
| Arithmetic | certificate body | answer engine, FEC |
| Source | pinned manifest + archived bytes | certificate claims |
| Network | `https://www.sec.gov/Archives/edgar/data/` only | any URL a manifest contains |

Live fetching is restricted to the approved SEC archive prefix over HTTPS. The URL is validated, the
host must be exactly `www.sec.gov`, the path must remain under `/Archives/edgar/data/`, a declared
`User-Agent` is mandatory, and the response is capped (45 MB) before it is hashed. A missing, oversized,
redirected or non-HTTPS URL yields *no evidence* and a `SOURCE_UNVERIFIED` result — never an exception
in the middle of a verification and never a silent fallback to a different source.

## Repository layout

| Path | Role |
|------|------|
| `src/atlas/research/knowledge.py` | document ingestion, availability time, digests |
| `src/atlas/research/table_cells.py` | flattened-row table reader, scale/currency detection |
| `src/atlas/research/financial_concepts.py` | concept resolution and evidence bindings |
| `src/atlas/research/financial_answers.py` | typed answers, display precision, abstention |
| `src/atlas/research/financial_verification.py` | independent `Fraction` arithmetic |
| `src/atlas/research/certificate.py` | certificate construction and canonical fingerprint |
| `src/atlas/research/certificate_verify.py` | four-level verifier, manifest builder, byte authority |
| `src/atlas/research/focus_cases.py` | the 13 controlled real-filing cases |
| `scripts/focus_build_corpus.py` | network ingestion, snapshot archiving |
| `scripts/focus_manifest.py` | explicit trust-anchor generation |
| `scripts/focus_demo.py` | offline demonstration with a fail-closed exit contract |
| `tests/test_focus_certificate.py` | levels, 16-mutation matrix, CLI contract |
| `tests/test_certificate_source_limits.py` | fetch allowlist and bounds |

## Interfaces

One CLI, two spellings for compatibility:

```
atlas verify-certificate FILE [--manifest M] [--snapshots DIR] [--live-sec] [--strict]
atlas certificate verify FILE [--manifest M] [--snapshots DIR] [--live-sec] [--strict]
```

`--manifest` and `--snapshots` are what turn `ARITHMETIC_VERIFIED` into `SOURCE_VERIFIED`. `--live-sec`
allows fetching from the approved SEC endpoint when a snapshot is absent, and requires
`ATLAS_SEC_USER_AGENT`. `--strict` exits nonzero unless the level is `SOURCE_VERIFIED`.

Make targets:

| Target | Network | Purpose |
|--------|---------|---------|
| `make focus-corpus` | yes | fetch filings, archive bytes, write `artifacts/focus_corpus_manifest.json` |
| `make focus-manifest` | no | pin `artifacts/focus_source_manifest.json` over archived bytes |
| `make focus-demo` | no | 13 cases, certificate matrix, 16 mutations, refusals |
| `make focus-verify` | no | strict verification of every emitted certificate |

Exit codes for `focus-demo`: `0` all checks pass, `1` a check failed / a tamper was accepted / an
expected refusal is missing, `2` corpus, manifest or snapshots absent (with the command that creates
them).

## Artifacts

| File | Contents |
|------|----------|
| `artifacts/focus_corpus_manifest.json` | what was fetched, from where, when, with which digest |
| `artifacts/focus_source_manifest.json` | pinned cells: raw text, label, period, scale, currency |
| `artifacts/focus_demo/report.json` | 13-case results, certificate matrix, mutations, checks |
| `artifacts/focus_demo/certificate.json` | flagship certificate (3M FY2022 net sales) |
| `artifacts/focus_demo/certificates.json` | every answered certificate |

Archived bytes live in `var/focus/snapshots/<accession>.html`, which is untracked: the demo replays
locally archived source bytes, and a fresh checkout needs `make focus-corpus` once before it can verify
anything against a source snapshot.
