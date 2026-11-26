# Phase 9.5 — memo integration

## 1. Contract

`atlas.knowledge.claim.v1` is a separate, versioned object. It does not replace
`atlas.research_memo.v1`; it attaches to it.

```json
{
  "schema": "atlas.knowledge.claim.v1",
  "claim_version": "1.0.0",
  "claim_id": "KCL-…",
  "key": "customer-concentration",
  "issuer_id": "ISS-CIK0000320193",
  "question": "customer concentration risk",
  "cutoff": "2026-06-01T00:00:00Z",
  "policy": "public_available",
  "epistemic_status": "observed_fact",
  "statement_kind": "verbatim_excerpt",
  "statement": "10-K 0000320193-26-000026 · Item 1A. Risk Factors: “…”",
  "citations": [{ "unit_id": "UNI-…", "char_start": 44297, "char_end": 44465, "unit_sha256": "…" }],
  "counter_evidence": [],
  "verification": { "outcome": "verified", "checks": [], "diagnostics": [], "export_allowed": true },
  "limitations": ["…"]
}
```

## 2. Epistemic statuses

| Status | Meaning | Can be presented as fact |
| --- | --- | --- |
| `observed_fact` | The filing states this, cited to an exact span | Yes, as a statement about the filing |
| `analyst_inference` | Interpretation with stated premises | No |
| `hypothesis` | Not established by the citation | No |
| `unsupported` | No supporting passage at the cutoff; no citation is attached | No |

The status is set at construction and is not upgraded by verification. A verified citation
proves *the filing says this*; it does not prove the company's assertion is economically true,
and the limitation list says so.

## 3. Verification

`verify_document_claim` checks, per citation:

| Check | Failure code |
| --- | --- |
| Passage exists | `passage_missing` |
| Passage belongs to the cited document | `document_mismatch` |
| Passage belongs to the claimed issuer | `issuer_mismatch` |
| Recomputing the body hash matches the stored hash | `passage_corruption` |
| Stored hash matches the hash captured at claim construction | `passage_hash_mismatch` |
| Stored span matches the cited span | `span_mismatch` |
| Availability time is not after the cutoff | `availability_after_cutoff` |
| Availability precision is exact | `availability_date_precision` (downgrades outcome) |
| Rights permit export | `restricted_source` (blocks export) |

Outcomes: `verified`, `partially_verified`, `missing_evidence`, `unsupported`,
`unverifiable_historical_availability`, `restricted_source`. A citation to the correct filing but
the wrong paragraph fails `span_mismatch`, which is the failure mode the specification calls out.

## 4. Attaching to a memo

```python
from atlas.research.knowledge_claims import attach_document_claims

memo = ResearchMemoService(db).build("ISS-CIK0000320193")
memo = attach_document_claims(memo, document_claims)
memo["document_claim_summary"]
# {"total": 2, "verified": 2, "unsupported": 0, "restricted": 0, "schema": "atlas.knowledge.claim.v1"}
```

Additive migration, no version bump:

- `document_claims` is a new optional key; existing readers ignore it.
- `document_claim_summary` reports counts without changing any numeric claim.
- `content_hash` is recomputed with the **existing** `memo_hash`, so reopen and export
  verification continue to work; `memo_id` follows the hash.
- No numeric claim, formula, evidence id, integrity dimension or section is modified.

This is the "documented migration" the specification permits: rather than restating the numeric
memo schema, the qualitative claims travel in a typed side-channel that the same hash protects.

## 5. Revision intelligence

`revision_report(engine, earlier, later, claims)` returns the section-level comparison, the claims
whose cited passages now fall in changed or removed sections, and rule-based significance. It never
rewrites the earlier memo and never assigns a model-generated confidence score. A legitimate
outcome is "nothing material changed", represented by empty `impacted_claims`.

## 6. Limits

- Claims are constructed from retrieved passages with a fixed excerpt; there is no multi-passage
  synthesis into a paragraph, so a claim states one thing from one passage.
- Counter-evidence is a lexical negation heuristic, labelled as candidates for review.
- No human review workflow, approval queue or signature exists yet.
- Document claims are not written into `research_object` rows in this phase; they are persisted
  with the memo payload the caller stores.
