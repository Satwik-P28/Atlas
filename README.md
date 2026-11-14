# Atlas

Atlas is a point-in-time financial research system that connects historical SEC source evidence to typed, independently verified financial computations.

It is built to answer a hard question honestly:

**How do we know that a financial answer is correct when its sources can be revised, misidentified, historically unavailable, or contradictory?**

This repository is an engineering research project. It does not claim institutional trading performance, terminal parity, or profitability.

## The technical problem

Public filings are revised, restated, segmented, and scaled. A printed number without statement identity, period, currency, scale, and availability time is not a research answer. Atlas treats those fields as part of the computation, refuses when they cannot be established, and packages accepted answers as independently verifiable research certificates.

## Working result (FOCUS demo)

Network ingestion and offline verification are separate steps. The first fetches SEC HTML and archives the
exact bytes it received; the second pins a manifest over those bytes; the third replays everything offline.

```bash
python3 -m pip install -e ".[dev]"
export ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com'
make focus-corpus     # network: fetch 4 filings, archive bytes under var/focus/snapshots/
make focus-manifest   # explicit trust anchor: artifacts/focus_source_manifest.json
make focus-demo       # offline: 13 cases, certificates, 16 mutations, refusals
```

`make focus-demo` exits `0` only when every required check passes, `1` when a check fails, a tamper is
accepted, or an expected refusal is missing, and `2` when the corpus, manifest, or snapshots are absent
(it prints the command that would create them; it never manufactures a trust anchor itself).

Measured on the real 3M FY2022 10-K (accession `0000066740-23-000014`):

| Step | Result |
|------|--------|
| Consolidated net sales FY2022 | printed `34,229`, scale `6` (millions), economic amount `34,229,000,000` USD |
| FEC + independent Fraction verification | agree |
| `atlas.research_certificate.v1` | issued and fingerprint-stable |
| `atlas verify-certificate --manifest --snapshots --strict` | `SOURCE_VERIFIED`, 34/34 checks pass |
| 16 self-consistent retampered certificates | all `INVALID` |
| Cutoff before availability (2017) | refused |

Thirteen controlled real-filing cases across Coca-Cola, JPMorgan, and 3M were re-run on the same corpus
builder: **10 answered, 3 correctly refused**, each for a different reason.

| Refusal | Case | Classification |
|---------|------|----------------|
| JPMorgan gross profit not in the available statement | FOCUS-09 | justified unanswerability |
| 3M FY2018 consolidated net sales | FOCUS-12 | resolver capability gap (the filing prints `32,765`; Atlas does not resolve it) |
| Evidence not yet public at the cutoff | FOCUS-13 | historical information refusal |

The FY2018 refusal is a known gap, not a success: the figure exists in the filing and Atlas fails to bind it.
A refusal that happens to be correct is not counted as an answered question.

## Architecture

1. **Ingest** SEC HTML 10-Ks into a local SQLite knowledge store with availability timestamps.
2. **Extract** verified table cells (period, currency, scale, coordinates) or leave them unresolved.
3. **Resolve** a financial concept to one cell with statement family and entity scope; refuse conflicts.
4. **Bind** the selected evidence identity (`ResolvedFinancialInput`) so later steps cannot silently re-search by row label.
5. **Compile** through the Financial-Economic Compiler (FEC) and recompute with an independent Fraction verifier.
6. **Certify** the answer as `atlas.research_certificate.v1` and verify it with `atlas verify-certificate` (no production answer pipeline).

## Verification levels

A certificate is checked in two independent passes: recomputing the arithmetic from the bound raw
strings, and comparing the bound evidence against a pinned manifest and the archived source bytes.
The result is one of four levels.

| Level | Meaning |
|-------|---------|
| `SOURCE_VERIFIED` | Arithmetic agrees and the certificate's document digest, table digest, coordinates, label, raw text, period, scale and currency all match the pinned manifest and archived bytes |
| `ARITHMETIC_VERIFIED` | Arithmetic agrees, but no trusted evidence was supplied, so the inputs themselves are unproven |
| `SOURCE_UNVERIFIED` | Evidence was offered but is unusable (manifest without bytes, or hashes copied from the certificate itself) |
| `INVALID` | Fingerprint, structure, arithmetic, or source comparison failed |

`SOURCE_VERIFIED` means *consistent with that pinned snapshot*. It does not prove when the document
was published, that the printed number is the financially correct concept, or that the manifest itself
is authentic — it is an unsigned file produced by `make focus-manifest`.

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
| `make focus-corpus` | Network: fetch the FOCUS filings into `var/focus_demo.db` and archive exact bytes |
| `make focus-manifest` | Pin `artifacts/focus_source_manifest.json` over the archived bytes |
| `make focus-demo` | Offline: source → certificate → verify → 16 tampers → cutoff refusal |
| `make focus-verify` | Strictly verify the demo certificates against the pinned manifest |
| `python3 scripts/phase9_6_4_case_studies.py` | Re-run the 13 real-filing cases (expects `var/phase9_6.db`) |
| `python3 -m atlas verify-certificate artifacts/focus_demo/certificate.json --manifest artifacts/focus_source_manifest.json --snapshots var/focus/snapshots --strict` | Independent strict certificate check |
| `python3 -m pytest -q` | Offline unit/property suite (812 tests) |

FinanceBench evaluation (`scripts/phase9_6_4_evaluate.py`) requires licensed reference rows out-of-band. Without them the evaluator exits `2` and writes `unavailable_reference_data` — it does not invent scores.

## Tests and benchmarks

- Binding / geometry fault injection: `tests/test_phase9_6_4_binding_and_geometry.py`
- Evaluator integrity (exit codes, confusion-matrix rates, zero-denominator nulls): `tests/test_phase9_6_4_evaluator_integrity.py`
- Research certificates, verification levels and the 16-mutation matrix: `tests/test_focus_certificate.py`
- Live-fetch endpoint allowlist and size bounds: `tests/test_certificate_source_limits.py`
- Independent arithmetic reference vectors: `src/atlas/research/financial_verification.py`

Historical phase benchmarks and browser acceptance reports live under `docs/PHASE9_*.md` and `artifacts/`. They are retained as history; they are not re-claimed by this README.

## Limitations

- No XBRL fact corroboration in the current corpus.
- Table geometry is inferred from flattened HTML rows; colspan/rowspan truth is incomplete.
- Vintage policy covers original-as-filed selection and conflict refusal; latest-at-cutoff and restatement comparison are incomplete.
- `main` still contains historical ancestry that includes previously committed FinanceBench material (`d8ae4f1`). Clean FOCUS work is on a candidate branch; history rewrite / force-push to `main` is not authorized from this workstream.
- `SOURCE_VERIFIED` proves consistency with a pinned snapshot, not publication time or financial semantics; the manifest is unsigned and generated by an explicit command.
- Currency is detected from symbols in the statement (`$` → USD), not from an ISO code; a filing that prints a bare `$` for a non-USD dollar would be misread.
- Spec `ATLAS_MASTER_SPEC.md` v3.1.0 (sha256 `d1800cfea35d973e2ff2b3570f8bf564fd3a7aceabca2f623ec5de17931a1111`) describes a much larger desired system. Most of that surface is proposed or prototype, not FOCUS-verified.

## Documentation

| Document | Contents |
|----------|----------|
| `docs/FOCUS_TECHNICAL_NOTE.md` | Problem, method, certificate design, measured example |
| `docs/FOCUS_RESEARCH_RESULTS.md` | Case-study results and threats to validity |
| `docs/FOCUS_ARCHITECTURE.md` | Source-to-answer chain |
| `docs/FOCUS_APPLICATION_PACKAGE.md` | Application-facing summaries |
| `docs/RESUME_EVIDENCE.md` | Resume bullets with file/test evidence |
| `docs/ENGINEERING_DEFENSE.md` | Interview defense against the implementation |
| `docs/FOCUS_FILING_CASE_OUTCOMES.md` | Per-case outcomes and refusal reasons |
| `docs/FOCUS_SOURCE_RIGHTS.md` | Source URLs, licensing and redistribution position |
| `docs/FINAL_RELEASE_REPORT.md` | Integrated candidate, checks run, remaining blockers |
| `ATLAS_MASTER_SPEC.md` | Canonical desired-state specification v3.1.0 (sha256 `d1800cfe…a1111`) |
| `docs/archive/README_PRE_FOCUS.md` | Pre-FOCUS historical README |

## License and data rights

Atlas code is developed in this repository. SEC EDGAR filings used by the FOCUS demo are fetched at build time into untracked `var/*.db` files and are not redistributed in git. Licensed FinanceBench question text is never committed.
