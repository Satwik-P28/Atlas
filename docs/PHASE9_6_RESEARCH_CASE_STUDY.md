# Phase 9.6 — Cross-Issuer Research Case Study

**Artifact:** `artifacts/phase9_6_case_study.json` (`schema: atlas.phase9_6.case_study.v1`)
**Script:** `scripts/phase9_6_case_study.py`
**Label:** `self_authored` (question and comparison framing were written for this phase)

## Design

| Field | Value |
| --- | --- |
| Question | "What does the company disclose about liquidity and capital resources?" |
| Issuers | Boeing (CIK 0000012927), Lockheed Martin (CIK 0000936468) |
| Cutoff | `2021-06-30T00:00:00Z` |
| Policy | `public_available` |

Both issuers are aerospace and defence manufacturers, so their liquidity disclosures are
legitimately comparable in kind. They are not comparable in period, and the artifact says so.

## Outcome

| Issuer | Document | Period | Claim kind | Integrity on reopen |
| --- | --- | --- | --- | --- |
| Boeing | `0000012927-19-000010` | FY2019 | `verbatim_excerpt` | hash ✓ issuer ✓ available-before-cutoff ✓ |
| Lockheed Martin | `0000936468-21-000013` | FY2020 | `verbatim_excerpt` | hash ✓ issuer ✓ available-before-cutoff ✓ |

Each side carries a real source passage, the document's availability timestamp and precision, and
the exact section locator. The artifact was written and then reopened: the stored excerpt was
re-hashed against the database and matched in both cases, so the comparison is reproducible from
the database, not from prose.

## What the comparison asserts

* **Comparable facts:** both filings are annual reports available before the same cutoff, and both
  discuss liquidity and capital resources as a management disclosure.
* **Not equivalent:** the fiscal periods differ (FY2019 vs FY2020); the two issuers describe
  liquidity with different instruments and vocabularies; no ratio is computed across them and no
  equivalence is claimed. `equivalence_asserted: false` is stored in the artifact.
* **Missing data:** customer-concentration wording was not located for every issuer, so it is
  recorded as missing rather than treated as an absent risk — the absence of a phrase is not
  evidence that a risk does not exist.
* **Management assertions vs facts:** the excerpts are labelled as what the filing says, not as
  economically validated conclusions.

## Limitations

* This is one pair and one question, authored by the same engineer who built the retriever; it
  demonstrates the pipeline and the epistemic discipline, not comparative-research accuracy.
* No memo object was produced: the existing memo service builds from equity analysis, and creating
  a parallel comparative-research product was explicitly out of scope. The artifact therefore
  reuses the claim and citation primitives without a memo export.
