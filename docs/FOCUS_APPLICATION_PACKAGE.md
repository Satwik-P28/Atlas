# Jane Street FOCUS application package

This is the submit-ready description of what was built, what can be checked, and what is not
claimed. It assumes a reviewer with roughly three minutes and a terminal.

## The one-sentence version

Atlas computes financial answers only from printed cells of specific SEC filings, records each
answer as a certificate, and can prove the cell and the arithmetic against the original document
bytes — and it refuses, with a stated cause, when it cannot.

## What to look at, in order

1. **`docs/FOCUS_TECHNICAL_NOTE.md`** — the engineering problem, the trust model, what a fingerprint
   does and does not prove, the four verification levels, the adversarial results.
2. **`docs/FOCUS_RESEARCH_RESULTS.md`** — the thirteen cases, the three refusals with their
   classifications, the tamper table, the measured costs.
3. **`src/atlas/research/certificate_verify.py`** — the verifier. Read `verify()` top to bottom;
   each check is a line of reasoning.
4. **`tests/test_research_certificate.py`** — 44 tests, sixteen of them adversarial.

## Reproduce it

```bash
make install                     # creates .venv and installs the package

# 1. Build the corpus from live SEC EDGAR (network; SEC requires a contact User-Agent)
export ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com'
make focus-corpus

# 2. Run the demonstration (offline; authenticates against the archived bytes)
make focus-demo
```

Expected output: ten answers, three refusals with distinct causes, sixteen tampered certificates
refused. The machine-readable record is `artifacts/focus_demo.json`.

To verify the emitted certificate directly:

```bash
make focus-verify CERT=artifacts/focus_certificate.json
# level SOURCE_VERIFIED

.venv/bin/atlas certificate verify --certificate artifacts/focus_certificate.json
# level ARITHMETIC_VERIFIED  (no trusted evidence supplied)
```

Those two commands are the argument. The same file is `SOURCE_VERIFIED` when the original bytes are
available and `ARITHMETIC_VERIFIED` when they are not, and it never claims more than it checked.

## What is proven, precisely

| Claim | Basis |
| --- | --- |
| Coca-Cola FY2022 net operating revenues are printed as `43,004` in accession 0000021344-23-000011, column 2022 | Cell authenticated against the original document bytes |
| 3M FY2022 net sales are printed as `34,229` with scale 10^6, i.e. $34,229,000,000 | Same |
| The computed growth and margin values equal an independent rational-arithmetic recomputation | `certificate_verify.compute` vs `atlas.fec` execution |
| A certificate whose input and result were both changed, with every owned hash recomputed, is refused | 16/16 mutations refused under trusted evidence |
| A query with a 2017 cutoff cannot use a filing that became available in 2023 | Case 13, `historical_information_refusal` |
| The backend suite passes | 810 tests, 150.96 s |

## What is not claimed

- **Not a benchmark result.** Thirteen curated cases over four filings. No FinanceBench score is
  claimed; the licensed evaluation dataset is not in this repository.
- **Not general financial question answering.** Four 10-Ks, three issuers.
- **Not currency-verified.** Certified cells carry `currency=None`; scale is certified, currency is
  not. `34,229 × 10^6` is the economic amount; asserting USD specifically would be unsupported.
- **Not semantic verification.** The bytes prove the printed row. That the row is the concept the
  question meant is a pinned, reviewed judgement.
- **Not production or institutional use.** No user, deployment, or external adoption exists.
- **Not trading performance.** Nothing here is a strategy or a backtest result.

## The three resume bullets

See `docs/RESUME_EVIDENCE.md` for file-level mappings. In short:

1. Built a temporal evidence pipeline that ingests SEC 10-K filings as immutable, content-addressed
   documents and binds each financial value to a specific table, row, column and printed string.
2. Implemented a typed financial compiler path plus two independent rational-arithmetic
   implementations that must agree before an answer is shown.
3. Designed an adversarial verification harness in which sixteen self-consistent forgeries of a
   financial certificate are all refused, and documented the cases where verification cannot help.

## Honest status

`FOCUS_READY` for review. The demonstration runs end to end against real filings, the test suite is
green, and every claim above is checkable with the commands listed. The unresolved items are
research limitations (currency detection, concept mapping, XBRL corroboration), not broken
deliverables.

Repository history contains a commit (`d8ae4f1`) that once committed licensed FinanceBench material;
the current tree is clean of it. History has not been rewritten. See
`docs/FOCUS_SOURCE_RIGHTS.md`.
