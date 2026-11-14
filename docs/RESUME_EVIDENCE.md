# Resume evidence

Every bullet below maps to code that exists, tests that run, and an artifact that was produced. If a
claim is not backed by a file path in this document, it should not go on a resume.

Commit references: the commit that introduced this material is recorded in
`docs/FINAL_RELEASE_REPORT.md`; `git log -- src/atlas/research/certificate_verify.py` gives the
exact history.

---

## Bullet 1 — financial data and historical evidence engineering

> Built an SEC filing evidence pipeline that ingests 10-K documents as immutable content-addressed
> records, resolves financial concepts to a specific table, row and column, and enforces
> point-in-time availability: a 2022 filing cannot answer a query dated 2017.

**Implemented**
- `scripts/focus_corpus.py` — fetch, ingest, archive exact bytes (declared User-Agent, 0.2 s throttle).
- `src/atlas/research/knowledge.py` — document/unit/table store; availability modelled as EDGAR
  acceptance plus a fixed lag, precision recorded as `unknown`.
- `src/atlas/research/table_cells.py` — cell geometry, scale, sign convention, period alignment.
- `src/atlas/research/financial_concepts.py` — concept → binding, refuses on ambiguity.
- `src/atlas/research/focus_cases.py` — the thirteen cases and evidence-based outcome diagnosis.

**Evidence**
- Four real 10-Ks, 37,846,146 bytes, 1,146 tables (`artifacts/focus_corpus.json`).
- Case 13 refuses a 2022 filing at a 2017 cutoff, classified `historical_information_refusal`
  with the accession and availability timestamp in the reason.
- Defect found and fixed: 3M declares its scale inside the table, not the caption; the extractor
  recorded $34,229 instead of $34,229,000,000 (commit modifies `table_cells.extract_cells`).

**Tests** — `tests/test_phase9_6_4_binding_and_geometry.py`, `tests/test_phase9_6_3_financial_resolution.py`,
`tests/test_research_certificate.py`.

**Limit** — currency is not detected for these statements; scale is certified, currency is not.

---

## Bullet 2 — compiler-backed computation and independent verification

> Implemented a typed computation path where every financial answer is compiled to a plan and
> executed by a typed financial compiler, then independently recomputed by two separate
> rational-arithmetic implementations that share no code with it; disagreement is a refusal, not a
> warning.

**Implemented**
- `src/atlas/fec` — typed plan compilation and execution (`Decimal`).
- `src/atlas/research/financial_verification.py` — `Fraction` recomputation over printed text.
- `src/atlas/research/certificate_verify.py` — third implementation, used by the verifier.
- `src/atlas/research/certificate.py` — the certificate record.
- `src/atlas/cli.py` — `atlas certificate verify`.

**Evidence**
- 10/10 answered cases: compiler result equals independent recomputation, `ARITHMETIC_VERIFIED`.
- The answer engine refuses on disagreement (`verification_disagreement`).
- `test_verifier_arithmetic_matches_a_second_independent_implementation` checks the third
  implementation against the second on hand-computed vectors.

**Tests** — `tests/test_research_certificate.py` (44 tests), `tests/test_phase9_6_2_financial_answers.py`.

**Limit** — independent implementations protect arithmetic, not extraction.

---

## Bullet 3 — adversarial testing and reproducible numerical research

> Designed an adversarial harness that mutates a financial certificate in sixteen ways while
> recomputing every hash the certificate owns; all sixteen are refused once independent evidence is
> supplied, and the twelve that pass arithmetic-only verification are documented as a limitation
> rather than hidden.

**Implemented**
- `tests/test_research_certificate.py` — parametrised attack matrix, structural tests, byte-tamper
  tests, manifest-only behaviour.
- `scripts/focus_demo.py` — runs the same attacks against a real filing and emits
  `artifacts/focus_demo.json` and `artifacts/focus_certificate.json`.
- `src/atlas/research/certificate_verify.py` — four explicit levels: `ARITHMETIC_VERIFIED`,
  `SOURCE_VERIFIED`, `SOURCE_UNVERIFIED`, `INVALID`.

**Evidence**
- 16/16 tampered certificates `INVALID` under trusted evidence; 0 accepted.
- The headline attack (input and result changed together, all hashes recomputed) passes
  arithmetic-only verification and is refused by the pinned manifest and by the original bytes.
- `make focus-verify CERT=artifacts/focus_certificate.json` → `SOURCE_VERIFIED`;
  the same file without evidence → `ARITHMETIC_VERIFIED`.

**Tests** — 810 backend tests pass in 150.96 s.

**Limit** — the case set is thirteen curated questions written by the author; it is not a benchmark.

---

## Variants

**Software engineering**
> Designed and shipped a versioned evidence-and-verification subsystem (~1,600 lines of new library
> code, 44 tests, CLI and Make targets) on top of an existing Python/SQLite codebase, including a
> backward-compatible fix to a stale CI assertion and a data-extraction defect found by inspecting a
> real filing.

**Systems engineering**
> Built a content-addressed evidence layer over SEC filings with explicit availability semantics,
> immutable documents, content-hash keyed pinning that survives rebuilds (identifiers are
> regenerated per ingestion), and a verifier whose trust boundary is documented in the code.

**Quantitative research**
> Implemented exact rational arithmetic for financial statement analysis with two independent
> implementations, half-up quantisation at the output boundary, zero-denominator and dash-is-not-zero
> refusal semantics, and a falsification-first outcome classification for abstentions.

**Research engineering**
> Wrote the technical note, the architecture contract, the limitations section, and the negative
> findings, including a defect that was mis-labelled as "ambiguous evidence" by the system itself
> before the classification was made evidence-based.

---

## Not to be claimed

- No professional trading, P&L, or strategy performance.
- No publication, peer review, or external citation.
- No institutional users, customers, or deployment.
- No FinanceBench score.
- No claim that "all thirteen cases succeed": three refuse, and one of those is a known defect.
