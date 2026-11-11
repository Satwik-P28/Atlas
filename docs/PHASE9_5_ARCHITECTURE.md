# Phase 9.5 — Financial Knowledge Engine architecture

## 1. Where the engine sits

The FKE is a retrieval and grounding layer **inside** the existing stack, not a parallel one:

```
SEC EDGAR ──► ingestion driver ──► knowledge_document / knowledge_unit / knowledge_table
                                          │
                                          ▼
                             SQLite FTS5 (BM25) index
                                          │
        cutoff + issuer + policy filter ──┤
                                          ▼
                     KnowledgeEngine.search  ──►  passages with exact spans
                                          │
                                          ▼
              knowledge_claims (epistemic status + citation verification)
                                          │
                     ┌────────────────────┴────────────────────┐
                     ▼                                         ▼
           Standard /filings page                  Advanced `filing` panel
                                                (link groups, desk cutoff)
```

It reads `issuer` and `source` from the Temporal Evidence Kernel, classifies rights through
`atlas.research.rights`, and never creates a second evidence, permission or object store.
Financial arithmetic remains in the FEC; this phase adds no new calculation engine.

## 2. Storage

Migration **014** (`phase9_5_financial_knowledge_engine`) adds four tables and one virtual table:

| Object | Purpose |
| --- | --- |
| `knowledge_document` | One row per accession: issuer, form, amendment link, period, filing date, acceptance time, availability time + precision + basis, URL, SHA-256, bytes, rights, parser version, counts, status |
| `knowledge_unit` | Deterministic passages: kind (`heading`/`paragraph`/`table`), section path, body, `char_start`/`char_end`, SHA-256 |
| `knowledge_table` | Table rows, detected periods, footnotes, caption, cell locator |
| `knowledge_fts` | FTS5 index over body/heading/section with unit and document ids as unindexed columns |
| `knowledge_query_log` | Plan, cutoff, policy, result count, abstention, latency for every search |

The FTS index is derived. Deleting it and rebuilding from `knowledge_unit` loses nothing.

## 3. The five times that must not be confused

| Column | Meaning |
| --- | --- |
| `period_of_report` | The fiscal period the document describes |
| `filed_date` | The date the SEC lists the filing |
| `acceptance_time` | The SEC acceptance timestamp (seconds precision) |
| `availability_time` | What the retrieval cutoff compares against |
| `ingested_at` | When this database received the bytes |

`availability_precision` is `exact` only when an acceptance timestamp exists; otherwise it is
`date` and every citation built from it is downgraded to
`unverifiable_historical_availability` rather than presented as precise history.
Two policies are supported and never mixed: `public_available` filters on availability time,
`atlas_ingested` filters on ingestion time. The second answers "what did *this* database know
then", which the spec (§17.2) distinguishes from historical public knowledge.

## 4. Code paths

| Path | Responsibility |
| --- | --- |
| `src/atlas/research/knowledge.py` | Extraction, storage, BM25 retrieval, table access, version comparison, SEC adapter |
| `src/atlas/research/knowledge_claims.py` | Epistemic statuses, citation verification, counter-evidence candidates, revision impact |
| `src/atlas/terminal/knowledge_api.py` | `/api/knowledge/*` routes (read-only except query log) |
| `src/atlas/storage/migrations.py` | Migration 014 |
| `scripts/phase9_5_ingest.py` | Offline ingestion driver (no write API by design) |
| `scripts/phase9_5_benchmark.py` | Pre-registered evaluation harness |
| `web/src/pages/Filings.tsx` | Standard document-research workspace |
| `web/src/terminal/panels/registry.tsx` | `filing` panel for the Advanced desk |
| `web/e2e/phase9_5_filings.mjs` | Chromium certification of the research path |

## 5. Boundaries deliberately kept

- **No embeddings, no LLM, no vector database, no new service.** The specification requires a
  measured improvement over the lexical baseline before adopting a more complex retriever; this
  phase establishes the baseline and the harness to judge one, and nothing more.
- **No generation.** Passages are verbatim source text. The only "summary" is the analyst's own
  claim object, which carries the citation or abstains.
- **No write API.** A client cannot upload a document; ingestion is an offline, auditable command.
- **No retired numeric contract.** `atlas.research_memo.v1` is unchanged; document claims are a
  separate versioned object (`atlas.knowledge.claim.v1`) referenced from the memo.

## 6. Failure behaviour

- Unknown issuer, unknown accession, duplicate accession with different bytes → `ValidationError`.
- Document over 24 MB, empty payload, no extractable text → rejected with the reason.
- Corpus without the migration → API returns 503 `knowledge_schema_missing` with the fix.
- Search with an unknown policy → 422 with the supported list.
- Tampered passage (body no longer matching its hash) → `passage_corruption`, claim not verified.
- No supporting passage → abstention with a named reason, never an unrelated match.
