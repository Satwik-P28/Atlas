# FOCUS Source Rights

## Sources used

All corpus evidence is SEC EDGAR HTML for 10-K filings. These filings are prepared and filed by
their issuers, not by US federal employees, so 17 U.S.C. §105 does not apply and no public-domain
status is asserted. The SEC makes EDGAR filing content free to access and reuse under its published
web-access guidance; that is a reuse permission, not a statement of authorship. This repository
relies on the permission and redistributes no filing bodies.

| Filing | Accession | Endpoint family |
|--------|-----------|-----------------|
| Coca-Cola FY2022 10-K | `0000021344-23-000011` | `https://www.sec.gov/Archives/edgar/data/21344/` |
| JPMorgan FY2022 10-K | `0000019617-23-000231` | `https://www.sec.gov/Archives/edgar/data/19617/` |
| 3M FY2022 10-K | `0000066740-23-000014` | `https://www.sec.gov/Archives/edgar/data/66740/` |
| 3M FY2018 10-K | `0001558370-19-000470` | `https://www.sec.gov/Archives/edgar/data/66740/` |

## What is fetched, and how

- Ingestion is network-backed and explicit: `make focus-corpus` / `scripts/focus_build_corpus.py`.
- Every request carries a declared `User-Agent` from `ATLAS_SEC_USER_AGENT`; SEC requires this and the
  script refuses to run without it.
- Responses are size-bounded, and the exact bytes are archived under `var/focus/snapshots/` so that all
  later verification is offline and reproducible.
- Live verification fetching (`--live-sec`) is restricted to the approved HTTPS SEC archive prefix
  `https://www.sec.gov/Archives/edgar/data/`, with an exact-host check, a path-prefix check, a declared
  `User-Agent`, and a size cap. Any other URL yields no evidence rather than being followed.

## What is not redistributed

- Filing bytes are **not committed**. `var/*.db` and `var/focus/snapshots/` are untracked, so a clone
  contains no SEC document bodies, only the code that fetches them and the digests that identify them.
- `artifacts/focus_corpus_manifest.json` and `artifacts/focus_source_manifest.json` contain accessions,
  URLs, availability times, digests and short quoted cell values (e.g. `34,229`). These are factual
  identifiers and small figures from filings retrieved from SEC EDGAR.
- The synthetic market fixture is project-authored and labelled synthetic in its own metadata; it is never
  described as observed market data.

## Licensed material

FinanceBench question text and reference rows are licensed and are never committed. The evaluator
(`scripts/phase9_6_4_evaluate.py`) requires reference rows out-of-band and exits `2` with
`unavailable_reference_data` when they are absent, rather than inventing scores.

`main` still contains historical ancestry that includes previously committed FinanceBench material
(`d8ae4f1`). A normal merge does not remove it, and no history rewrite or force-push is authorized from
this workstream. This is a release blocker that requires an owner decision on history policy.

## Operating position

The FOCUS demo is research software. It does not redistribute licensed data, does not claim institutional
performance, and its certificates state what they do and do not prove
(see `docs/FOCUS_TECHNICAL_NOTE.md`).
