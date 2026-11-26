# Phase 9.5 — final report

## 1. Repository state

| Ref | Commit |
| --- | --- |
| Starting commit | `0f9d6861c57d44925c3f0f3a3f32fe4899edeb3e` |
| Schema | 13 → **14** (migration `phase9_5_financial_knowledge_engine`) |
| Master spec | v3.1.0 unchanged, 333,547 bytes, SHA-256 `d1800cfe…`, 64 ICB ids |

## 2. What was built

A Financial Knowledge Engine over real SEC filings, inside the existing TEK/UROS/FEC stack:

- **Ingestion** of primary SEC documents: content-addressed, with acceptance time, availability
  precision, amendment links, rights, parser version and exact passage spans.
- **Deterministic extraction**: headings → sections, paragraphs, tables with rows, captions,
  detected periods and footnotes.
- **Historical retrieval**: SQLite FTS5/BM25 with issuer, form, section and cutoff filters applied
  before ranking; `public_available` and `atlas_ingested` policies kept distinct.
- **Abstention** when a query term is absent from the corpus or nothing satisfies the cutoff.
- **Claims**: `atlas.knowledge.claim.v1` with epistemic status, exact citation, counter-evidence
  candidates and verification that recomputes the passage hash.
- **Revision intelligence**: section-level comparison, amendment relationship, claims whose cited
  text changed, rule-based significance, and an explicit statement that earlier research stands.
- **Interfaces**: Standard `/filings` workspace and an Advanced `filing` panel that follows link
  groups and the desk cutoff; both call the same API.
- **API**: `/api/knowledge/{stats,documents,documents/{id},units/{id},documents/{id}/tables,
  search,claims,compare,revisions}`; ingestion remains an offline command.

Corpus used: 6 real documents (Apple and JPMorgan 10-K/10-Q), **6,551 passages**, **698 tables**,
27.5 MB of source text.

## 3. Verification

| Check | Result |
| --- | --- |
| Full Python backend suite | **passed, exit 0** |
| New knowledge tests | 21 passed |
| Registry + workspace layout tests | 26 passed |
| Schema/API pinned tests after migration 014 | 52 passed (targeted rerun) |
| Frontend unit tests | 45 passed (4 files) |
| TypeScript typecheck | exit 0 |
| Production build | succeeds, entry 301.37 kB (94.33 kB gzip) |
| Master-spec integrity | VERIFIED (size + SHA-256) |
| Retrieval benchmark gates | 4/4 pass |
| Browser journey | **9/9 checks**, 0 console errors, 0 failed requests |

Tests changed, and why:

- `schema_version` pins moved 13 → 14 in ten test modules, and migration-run lists gained `14`.
  A new migration is exactly the event those pins exist to catch; the numbers were updated, not
  deleted.
- The OpenAPI fixture was **regenerated** with the nine new knowledge routes (133 → 142 paths,
  147 → 156 operations) and the assertion counts follow it. The rest of the projection is
  unchanged, so the contract check still compares operation ids, parameters, bodies and responses.

No assertion was weakened, skipped or deleted.

## 4. Benchmark

`artifacts/phase9_5_benchmark.json` — 13 pre-registered questions, 6 documents:

| Metric | Value |
| --- | --- |
| hit@5 | 0.9091 (gate ≥ 0.70) |
| Citation support | 1.0000 (gate ≥ 0.90) |
| Future leak rate | 0.0000 (gate = 0) |
| Cross-issuer rate | 0.0000 |
| Abstention recall (unanswerable) | 1.0000 (gate ≥ 0.80) |
| Answerable abstention rate | 0.0909 (reported) |
| Latency p50 / p95 | 7.7 ms / 18.7 ms |

Published failures: abstention was 0.0 before the absent-term rule; one answerable question
abstains because *concentration* is absent from the JPM passage set; two historical questions were
vacuous until their cutoffs were moved to a date where a newer filing genuinely exists.

## 5. Browser certification

`docs/PHASE9_5_BROWSER_ACCEPTANCE.md`: 9/9 at 1440×900 and 390×844, screenshots
`artifacts/phase9_5_filings.png` and `artifacts/phase9_5_filings_mobile.png`. The Standard
interface is certified. **The Advanced `filing` panel is implemented, registered and typechecked,
but not driven in a browser** — recorded as a gap, not a pass.

## 6. Unresolved blockers and non-claims

1. **ICB-34 / ICB-39 / ICB-48 are incomplete.** The flagship end-to-end workflow was not executed:
   licensed historical market data, narrative coverage, professional comparison and notification
   delivery are still missing. The scoreboard was not adjusted.
2. **No dense, hybrid, graph or multimodal retrieval.** Spec §49.3 lists them; none was implemented
   or measured, and the specification requires measured improvement before adoption.
3. **No LLM answering.** Model-generated text is never evidence, and no model is used.
4. **Advanced document panel not browser-certified.**
5. **Benchmark is small and self-authored.** 13 questions, 6 documents, one engineer, no independent
   human reference answers, no second retriever.
6. **Ingestion is HTML-only.** No PDFs, exhibits, OCR or footnote-to-cell attachment.
7. **Repository remains private.** The historical restricted-market-data issue is unchanged and
   still blocks public release.
8. **No authentication.** The API stays a local, single-user service; it must not be deployed as a
   public multi-user endpoint.

## 7. Promotion

Gates met: full suite passing, zero historical leakage, citation and rights enforcement verified,
browser research journey verified, spec integrity intact, no critical research-integrity defect.
Promotion is by fast-forward only; the branch history contains no rewrite.

## 8. Suggested Phase 9.6 scope

1. Independent, human-reviewed retrieval evaluation with a second corpus and a dense baseline —
   the only honest way to justify a more complex retriever.
2. Advanced `filing` panel browser certification and cross-issuer comparative memos.
3. PDF/exhibit ingestion with page-level localization and rights handling.
4. Time Capsule execution reproduction, so a memo can be re-run against archived documents.
5. Joint textual + numeric answering through FEC, with arithmetic verified independently of the
   retrieval layer.
## 9. Reproduce

```bash
python -m atlas.cli --db var/phase9_5.db migrate
python scripts/phase9_5_ingest.py --db var/phase9_5.db --cik 0000320193 --forms 10-K,10-Q --limit 2
python scripts/phase9_5_ingest.py --db var/phase9_5.db --cik 0000019617 --forms 10-K,10-Q --limit 1
python scripts/phase9_5_benchmark.py --db var/phase9_5.db --out artifacts/phase9_5_benchmark.json
python -m pytest -q
(cd web && npm run typecheck && npx vitest run && npm run build)
cd web && ATLAS_ARTIFACTS=../artifacts node e2e/phase9_5_filings.mjs
```
