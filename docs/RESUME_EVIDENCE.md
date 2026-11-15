# Resume Evidence

Bullets with the file, test or artifact that supports each one. No number here is estimated; each is
reproduced by a command in this repository.

## Project entry

**Atlas — point-in-time financial research with verifiable certificates** (independent research project,
Python + TypeScript)

- Designed a point-in-time financial research pipeline that ingests historical SEC 10-K filings, extracts
  table cells with period, scale, source coordinates and optional currency, refusing unsupported
  required inputs. Evidence: `src/atlas/research/table_cells.py`, `financial_concepts.py`; three distinct
  refusal classes reproduced by `make focus-demo`.
- Built a research-certificate format (`atlas.research_certificate.v1`) that binds each answer to its
  source coordinates, raw strings, document digest and availability time, with a canonical fingerprint
  over the body. Evidence: `src/atlas/research/certificate.py`.
- Implemented a four-level verifier with two independent passes — recomputed arithmetic from the
  certificate's own raw text, and source comparison against a pinned manifest plus archived bytes —
  producing `SOURCE_VERIFIED` / `ARITHMETIC_VERIFIED` / `SOURCE_UNVERIFIED` / `INVALID`.
  Evidence: `src/atlas/research/certificate_verify.py`.
- Repaired a scale defect that reported `34,229` instead of `34,229,000,000` by reading the unit banner
  from the header row and treating undetectable scale as unknown rather than zero. Evidence:
  `tests/test_phase9_6_4_binding_and_geometry.py`, `artifacts/focus_demo/report.json`.
- Eliminated a circular trust model in which the "trusted" source hash was copied from the certificate
  under test; verification now refuses that shape and requires external evidence. Evidence:
  `SOURCE_UNVERIFIED` with reason `legacy_trusted_sources_insufficient`.
- Built a 16-case adversarial suite in which every forged certificate is re-signed with a recomputed
  fingerprint; 16/16 are refused, including the case where the printed input and the computed result are
  changed together. Evidence: `tests/test_focus_certificate.py`.
- Restricted live source fetching to approved HTTPS SEC endpoints with an exact-host check, path-prefix
  check, declared `User-Agent` and size cap; failures degrade to missing evidence rather than exceptions.
  Evidence: `tests/test_certificate_source_limits.py`.
- Made the demonstration fail closed: exit `0` only when every check passes, `1` on a failed check, an
  accepted tamper, or a missing expected refusal, `2` when the corpus, manifest or snapshots are absent —
  and never regenerated a missing trust anchor during verification. Evidence: `scripts/focus_demo.py`.
- Ran thirteen controlled real-filing cases across Coca-Cola, JPMorgan and 3M: ten answered, three
  refused, with the 3M FY2018 case reported as a resolver capability gap rather than a success.
- Maintained a 812-test backend suite and a 50-test frontend suite with typecheck and production build
  green, plus offline reproduction of research packages from archived fixtures.

## Interview talking points

- Why the interesting tamper is the one that re-signs itself, and why arithmetic-only verification cannot
  catch it.
- Why a manifest keyed by `(table_sha256, row, column)` survives re-ingestion while ids do not.
- Why "unknown scale" must be `None` and not `0`.
- Why count of refusals is not count of failures, and why a capability gap has to be labelled separately
  from a policy refusal.
- What `SOURCE_VERIFIED` explicitly does not prove.

## Do not claim

- Trading performance, alpha, or profitability.
- Accuracy across a corpus: four filings, three issuers, ten answers.
- That certificates prove publication time or financial semantics.
- That the manifest is authenticated: it is unsigned.
- That the 3M FY2018 question was answered.
