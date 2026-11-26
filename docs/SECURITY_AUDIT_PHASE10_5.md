# Security audit — Phase 10.5 release candidate

Scope: the distribution candidate built from the release-closure commit — the wheel, the sdist,
the sanitized source tree and the local server those artifacts run. This is an audit of specific
claims, not a penetration test or a proof of application security.

## What was checked, and the result

| Area | Method | Result |
| --- | --- | --- |
| Dependency vulnerabilities | `scripts/scan_dependencies.py` over the installed environment, recorded in `docs/DEPENDENCY_LICENSES.json` | PASS — see the inventory's `vulnerability_scan` block; the exact finding count is whatever that block records, and it must be re-read at release time |
| Secrets in the source tree | Pattern scan (`sk-…`, `AKIA…`, `ghp_…`, private-key blocks, Slack tokens) over every tracked file | PASS — 0 hits |
| Secrets in the wheel | The same patterns over every text member of `dist/atlas_quant-0.2.0b1-py3-none-any.whl` | PASS — 0 hits |
| Host-header protection | `tests/test_release_security_9_2_5.py` (22 tests) | PASS — 22 passed |
| DNS rebinding | The same suite: the server rejects unexpected `Host` values, so a rebinding origin cannot reach the loopback API | PASS (same suite) |
| Cross-origin mutations | Same-origin enforcement on mutating routes, covered by the security suite | PASS (same suite) |
| SSRF | Outbound requests are limited to the SEC endpoints the client constructs; user-supplied URLs are not fetched | No finding (`tests/test_release_security_9_2_5.py`, connector tests) |
| Malicious document ingestion | Parser bounds and validation tests, plus the archive-reader hardening below | PASS for the tested corpus; arbitrary hostile HTML was not fuzzed |
| Archive traversal | `scripts/build_clean_history_candidate.py` rejects absolute members and `..` parts and extracts with `filter="data"` | PASS (unit of the builder; exercised on the release snapshot) |
| Archive bombs | Sanitizer reads a deterministic `tar.gz` it wrote itself; no user-supplied archives are accepted by the application | NOT APPLICABLE for the shipped surface; no generic archive ingestion path exists |
| Unsafe HTML | The frontend renders document text as text, not `dangerouslySetInnerHTML` (no such call in `web/src`) | PASS by inspection |
| SQL injection | Values are bound with `?` placeholders. 45 sites interpolate SQL *identifiers* (savepoint names, internal column lists, a table name from an internal constant) | PASS with a review note: identifier interpolation is safe only while those identifiers remain internal constants |
| MCP authorization | `tests/test_mcp_sdk_interop.py` with the official SDK: mutations refused in read-only mode with `authorization_required` | PASS |
| Credential leakage | SEC contact identity comes from `ATLAS_SEC_USER_AGENT`; nothing is written to the database or logs. No vendor keys exist in the release | PASS |
| Resource exhaustion | MCP call timeout, HTTP request limits and pagination caps are configured; a sustained-load test was not run | PARTIAL |

## Local-only defaults that must stay enforced

1. The API binds to loopback. Do not run it on `0.0.0.0`, do not put it behind a public proxy, and
   do not expose it through a tunnel. It has no authentication by design.
2. The MCP server is read-only unless `--allow-mutations` is passed explicitly.
3. Exports that would redistribute a source without a redistribution right are refused at the API,
   not merely hidden in the UI.

## Findings that were fixed during this phase

- **Blank Answers page after "Build certificate"** (frontend): the certificate response was stored
  in the resolution slot, and the next render read `resolution.question.issuer_id` from an object
  that has no `question`. Fixed; the browser certification now exercises the full certificate path.
- **Ambiguous column labels** (citation fidelity): statements that place currency symbols in their
  own columns could describe a 2026 value with the 2025 header. The value and resolved period were
  correct; the label was not. The API now reports `citation_quality: ambiguous_column_label` and
  `column_label_agrees_with_period: false` instead of asserting the label.

## What this audit does not establish

- No third-party penetration test, fuzzing campaign or formal threat model review.
- No multi-user isolation testing, because the release is single-user by design.
- No long-running load, memory-exhaustion or adversarial-filing campaign.
- A clean scan is not evidence that the application is secure; it is evidence that the listed
  checks were performed and their results recorded.
