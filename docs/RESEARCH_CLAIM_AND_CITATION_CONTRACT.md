# Research claim and citation contract

Contract: `atlas.research_claim.v1` (`src/atlas/research/claims.py`).

A memo statement is not text with a number in it. It is a claim with an identity, a type, and
either resolvable evidence or a reproducible transformation. If neither can be established,
the claim is published as unsupported rather than softened into a fact.

## Claim record

| Field | Meaning |
| --- | --- |
| `claim_id` | `CLM-` + SHA-256 of issuer, type and key. Stable across rebuilds. |
| `research_object_id` | The memo that publishes the claim. Excluded from the memo hash. |
| `claim_type` | One of the seven types below. |
| `statement` | The exact sentence the memo renders. |
| `value`, `unit`, `currency` | Canonical decimal string and unit; never a formatted string. |
| `period` | Start, end, type and fiscal period the claim speaks about. |
| `cutoff` | Information cutoff the claim was built under. |
| `evidence_ids` | Every SEC record the claim rests on. |
| `observation_ids` | Market observations, when a price is cited. |
| `model` | Name, version, compiler version, fingerprint, audit verdict. |
| `assumption_ids` | Analyst assumptions the number depends on. |
| `transformation` | Human-readable formula or method. |
| `computation` | Machine-checkable inputs, formula key, operator version, tolerance. |
| `verification` | Outcome, checks and diagnostics. |
| `limitations` | What the claim does not establish. |

## Types

`observed_fact`, `derived_financial_metric`, `model_output`, `analyst_assumption`,
`analyst_hypothesis`, `methodology_disclosure`, `unsupported_claim`.

Only the first three are factual. An analyst hypothesis is never rendered as an observation,
and an assumption keeps its authored value and carries no evidence that would imply it was
reported.

## Verification outcomes

`verified`, `partially_verified`, `unsupported`, `missing_evidence`, `incompatible_model`,
`restricted_source`, `unverifiable_historical_availability`.

Non-factual claims carry the explicit marker `not_applicable` instead of borrowing a factual
outcome. There is no numeric confidence score: a reviewer reads the outcome and the
diagnostics.

## What each type is checked against

**Observed fact.** The cited record must exist, belong to the claimed issuer, cover the
claimed period, carry the claimed unit and currency, hold exactly the claimed value, and have
become available at or before the cutoff. A matching record sets `verified`; a missing record
sets `missing_evidence`; any other mismatch sets `unsupported` with a named diagnostic.

**Derived metric.** Every input must resolve to stored evidence with the stated value, the
value must reproduce from the recorded formula with a relative tolerance of `1e-9`, and the
operator version is recorded (`atlas.claim.arithmetic.v1`). The recomputation is written in
the verifier, not called from the read model that produced the number.

**Model output.** The execution manifest must name the model and version, the compiler version
must match the current implementation, the independent component audit must have passed, and
at least one assumption must be declared. An audit failure sets `unsupported`; a different
compiler sets `incompatible_model`.

## Diagnostic codes

`evidence_missing`, `issuer_mismatch`, `period_mismatch`, `value_mismatch`, `unit_mismatch`,
`currency_mismatch`, `availability_after_cutoff`, `model_incompatible`, `model_audit_failed`,
`observation_revision_unresolved`, `citation_span_unavailable`, `export_rights_prohibited`.

Diagnostics are never dropped. A claim that fails verification stays in the memo, appears in
the unresolved-contradictions section, and is counted by the evidence-integrity dimension.

## Citations

Every citation resolves to a stored object:

* SEC evidence — CIK, accession number, form type, filed date, acceptance timestamp,
  reporting period, XBRL concept, value, unit, evidence id, source document id, content hash,
  and an inspector path.
* Market observation — security, MIC, provider, session, revision, observation id, content
  hash, rights class and adjustment convention.
* Model output — model, version, compiler version, operator versions, fingerprint, inputs,
  assumptions and audit verdict.

**What is never invented:** a page number, a quotation, or a passage offset. Atlas stores the
structured fact and the source document id; if exact passage localisation is unavailable the
citation says so (`passage: null` with a stated reason) instead of fabricating one.

## Rights

A citation carries the rights class of its source. `claim_contract.rights_decision()` treats
`public_domain`, `project_authored` and `permitted` as redistributable and everything else —
including an unknown class — as restricted. Export refuses when a cited source is restricted,
and the refusal names the source. Rights are a decision, not a warning.
