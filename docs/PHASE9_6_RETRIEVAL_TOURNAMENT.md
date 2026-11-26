# Phase 9.6 — Retrieval Tournament

## Ladder

| # | Method | Status |
| --- | --- | --- |
| 1 | Phase 9.5 FTS5/BM25 (`bm25`) | baseline, unchanged |
| 2 | Precision-first lexical cascade (`lexical_improved`) | implemented, evaluated |
| 3 | Separate sparse baseline (SPLADE/BM25 variants) | not run |
| 4 | Local dense retrieval | not run — no pinned, license-reviewed weights; heavy download with no justified gain |
| 5 | Hybrid / reranking | not run (depends on 4) |

The default remains `bm25`. A challenger is only promoted on measured evidence, and there is none.

## Controlled conditions

Both methods ran on the same corpus (`var/phase9_6.db`), the same 112 held-out questions, the same
`public_available` cutoffs, the same gold target documents, the same evaluator and the same
hardware. Only `mode=` differs, and the cascade changes only the match expression:

1. whole-query phrase, then
2. all content terms (AND), then
3. any term (OR).

Abstention was held constant at the retrieval layer (`balanced`), and the strict policy was
measured separately, so a change in abstention could not masquerade as a retrieval gain.

## Results

| Metric | bm25 | lexical_improved | Δ |
| --- | --- | --- | --- |
| Correct document @1 | 0.7589 | 0.7589 | 0.0000 |
| Target document recall @10 | 1.0000 | 1.0000 | 0.0000 |
| MRR | 0.8424 | 0.8424 | 0.0000 |
| Evidence localized | 0.9732 | 0.9732 | 0.0000 |
| Answer literal presence @10 | 0.2411 | 0.2411 | 0.0000 |
| p50 latency (ms) | 642.66 | 643.86 | +1.20 |
| p95 latency (ms) | 791.09 | 769.72 | −21.37 |

**Negative result, recorded deliberately.** At document level the baseline already achieves
recall 1.0, so the cascade has no headroom and produces identical rankings. Its extra passes cost
about 1 ms at the median. There is no basis to make it the default.

## Segmentation

Answer presence is 0.2411 overall. Segmentation shows the shortfall is concentrated in questions
whose reference answer is computed rather than printed (ratios, margins, changes), which the
per-question records make checkable: `question_type` and `answer_rank` are stored for every one of
the 112 questions.

## Resource accounting

* Corpus: 303 MB of source bytes, 112,484 passages, 11,851 tables.
* Query: single-process SQLite FTS5; p50 ≈ 0.64 s, p95 ≈ 0.79 s at this corpus size, versus
  ~7.7 ms in Phase 9.5's six-document corpus. Latency scales with corpus size, not with question
  count, and no caching is applied between questions.
* No GPU was used. No paid API is required.
