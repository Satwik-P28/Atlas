# FOCUS research results

Every number in this document was produced by the committed code against filings fetched from SEC
EDGAR. Nothing here is estimated. Where a result is a refusal, it is reported as a refusal.

Artifacts: `artifacts/focus_demo.json`, `artifacts/focus_certificate.json`,
`artifacts/focus_source_manifest.json`, `artifacts/focus_corpus.json`,
`artifacts/phase9_6_4_case_studies.json`.

## 1. Corpus

| Issuer | Accession | Period | Bytes | Tables |
| --- | --- | --- | --- | --- |
| Coca-Cola | 0000021344-23-000011 | FY2022 | 5,390,657 | 122 |
| JPMorgan Chase | 0000019617-23-000231 | FY2022 | 15,883,009 | 634 |
| 3M | 0000066740-23-000014 | FY2022 | 6,551,758 | 113 |
| 3M | 0001558370-19-000470 | FY2018 | 10,020,722 | 277 |

Total 37,846,146 source bytes, 8,986 text units, 1,146 tables, 4 documents.
Built by `make focus-corpus` against live SEC EDGAR with a declared contact User-Agent and a 0.2 s
request throttle.

The FY2018 10-K was fetched deliberately. Refusing the 2018 question because the document was never
ingested would have been an artefact of the corpus, not a property of the question.

## 2. Case outcomes — 10 answered, 3 refused

| # | Issuer | Request | Outcome | Value | Scale | Certificate |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | Coca-Cola | revenue FY2022 | answered | 43,004.00 | 6 | `SOURCE_VERIFIED` |
| 02 | Coca-Cola | net income FY2022 | answered | 9,571.00 | 6 | `SOURCE_VERIFIED` |
| 03 | Coca-Cola | revenue growth 2021→2022 | answered | 11.25 % | — | `SOURCE_VERIFIED` |
| 04 | Coca-Cola | operating margin FY2022 | answered | 25.37 % | — | `SOURCE_VERIFIED` |
| 05 | Coca-Cola | total assets / revenue FY2022 | answered | 2.16 | — | `SOURCE_VERIFIED` |
| 06 | JPMorgan | total assets FY2022 | answered | 3,665,743.00 | 6 | `SOURCE_VERIFIED` |
| 07 | JPMorgan | net income FY2022 | answered | 37,676.00 | 6 | `SOURCE_VERIFIED` |
| 08 | JPMorgan | net income / assets FY2022 | answered | 0.01 | — | `SOURCE_VERIFIED` |
| 09 | JPMorgan | gross profit FY2022 | refused | — | — | — |
| 10 | 3M | net sales FY2022 | answered | 34,229.00 | 6 | `SOURCE_VERIFIED` |
| 11 | 3M | net sales growth 2021→2022 | answered | −3.18 % | — | `SOURCE_VERIFIED` |
| 12 | 3M | net sales FY2018 | refused | — | — | — |
| 13 | 3M | net sales FY2022 at 2017-01-01 cutoff | refused | — | — | — |

Economic magnitudes recovered:

- Coca-Cola FY2022 revenue: printed `43,004`, scale 6 → **43,004,000,000**.
- 3M FY2022 net sales: printed `34,229`, scale 6 → **34,229,000,000**.

Checked by hand against the filings: Coca-Cola's 2022 revenue growth is
(43,004 − 38,655) / 38,655 = 11.25%; operating margin is 10,909 / 43,004 = 25.37%; assets/revenue
is 92,843 / 43,004 = 2.16. 3M's net sales change is (34,229 − 35,355) / 35,355 = −3.18%.

## 3. The three refusals, classified by cause

A refusal is not a success. Each is classified from the corpus, not from the resolver's status
string (`focus_cases.diagnose`).

| Case | Classification | Evidence for the classification |
| --- | --- | --- |
| 09 JPM gross profit | `justified_unanswerability` | No verified statement row of JPMorgan's ingested statements uses the concept. A bank's consolidated statement of income reports no gross profit line. |
| 12 3M FY2018 | `capability_gap` | The FY2018 10-K prints a unique consolidated row `Net sales = 32,765` for 2018. The resolver returned `ambiguous` after matching segment rows labelled `Sales (millions)`. The question is answerable; Atlas failed to answer it. |
| 13 3M 2017 cutoff | `historical_information_refusal` | Accession 0000066740-23-000014 covers 2022-12-31, available 2023-02-08T18:14:49Z, after the 2017-01-01 cutoff. |

The resolver's reason string for case 12 was `concept_resolution:ambiguous`. An earlier version of the
runner reported that as `ambiguous_evidence`. That was wrong: it relabelled a resolver defect as a
property of the evidence. The diagnosis now inspects stored cells first, and the case is recorded as
a capability gap with the cell that proves it.

## 4. Certificate verification

Ten certificates are built from the same bindings the answers used — nothing is re-resolved for the
certificate.

- **Arithmetic only** (no trusted evidence): 10/10 `ARITHMETIC_VERIFIED`.
- **With trusted evidence** (pinned manifest + archived original bytes): 10/10 `SOURCE_VERIFIED`,
  route `snapshot`.

What `SOURCE_VERIFIED` asserts for each: the document's SHA-256 matches the pinned manifest, the
original bytes hash to that value, the source table is located inside those bytes by content hash,
the printed text at the recorded row and column equals the claimed raw text, every semantic field
matches the manifest, and the arithmetic recomputed from the snapshot's text equals the result.

What it does not assert: that the resolved concept is the economically intended one. That mapping is
pinned and reviewed; it is a judgement, and the verifier says so in its own limitations.

## 5. Adversarial results — 16/16 refused

Each mutation is applied to the Coca-Cola revenue certificate and every hash the certificate owns is
recomputed, so the artifact is internally self-consistent. All sixteen are `INVALID` under trusted
evidence.

| Mutation | Without evidence | With evidence |
| --- | --- | --- |
| result changed | `INVALID` | `INVALID` |
| raw input changed | `INVALID` | `INVALID` |
| **input and result changed together** | `ARITHMETIC_VERIFIED` | **`INVALID`** |
| source fingerprint changed | `ARITHMETIC_VERIFIED` | `INVALID` |
| issuer changed | `ARITHMETIC_VERIFIED` | `INVALID` |
| accession changed | `ARITHMETIC_VERIFIED` | `INVALID` |
| period changed | `ARITHMETIC_VERIFIED` | `INVALID` |
| currency changed | `ARITHMETIC_VERIFIED` | `INVALID` |
| scale changed | `ARITHMETIC_VERIFIED` | `INVALID` |
| availability changed | `ARITHMETIC_VERIFIED` | `INVALID` |
| coordinates changed | `ARITHMETIC_VERIFIED` | `INVALID` |
| concept changed | `ARITHMETIC_VERIFIED` | `INVALID` |
| table fingerprint changed | `ARITHMETIC_VERIFIED` | `INVALID` |
| operator changed | `INVALID` (structure) | `INVALID` |
| result scaled by 1000 | `ARITHMETIC_VERIFIED` | `INVALID` |
| row label changed | `ARITHMETIC_VERIFIED` | `INVALID` |

The table is the finding. Under arithmetic-only verification, twelve of sixteen forgeries pass. The
fingerprint is not an authority, and the test suite asserts this explicitly
(`test_arithmetic_verification_alone_cannot_detect_a_consistent_tamper`) so that the limitation
cannot quietly disappear from the documentation.

## 6. Measured costs

Machine: Linux container, Python 3.12.3, SQLite 3.45.1, NumPy 2.5.4, scikit-learn 1.9.1.

| Workload | Wall | Peak RSS |
| --- | --- | --- |
| `python scripts/focus_demo.py` (13 cases, 10 certificates, 2× verification each, 16 mutations) | 18.60 s | 89 MiB |
| Full backend suite, 810 tests | 150.96 s | — |

`focus-demo` re-reads all 1,146 tables of the four filings on every run (`FinancialAnswerEngine.cells`
is not memoised). This is a known cost of ~18 s and has not been optimised, because no measurement
yet shows it matters for a single-document demonstration.

## 7. Negative findings

- **The scale defect was real and large.** Before the fix, 3M's net sales carried scale 0, recording
  $34,229 instead of $34.229bn. The cause was reading only the caption for unit declarations; 3M
  prints `(Millions, except per share amounts)` as the table's first row. This would have been the
  first thing a reviewer checked.
- **The resolver's ambiguity label is not evidence.** Case 12 shows a resolver returning `ambiguous`
  on a question with a single unique answer.
- **Currency detection does not work on these statements.** All certified cells carry
  `currency=None`. Scale is certified; currency is not claimed.
- **Statement identity fails on 3M's FY2018 filing.** Every cell from that document carries
  `statement_family="unknown"`, which is the direct cause of the capability gap.
- **Arithmetic-only verification cannot detect a consistent forgery.** This is not a defect to fix;
  it is the reason the four levels exist.

## 8. Threats to validity

- Thirteen curated questions over four filings are not a benchmark. No FinanceBench result is
  claimed: the licensed evaluation dataset is not present in this repository, and no number here
  depends on it.
- The case set was written by the author of the system. Selection bias is real; the abstentions are
  the only partial control.
- Scale and period correctness are checked for the cases shown, not across the corpus.
- The archived snapshot proves the bytes that were ingested. It does not prove that SEC served those
  bytes on the claimed date; that would require a timestamped third-party archive.
