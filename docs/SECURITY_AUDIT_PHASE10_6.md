# Security audit — Phase 10.6 (targeted closure)

Scope: the exact artifacts that are candidates for publication. This is a targeted closure of
the items Phase 10.5 left open, not a new audit programme.

## 1. SQL identifier interpolation

The Phase 10.5 audit flagged 45 identifier-interpolation sites for review. The current inventory
finds 49 interpolated statements; each one is classified, read in place and recorded in
`docs/SECURITY_SQL_INTERPOLATION.json`. Four splice a name into the text:

| Site | Name spliced | Control |
| --- | --- | --- |
| `evidence/kernel.py:619` | `AsOfMode.column` | two-member enum |
| `evidence/selection_sql.py:242` | `AsOfMode.column` | two-member enum |
| `mcp/tools.py:498` | table for the health counts | literal tuple in the tool |
| `storage/db.py:221` | `row_count(table)` | `_SAFE_IDENTIFIER` + typed refusal |

No user-controlled value reaches SQL text. Details and adversarial tests: `docs/SECURITY_SQL_REVIEW.md`
and `tests/test_sql_structure_safety.py` (9 tests passing).

**Verdict:** no exploitable structure-injection path found in the reviewed code; no code change
was required beyond the tests that pin the four controls.

## 2. Bounded resource-exhaustion audit

`scripts/audit_resource_limits.py` runs nine shapes against one process and one local server and
records timings, peak RSS and recovery. Full output: `artifacts/release/resource_limits.json`.

| Case | Result |
| --- | --- |
| Malformed HTML (300 tables, overrunning spans, nesting) | PASS — 34 KB of broken markup ingested without a crash; 0 tables kept (the parser drops what it cannot grid), 1 unit |
| Large financial table (4,000 rows × 5 periods) | PASS — 353 KB, 0.2 s, 1 table, 2 units |
| Oversized document | PASS — 31.3 MB is **refused** with the typed ingestion limit (`limit=25,165,824`) |
| Large CSV (200,000 rows) | PASS — 2.4 s, 128 MB peak; the importer de-duplicates to 28 sessions for the repeated dates |
| Archive expansion | PASS — a 16 KB ZIP expanding to 16 MB and a 200-entry package are both refused before extraction |
| 200 concurrent invalid API requests | PASS — 200/200 refused with 4xx; `/api/health` healthy afterwards |
| Client cancellation (20 dropped mid-response) | PASS — server healthy afterwards |
| Four concurrent MCP sessions | PASS — 4/4 answered `initialize` |
| Expensive model request | NOT RUN — no model provider is configured in this environment; not claimed |

Peak RSS for the whole audit process stayed at 129 MB, well under the 2 GB case bound. No case
left the application unresponsive.

**Verdict:** the tested workload is bounded and recovers. This is not a fuzzing campaign, a
memory-profiler trace or a multi-user isolation test.

## 3. Dependency and secret scans on the candidate

* `scripts/scan_dependencies.py`: Python and npm clean; 0 critical/high/moderate/low findings.
* `scripts/audit_distribution.py`: the working tree contains no restricted vendor data and no
  secret-like path or content. Nine vendor market-data files remain reachable in **published
  history** (see `docs/REPOSITORY_MIGRATION.md`); the working tree, wheel, sdist and sanitized
  source are clean.
* Secret patterns (`sk-…`, `AKIA…`, `ghp_…`, private-key blocks) are re-checked over the
  candidate tree and inside the built wheel before publication.

## 4. Defects found and fixed in this phase

| Defect | Impact | Fix |
| --- | --- | --- |
| Statement values were unclickable in a narrow desk panel | The evidence inspector could not be reached with the pointer at all; the frozen label column was 186 px wide in a 241 px panel and covered every value | Row labels and concept keys truncate to 108 px, leaving room for the values (`web/src/styles.css`) |
| Saving an unchanged memo version returned 422 and left the export controls unreachable | A reader could not export a PDF of a memo that was already stored | `ResearchMemoService.save` is idempotent when the stored version has the same content hash; a *different* memo under an existing version is still refused |
| Cited column could name a different year than the resolved period | A 2026 value cited a "2025" header when the filer puts `$` in its own column | Period/label alignment from the printed header slot sequence, contested columns refused (`table_cells.py`), and the answer API refuses a citation whose label contradicts its period (`answers_api.py`) |

## 5. What this audit does not establish

* No third-party penetration test, fuzzing campaign or formal threat model.
* No load test beyond the nine bounded cases above, and no multi-hour soak.
* No claim about a deployment: the local API has no authentication and must not be exposed
  publicly.
* No claim that the current tree's cleanliness remedies the published history.
