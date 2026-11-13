# Phase 9.6.1 — Security and Recovery

New fault-injection coverage in `tests/test_phase9_6_1_security.py` (5 tests, all passing) plus the
temporal suite's immutability tests.

| Failure path | Test | Result |
| --- | --- | --- |
| Corrupted passage bytes | body edited after citation; `verify_document_claim` returns `passage_corruption` and **not** `verified` | pass |
| Script content in source HTML | `<script>alert('x')</script>` never appears in extracted text | pass |
| Oversized document | `MAX_DOCUMENT_BYTES` exceeded → `ValidationError` | pass |
| Truncated gzip / bad Content-Encoding | `_decoded` rejects a half gzip stream | pass |
| Query resource exhaustion | >128 terms raises `ValidationError` before FTS work | pass |
| Duplicate accession with different bytes | immutable document rule raises | pass |
| Corpus growth between identical queries | earlier result set unchanged | pass |
| Cross-issuer substitution | issuer mismatch diagnostic (existing Phase 9.5 tests) | pass |
| Claim verification after tampering | hash mismatch blocks `verified` | pass |

## What this means

A corrupted document cannot yield a verified claim: verification recomputes SHA-256 from the stored
body and compares it with both the stored digest and the citation's digest, and the span and issuer
are checked independently. Partial ingestion cannot leave a plausible but incomplete document
because units, tables and the FTS row are written inside one transaction and the document row is
only marked `indexed` on success.

## Not covered

* Decompression-bomb expanded size beyond the byte cap (the cap is checked post-decode; an
  expansion-ratio guard is not implemented).
* Concurrent ingestion and read isolation under WAL contention.
* Index rebuild after deliberate FTS corruption (no `rebuild` command is exercised).
* Prompt injection: retrieved text is rendered as data and no model consumes it, so there is no
  injection surface to test yet — this changes if an LLM layer is added.
* Unauthorised export of restricted sources is covered by existing rights tests, not re-audited.

## SEC access posture

`ATLAS_SEC_USER_AGENT` is required (no fictional contact in code), requests are throttled at
0.15 s, retried three times with backoff, and payloads are gzip-sniffed by magic bytes. The API
remains local and single-user; no isolation guarantee is implied.
