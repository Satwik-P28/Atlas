# Atlas

Atlas is a point-in-time financial research system that connects historical SEC source evidence to typed, independently verified financial computations.

It is built to answer a hard question honestly:

**How do we know that a financial answer is correct when its sources can be revised, misidentified, historically unavailable, or contradictory?**

This repository is an engineering research project. It does not claim institutional trading performance, terminal parity, or profitability.

## The technical problem

Public filings are revised, restated, segmented, and scaled. A printed number without statement identity, period, currency, scale, and availability time is not a research answer. Atlas treats those fields as part of the computation, refuses when they cannot be established, and packages accepted answers as independently verifiable research certificates.

## Working result (FOCUS demo)

From a clean checkout, with network access to SEC EDGAR and `ATLAS_SEC_USER_AGENT` set:

```bash
python3 -m pip install -e ".[dev]"
export ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com'
make focus-demo
```

Measured on the Priority 0 checkpoint (real 3M FY2022 10-K, accession `0000066740-23-000014`):

| Step | Result |
|------|--------|
| Consolidated net sales FY2022 | printed `34,229`, scale `6` (USD millions), economic amount `34229000000` |
| FEC + independent Fraction verification | agree |
| `atlas.research_certificate.v1` | issued and fingerprint-stable |
| `atlas verify-certificate` | accepts the unmodified certificate |
| Value tamper | rejected |
| Cutoff before availability (2017) | refused |

Thirteen controlled real-filing cases across Coca-Cola, JPMorgan, and 3M were re-run on the same corpus builder: **10 answered, 3 correctly abstained** (JPMorgan gross profit unsupported; 3M FY2018 ambiguous; pre-availability cutoff).

## Architecture

1. **Ingest** SEC HTML 10-Ks into a local SQLite knowledge store with availability timestamps.
2. **Extract** verified table cells (period, currency, scale, coordinates) or leave them unresolved.
3. **Resolve** a financial concept to one cell with statement family and entity scope; refuse conflicts.
4. **Bind** the selected evidence identity (`ResolvedFinancialInput`) so later steps cannot silently re-search by row label.
5. **Compile** through the Financial-Economic Compiler (FEC) and recompute with an independent Fraction verifier.
6. **Certify** the answer as `atlas.research_certificate.v1` and verify it with `atlas verify-certificate` (no production answer pipeline).

See `docs/FOCUS_ARCHITECTURE.md`.

## Key engineering decisions

- **Refuse over guess.** Ambiguous labels, unknown scale, unit mismatch, and future evidence abstain.
- **Bindings carry identity.** Validated cell selection is revalidated against stored bytes before arithmetic.
- **Two implementations for arithmetic.** FEC execution and `financial_verification` Fraction math must agree.
- **Typed display precision.** Exact values are preserved; display places depend on answer type (currency 2 dp, ratios 4 dp, …).
- **Certificates are canonical JSON.** Semantically meaningful edits change the fingerprint; resigned false results still fail arithmetic checks.

## Reproduction

| Command | Purpose |
|---------|---------|
| `make focus-demo` | End-to-end source → certificate → verify → tamper → cutoff refusal |
| `python3 scripts/focus_build_corpus.py` | Fetch the FOCUS SEC filings into `var/focus_demo.db` |
| `python3 scripts/phase9_6_4_case_studies.py` | Re-run the 13 real-filing cases (expects `var/phase9_6.db`) |
| `python3 -m atlas verify-certificate artifacts/focus_demo/certificate.json` | Independent certificate check |
| `python3 -m pytest -q` | Offline unit/property suite |

FinanceBench evaluation (`scripts/phase9_6_4_evaluate.py`) requires licensed reference rows out-of-band. Without them the evaluator exits `2` and writes `unavailable_reference_data` — it does not invent scores.

## Tests and benchmarks

- Binding / geometry fault injection: `tests/test_phase9_6_4_binding_and_geometry.py`
- Evaluator integrity (exit codes, confusion-matrix rates, zero-denominator nulls): `tests/test_phase9_6_4_evaluator_integrity.py`
- Research certificates and adversarial mutations: `tests/test_focus_certificate.py`
- Independent arithmetic reference vectors: `src/atlas/research/financial_verification.py`

Historical phase benchmarks and browser acceptance reports live under `docs/PHASE9_*.md` and `artifacts/`. They are retained as history; they are not re-claimed by this README.

## Limitations

- No XBRL fact corroboration in the current corpus.
- Table geometry is inferred from flattened HTML rows; colspan/rowspan truth is incomplete.
- Vintage policy covers original-as-filed selection and conflict refusal; latest-at-cutoff and restatement comparison are incomplete.
- `main` still contains historical ancestry that includes previously committed FinanceBench material (`d8ae4f1`). Clean FOCUS work is on a candidate branch; history rewrite / force-push to `main` is not authorized from this workstream.
- Spec `ATLAS_MASTER_SPEC.md` v3.1.0 describes a much larger desired system. Most of that surface is proposed or prototype, not FOCUS-verified.

## Documentation

| Document | Contents |
|----------|----------|
| `docs/FOCUS_TECHNICAL_NOTE.md` | Problem, method, certificate design, measured example |
| `docs/FOCUS_RESEARCH_RESULTS.md` | Case-study results and threats to validity |
| `docs/FOCUS_ARCHITECTURE.md` | Source-to-answer chain |
| `docs/FOCUS_APPLICATION_PACKAGE.md` | Application-facing summaries |
| `docs/RESUME_EVIDENCE.md` | Resume bullets with file/test evidence |
| `docs/ENGINEERING_DEFENSE.md` | Interview defense against the implementation |
| `ATLAS_MASTER_SPEC.md` | Canonical desired-state specification v3.1.0 |
| `docs/archive/README_PRE_FOCUS.md` | Pre-FOCUS historical README |

## License and data rights

Atlas code is developed in this repository. SEC EDGAR filings used by the FOCUS demo are fetched at build time into untracked `var/*.db` files and are not redistributed in git. Licensed FinanceBench question text is never committed.
