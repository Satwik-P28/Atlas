# Phase 9.6 — Security and Recovery

## SEC fair access

| Control | Implementation |
| --- | --- |
| User agent | required from `ATLAS_SEC_USER_AGENT`; unset → `ValidationError("SEC_USER_AGENT_UNSET")` |
| Contact address | supplied by the operator; no fictional address is hard-coded |
| Throttling | `SEC_MIN_INTERVAL = 0.15` s between requests |
| Retries | 3 attempts with backoff on transport/5xx |
| Encoding | gzip sniffed by magic bytes, not by header |
| Payload | response body size checked before decode; failures counted per document |

The corpus build ingests 64 documents with 0 failures and 18 recorded exclusions. A 403 from EDGAR
is surfaced as a build failure rather than silently skipped.

## Tested this phase

* Ingest failure accounting: every excluded or failed document is written to the corpus manifest
  with a reason; no question disappears from the evaluation without an exclusion record.
* Cutoff enforcement is re-verified per returned passage by the evaluator (source-availability
  timestamp compared with the question cutoff), giving future-leak rate 0.0000.
* Invalid `support_policy` values raise `ValidationError` instead of silently falling back.
* Passages are re-hashed on read in the evaluator and in the case study; corruption would surface
  as a citation-integrity failure rather than a plausible-looking quotation.

## Not tested this phase — recorded as gaps

| Area | Status |
| --- | --- |
| Malicious HTML / script injection in filings | not newly tested |
| Archive/decompression bomb and expanded-size limits | limits exist in the ingestion path; no new adversarial test |
| Truncated downloads and corrupted bytes | retry logic exists; no fault-injection test |
| Prompt injection inside retrieved documents | retrieval returns text to a UI, no LLM consumes it; not tested |
| Cache isolation by cutoff/identity/entitlement | no new cache layer was introduced |
| Concurrency, cancellation, partial-ingestion recovery | not tested |
| Index rebuild / transactional recovery | migration path exercised (13→14 on a DB copy); rebuild not fault-injected |
| Query resource exhaustion | query length bounded by the API schema; no adversarial load test |

## Data handling

* `var/phase9_6.db` holds third-party filing bytes and stays out of Git.
* FinanceBench rows are CC-BY-NC-4.0 evaluation material and stay out of Git.
* The API remains local, single-user and unauthenticated; no isolation guarantee is implied.
* Repository remains private; no restricted dataset was pushed.

## Assessment

The network-facing ingestion path is conservative (declared identity, throttling, retries,
byte-level decoding). The adversarial matrix above is incomplete, so this document does **not**
certify Phase 9.6 as security-hardened; it records what was actually verified.
