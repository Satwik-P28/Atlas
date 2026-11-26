# Phase 9.5 — master specification conformance

Authoritative document: `ATLAS_MASTER_SPEC.md` v3.1.0 (333,547 bytes, SHA-256
`d1800cfe…`, 61 sections, four appendices, ICB-01…ICB-64). The specification was **not** edited
in this phase.

| Contract | Implemented behaviour | Evidence | Missing behaviour | Status |
| --- | --- | --- | --- | --- |
| §49.1 FKE boundary inside TEK | Retrieval layer over archived documents; no second evidence store; FEC untouched | `research/knowledge.py`, migration 014, `knowledge_claims.py` | — | Conforms |
| §49.2 Distinct information classes | Raw bytes, units, tables, claims and numeric evidence are separate objects; units carry span + hash + rights | `knowledge_document`, `knowledge_unit`, `knowledge_table`, `atlas.knowledge.claim.v1` | Embedding artifacts, summaries, graph edges | Partial |
| §49.2 `resolve_original` / `show_span_or_cell` / `show_source_rights` / `state_missingness` | Each passage returns URL, exact character span (or `table-block`), rights class, and absence is named | `/api/knowledge/units/{id}`, `/api/knowledge/search` | `show_transform`, `challenge` as first-class API operations | Partial |
| §49.3 Exact + lexical retrieval | FTS5/BM25 with section/heading weighting, issuer/form/section filters, pagination via `limit` | benchmark hit@5 0.909 | Dense, hybrid, reranking, graph, multimodal, computational routing | Partial |
| §49.3 Router records plan and cost | Plan, policy, cutoff, filters, counts and latency recorded per query and logged | `knowledge_query_log`, response `plan`/`latency_ms` | Cost/credit estimation | Partial |
| §49.4 Historical vs restated | `public_available` vs `atlas_ingested`; cutoff applied before ranking; amendments kept separate; `compare` + `revision_report` | `test_cutoff_excludes_later_filing`, benchmark leak 0.000 | Time Capsule replay of a full environment (§17.2) | Partial |
| §49.4 Contradiction handling | Both passages retained; negation-language candidates surfaced for review; conflicts never collapsed | `_counter_evidence`, `test_amendment_comparison_and_claim_impact` | Semantic contradiction detection | Partial |
| §49.5 Evidence-grounded answering | Passages → claim with epistemic status → citation verification → abstention; no generated text stored | 21 knowledge tests, citation support 1.000 | Natural-language synthesis; no LLM by design | Partial |
| §49.6.1 Amendment vs original | Separate documents, `is_amendment`, `amends_accession`, `right_amends_left` | `test_amendment_comparison_and_claim_impact` | Real 10-K/A not ingested (none in the recent window) | Partial |
| §49.6.2 Revenue question with verified arithmetic | Numeric claims remain the existing FEC/memo path; document claims cite them without recomputation | unchanged `atlas.research_memo.v1` tests | Joint textual+numeric answer synthesis | Partial |
| §49.6.3 Right document, wrong passage | `span_mismatch` fails verification; `distinctive` term absence abstains | `test_tampered_passage_fails_citation_verification` | Forced second retrieval pass | Partial |
| §49.6.4 Cross-document comparison | `compare` across two documents of one issuer; multi-document question in benchmark | `engine.compare`, benchmark `multi_document` | Cross-issuer comparative memo | Partial |
| §49.6.5 Reproduce after restart | Documents, spans and claims are stored; benchmark reruns deterministically | `test_spans_are_exact_and_ordered`, benchmark rerun | Process-restart latency reproducibility record | Partial |
| §49.6.6 Restricted bytes never exposed | `restricted_source` blocks export; API returns excerpts and metadata only | `test_restricted_source_blocks_export` | Full document download endpoint (deliberately absent) | Conforms |
| §49.6.7 Quantified retrieval errors | Pre-registered thresholds, per-question rows, published failures | `artifacts/phase9_5_benchmark.json` | Independent human-reviewed reference answers | Partial |
| §17.2 Time Capsule | Availability-policy retrieval is the historical knowledge half | `PHASE9_5_HISTORICAL_RETRIEVAL.md` | Execution reproduction of archived computations | Not implemented |
| §39.1–39.4 Research desk | Filings research workspace in Standard, `filing` panel in Advanced, same backend | `web/src/pages/Filings.tsx`, `registry.tsx` | Forecast/valuation linkage of qualitative findings | Partial |
| §51 Intent-to-Research Compiler | Not implemented; no plan object, no typed workflow compilation | — | Entire section | Not implemented |
| §52, §54, §56, §59, §60 | Untouched by this phase; no claim made | prior phase docs | — | Unchanged |
| ICB-34 | Evidence-backed risk/qualitative retrieval demonstrated on 2 issuers | benchmark + screenshots | Named benchmark workflow not executed end-to-end with an independent analyst reference | Incomplete |
| ICB-39 | Historical cutoff retrieval works | cutoff tests, leak 0.000 | Full historical reconstruction of a research environment | Incomplete |
| ICB-48 | Complete flagship workflow not executed | — | Licensed historical market data, narrative coverage, professional comparison, notification delivery | Incomplete |
| ICB-63 | Citation-verified qualitative claims with abstention | 21 tests, citation 1.000 | Human-review workflow | Partial |

## Statement of non-claims

Atlas does **not** claim: dense or hybrid retrieval, LLM-grounded answering, institutional-grade
document coverage, human-reviewed benchmark accuracy, contradiction detection beyond lexical
candidates, or completion of ICB-34/39/48. The scoreboard was not edited to reflect this phase.
