# FOCUS architecture: from a filing to a verified claim

This document describes only what is implemented. Anything not in this diagram does not exist.

```
SEC EDGAR 10-K bytes
      │  scripts/focus_corpus.py  (network; declared User-Agent; 0.2s throttle)
      ▼
KnowledgeEngine.ingest_document        src/atlas/research/knowledge.py
      │  → knowledge_document   (sha256 over the exact bytes, availability time)
      │  → knowledge_unit       (text blocks, sha256 per block)
      │  → knowledge_table      (rows_json, table sha256 = sha256 of the block)
      ▼
ConceptResolver.resolve(issuer, concept, period, cutoff)   financial_concepts.py
      │  refuses on not_found / ambiguous; never guesses
      ▼
bind(resolution) → Binding {accession, table, unit, row, column, raw, value, scale, period, …}
      │
      ▼
FinancialAnswerEngine.validate_binding(binding, cutoff)    financial_answers.py
      │  re-reads the store: issuer, accession, availability ≤ cutoff,
      │  table hash, unit identity, cell text at (row, column), period printed in the table
      ▼
FEC compile + execute               src/atlas/fec
      │  typed plan: inputs Money[USD]/Scalar, nodes sub/div/mul
      ▼
independent recomputation           financial_verification.py
      │  Fraction arithmetic over the printed text; refuses on disagreement
      ▼
answer packet {outcome, operator, value, unit, inputs[], fec{…}, verification{…}}
      │
      ▼
build_certificate(db, packet, bindings)                    certificate.py
      │  adds document / table / unit hashes, issuer identity, availability
      │  fingerprint = sha256(canonical payload)
      ▼
certificate JSON  ──►  verify(certificate, evidence)       certificate_verify.py
                          ├─ ARITHMETIC_VERIFIED   (own Fraction implementation)
                          ├─ SOURCE_VERIFIED       (+ manifest + original bytes + cell text)
                          ├─ SOURCE_UNVERIFIED     (no authoritative evidence)
                          └─ INVALID               (reasons)
```

## Module map

| Module | Responsibility | Deliberately does not |
| --- | --- | --- |
| `scripts/focus_corpus.py` | Fetch, ingest, archive exact bytes | Verify anything |
| `research/knowledge.py` | Immutable documents, availability times, table extraction | Resolve concepts |
| `research/table_cells.py` | Cell geometry, scale, sign, period | Compute financial ratios |
| `research/financial_concepts.py` | Concept → row/column binding, refusal | Compute values |
| `research/financial_answers.py` | Plan construction, binding revalidation, refusal | Implement FEC arithmetic |
| `fec/*` | Typed compilation and execution | Know about SEC filings |
| `research/financial_verification.py` | Independent arithmetic over printed text | Parse filings |
| `research/certificate.py` | Record a result and its evidence | Decide whether it is true |
| `research/certificate_verify.py` | Decide, given independent evidence | Trust the certificate |
| `research/focus_cases.py` | The thirteen cases, outcome diagnosis | Produce artifacts |

The separation is the design. `certificate.py` can only *state*; `certificate_verify.py` can only
*judge*; neither can reach into the other's evidence. `focus_cases.py` reads the store to diagnose a
refusal, which is why it can contradict the resolver's own reason string.

## Certificate contract (`atlas.research.certificate.v1`)

Top level: `schema`, `certificate_version`, `emitted_at`, `subject`, `evidence[]`, `computation`,
`result`, `independent`, `engine`, `limitations`, `fingerprint`.

`subject` — `issuer_id`, `issuer_name`, `cik`, `accession`, `form_type`, `document_id`,
`document_sha256`, `primary_document_url`, `cutoff`.

`evidence[i]` — `concept`, `issuer_id`, `document_id`, `accession`, `document_sha256`, `table_id`,
`table_sha256`, `unit_id`, `unit_sha256`, `row`, `column`, `row_label`, `column_label`, `raw`,
`value`, `scale`, `currency`, `period`, `statement_family`, `statement_title`, `entity_scope`,
`availability_time`, `availability_precision`, `rights`.

`computation` — `operator` (one of `lookup`, `percentage_change`, `ratio`, `margin`, `total`),
`formula`, `answer_type`, `metric`, `period`, `compiler_version`, `operator_versions`,
`fec_fingerprint`, `run_id`, `plan`.

`structural_problems()` returns every missing or inconsistent field. A certificate with one evidence
item cannot claim `ratio`; the evidence count is checked against the operator before arithmetic.

## Trusted evidence

`TrustedEvidence(manifest, snapshots, live_sec)`.

- `manifest` — `atlas.focus.source_manifest.v1`, produced by `build_source_manifest(db, bindings)`
  from the store and the resolver bindings, never from a certificate. Cells are keyed by
  `(table_sha256, row, column)` because document and table ids are regenerated on every ingestion,
  so id-keyed pinning would break on rebuild.
- `snapshots` — `{accession: bytes}`, the archived original documents written by
  `focus_corpus.py` into `var/focus/snapshots/<accession>.html`.
- `live_sec` — fetch the manifest's `primary_document_url` from www.sec.gov instead. This is the only
  route that depends on neither this repository nor its archive.

A manifest alone yields `SOURCE_UNVERIFIED` with reason `no_source_bytes`. A manifest cannot prove
which bytes SEC served.

## Determinism

- Arithmetic is rational (`Fraction`), with half-up quantisation to two decimals at the boundary.
- Document, table and unit hashes are content hashes and reproduce across rebuilds.
- `document_id` / `table_id` / `unit_id` are generated per ingestion and do **not** reproduce; this
  is why every pinned reference and every certificate comparison uses content hashes.
- The corpus itself is refetched from SEC. The archived snapshots are the stable artifact; they are
  under `var/` and are not committed.

## Commands

```
make install                 # .venv + editable install
make focus-corpus            # network; ATLAS_SEC_USER_AGENT required
make focus-demo              # offline given the corpus; writes artifacts/focus_demo.json
make focus-manifest          # regenerate artifacts/focus_source_manifest.json
make focus-verify CERT=...   # atlas certificate verify against manifest + snapshots
make test                    # 810 backend tests
```
