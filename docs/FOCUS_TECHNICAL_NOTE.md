# Proving that a financial number came from the right historical evidence

**Atlas research note — October 2026**
Implementation: `src/atlas/research/certificate.py`, `certificate_verify.py`, `focus_cases.py`.
Reproduction: `make focus-corpus && make focus-demo`.

---

## 1. The problem

A financial question such as "what was Coca-Cola's 2022 revenue" looks like a retrieval problem and
is not one. Four independent things must be true before the number "43,004" is an answer:

1. it is printed in a document that existed at the time the question is asked about;
2. it is the right line in the right statement — consolidated net operating revenues, not a
   segment, not a footnote, not the 2021 column;
3. the unit is understood — 43,004 million dollars, not 43,004 dollars;
4. the arithmetic that turned the printed cell into the answer is correct.

A retrieval system can satisfy none of these. It returns text that is lexically near the question.
A large language model can produce a fluent sentence containing a plausible number with no
mechanism that distinguishes a quoted figure from an invented one.

The failure mode that matters is not "the system found nothing". It is "the system answered
confidently and was wrong by a factor of a million", or "the system used the 2023 10-K to answer a
question dated 2022". Both are invisible in the output.

Atlas was built around the claim that these errors can be caught *before* the answer is presented,
by making the evidence a first-class typed object and by refusing to compute on anything that has
not been bound to a specific printed cell.

## 2. Why a second arithmetic implementation is worth writing

The Financial-Economic Compiler (`src/atlas/fec`) executes a typed plan: `sub`, `div`, `mul` over
`Decimal` inputs. It is the production path.

`src/atlas/research/financial_verification.py` recomputes the same economic relationships from the
*printed text* using `fractions.Fraction`. It shares no code with the compiler. The answer engine
refuses when the two disagree (`financial_answers.py`, reason `verification_disagreement`).

`src/atlas/research/certificate_verify.py` is a third implementation, also rational arithmetic, also
sharing no code with either. It exists so that a certificate can be checked by something that does
not trust the process that produced it.

Agreement between independent implementations that operate on the same input is evidence about the
arithmetic. Agreement of an implementation with itself is not. That distinction is the reason the
third implementation exists rather than a call into the second.

It is worth being precise about what this buys: two implementations can both be wrong in the same
way if they misread the *input*. They are unlikely to be wrong in the same way if the input is
already a parsed rational number and the disagreement would be about the operator semantics. The
independent check therefore protects the arithmetic, not the extraction. Extraction is protected by
a different mechanism (section 4).

## 3. Why the financial types matter

Every quantity carries: issuer, statement family, entity scope (consolidated / segment / parent),
concept, period, scale, currency (when detected), sign convention, source document, source table
hash, and row/column coordinates.

The type discipline is enforced at bind time, not at display time. `FinancialAnswerEngine._require`
refuses to combine two cells with different `(scale, currency)`. The concept resolver refuses when
two candidate rows disagree. `table_cells.py` refuses to treat a dash as zero, because filings use a
dash for nil, for not-applicable and for not-disclosed, and the caption rarely says which.

These refusals are the product. A system that answers 10 of 13 curated questions and abstains on the
other three, with a stated cause for each abstention, is more useful than one that answers 13 and is
occasionally off by 10^6.

## 4. What a fingerprint proves, and what it does not

A certificate is a JSON document recording the subject filing, the exact printed cells used, the
typed plan, the result, and the hashes of the document, table and text unit.

`payload_fingerprint()` computes SHA-256 over the canonicalised payload. This proves **internal
consistency**: the body has not been altered since the fingerprint was computed.

It proves nothing about authority. An attacker who changes an input cell and the claimed result
together, then recomputes every hash the certificate owns, produces an artifact that is
self-consistent and wrong. No field inside the certificate can detect this, because the certificate
is the thing being checked.

This is not a hypothetical. It is case `changed_input_and_result` in
`tests/test_research_certificate.py`, and the demonstration runs it on a real filing: the tampered
artifact verifies as `ARITHMETIC_VERIFIED` and is refused as soon as independent evidence is
supplied.

## 5. How the verifier works

`verify(certificate, evidence=None)` returns exactly one of four levels.

| Level | Meaning |
| --- | --- |
| `ARITHMETIC_VERIFIED` | Payload is well-formed, its fingerprint matches its body, and the verifier's own rational arithmetic over the inputs *the certificate carries* reproduces the claimed result. |
| `SOURCE_VERIFIED` | All of the above, plus: the accession is pinned in a trusted manifest; the manifest's document hash equals the certificate's; the original document bytes hash to that value; the source table is located inside those bytes by content hash; the printed text at the recorded row and column equals the claimed raw text; every semantic field matches the pinned manifest; and the arithmetic recomputed from the *snapshot's* text equals the result. |
| `SOURCE_UNVERIFIED` | Arithmetic holds, but authoritative source evidence was unavailable, or only a manifest was supplied. Never reported as an error and never reported as source-verified. |
| `INVALID` | A required check failed; `reasons` names the first four failures. |

The ordering matters. The manifest is checked before any bytes are consulted, so a forged cell is
rejected even offline. The bytes are checked before the printed text is trusted, so a document
substitution is caught before extraction. The arithmetic is recomputed twice: once from the
certificate's claims, once from the authenticated text.

The verifier locates the source table by hashing the text block it was extracted from, not by its
position. A document whose pagination changed cannot silently match a different table.

## 6. What the adversarial tests found

Sixteen mutations are applied to a real certificate for Coca-Cola 2022 revenue. Each keeps the
artifact internally consistent: every hash the certificate owns is recomputed after the edit.

All sixteen are refused at `SOURCE_VERIFIED` as `INVALID`. The mutations are: result changed; raw
input changed; **input and result changed together**; source fingerprint changed; issuer changed;
accession changed; reporting period changed; currency changed; scale changed; availability changed;
coordinates changed; financial concept changed; table fingerprint changed; operator changed; result
scaled by 1000; row label changed.

Three results deserve emphasis, because they are the ones that would have been easy to get wrong:

- `changed_input_and_result` is `ARITHMETIC_VERIFIED` without evidence and `INVALID` with it. This
  is the demonstration that the fingerprint is not an authority.
- `changed_value_scale_consistently` multiplies the result by 1000 without touching the printed
  text. Arithmetic over the certificate's own inputs is unaffected (the raw text is unchanged), so
  only the pinned evidence catches it.
- `changed_operator` is caught structurally: a `lookup` certificate has one evidence item, and
  declaring it a `ratio` is inconsistent with the evidence count before any arithmetic runs.

The tests also quantify the limitation. `test_arithmetic_verification_alone_cannot_detect_a_consistent_tamper`
asserts explicitly that twelve of the sixteen forgeries *pass* arithmetic-only verification. That
test exists to keep the limitation visible rather than letting the level names imply more than they
do.

## 7. Limitations of the source parser

These are real and none of them is fixed by the certificate.

- **Currency is not detected** in the three statements used here. The cells carry
  `currency=None`; the scale (10^6) is certified, the currency is not. The economic amount is
  therefore "34,229 × 10^6 in the statement's reported currency", and claiming USD specifically
  would be an unsupported assertion. This is a capability gap, not a design decision.
- **Concept resolution is a semantic judgement.** The bytes prove that the row labelled
  "Net sales" contains 34,229 in the 2022 column. They do not prove that "Net sales" is the concept
  the question intended. That mapping is pinned in the manifest and reviewed; it remains a
  judgement, and the verifier says so in its own `limitations`.
- **Extraction is trusted.** Strict verification re-runs the same parser over the authenticated
  bytes. The hash authenticates the *document*; the parser is trusted to read it. A parser that
  silently mis-associates a column would produce a certificate that passes, with the wrong raw
  text — though the raw text is printed in the certificate, so a reviewer can see it.
- **One statement per document is recognised well.** 3M's FY2018 10-K keeps its statement titles in
  a form the statement classifier does not recover, which is the direct cause of the capability gap
  in section 8.
- **The corpus is four filings.** Nothing here generalises to "financial question answering". The
  claim is about a mechanism, demonstrated on files that were actually fetched.

## 8. Three abstentions, three different causes

The thirteen cases are named in `src/atlas/research/focus_cases.py`. Ten answer; three refuse. The
refusals are not equivalent and are not counted as successes.

| Case | Classification | Cause |
| --- | --- | --- |
| JPMorgan FY2022 gross profit | `justified_unanswerability` | No verified statement row of this issuer uses the concept. A bank's consolidated statement of income reports no gross profit line. |
| 3M FY2018 net sales | `capability_gap` | The FY2018 10-K prints a unique consolidated row: "Net sales 32,765" for 2018. Concept resolution did not bind it; it returned `ambiguous` after matching segment rows labelled "Sales (millions)". The question is answerable and Atlas failed to answer it. |
| 3M FY2022 at a 2017 cutoff | `historical_information_refusal` | Accession 0000066740-23-000014 covers 2022 but became available 2023-02-08T18:14:49Z, after the cutoff. |

The second row is the one worth reading twice. The resolver's own reason string said `ambiguous`.
Reporting that as "ambiguous evidence" would have converted a defect into a finding about the
question. The classifier in `focus_cases.diagnose` therefore ignores the resolver's label and
inspects the corpus: if a unique matching statement row exists at the cutoff, resolution failed and
the outcome is a capability gap. An earlier version of this table did report `ambiguous_evidence`
for this case; that was wrong and is the reason the diagnosis is now evidence-based.

Independent evidence for the claim: the row was located in the ingested FY2018 10-K by direct
inspection, and the same cell appears in the verified cell set (`row_label="Net sales"`,
`raw="32,765"`, `period="2018"`).

## 9. Defects found while building this

- **Stale schema assertion.** `scripts/reproduce_phase9_2.py` asserted `fresh_schema == 13` while
  the migration registry had advanced to 15. It now asserts against `LATEST_VERSION`. No migration
  was edited and no financial assertion was relaxed.
- **The answer packet did not record its operator.** Certificates were therefore labelling
  `answer_type` (`reported_value`) as the operator, which is a different fact. `_run` now records
  `operator` explicitly, and `build_certificate` refuses a packet that does not name a supported
  operator.
- **Scale declared inside the table was ignored.** 3M prints `(Millions, except per share amounts)`
  as the table's first row rather than in the caption. Reading only the caption produced scale 0, so
  $34.229bn was recorded as $34,229 — an error of 10^6 in the one number a reviewer would check
  first. Header-row text now participates in scale detection.
- **Refusal classification was derived from the resolver's status string.** See section 8.

## 10. The next difficult question

Scale and currency are recovered from whatever the table happens to print. The honest next question
is not "how do we parse more filings" but: **what is the minimal evidence that makes a concept
mapping correct rather than merely plausible?**

A defensible answer probably requires an independent structured source — SEC's `companyfacts` XBRL
API, keyed by accession and context — to corroborate the row the parser chose. That is a
corroboration problem with genuine conflict cases: custom inline XBRL tags often do not appear in
`companyfacts`, and when the two disagree the system must preserve the conflict rather than pick the
convenient number.

Until that exists, the correct statement about this system is narrow and should be made narrowly:
for four real 10-K filings, ten computed values are bound to specific printed cells, the printed
cells are authenticated against the original bytes, the arithmetic is reproduced by an independent
implementation, and sixteen self-consistent forgeries are refused. Everything else is a limitation
with a name.
