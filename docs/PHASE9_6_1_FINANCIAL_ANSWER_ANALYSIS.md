# Phase 9.6.1 — Financial Answer Analysis

## The three phenomena, separated

| Layer | Metric | Result |
| --- | --- | --- |
| Document discovery | `document_recall@5` / `@10` | 0.9732 / 1.0000 |
| Evidence retrieval | `evidence_proxy@5` / `@10` | 0.8839 / 0.9732 |
| Evidence span alignment | `evidence_span_recall@k` | **not_evaluable** |
| Answer construction | `answer_presence@5` / `@10` | 0.1964 / 0.2411 |
| Claim support | entailment | **not measured** |
| Citation integrity | hash/span/issuer | 1.0000 |

`evidence_proxy` is a text-overlap heuristic over concatenated passages. It can be satisfied by an
incidental number, which is exactly why it is no longer called localization: the artifact reports
`evidence_span_recall@k = "not_evaluable"` for every k. FinanceBench's gold evidence is anchored to
PDF pages; Atlas retrieves SEC HTML. Pretending those spans align would be a fabricated match.

## Why answer presence is 24%

The per-question records (`artifacts/phase9_6_1_evaluation.json`) carry `question_class`, assigned
from dataset structure **before** seeing results:

| Class | n | document_recall@10 | answer_presence@10 |
| --- | --- | --- | --- |
| directly reported value / table lookup | 34 | 1.0000 | 0.0294 |
| unclassified | 43 | 1.0000 | 0.3488 |

Questions that ask for a directly reported number are the worst served: the value lives in a table
cell, and Atlas returns narrative passages from the right filing. This is a table-localisation gap,
not a retrieval failure — the document is found every time.

The remaining gap is arithmetic: margins, ratios and year-over-year changes are computed, never
printed, so a literal-presence test cannot see them even when the inputs are present.

## Arithmetic adapter

Not implemented. Connecting table cells to the Financial-Economic Compiler requires reliable cell
addressing (row/column headers, units, scale, sign, period) and the existing table extractor
preserves rows but not a validated cell grid with period semantics. Building it halfway would
manufacture inputs, which the phase forbids. The measurement above is therefore retrieval-side
only; no calculation correctness is claimed.

## Consequences for promotion

`answer_presence@5` (0.1964) fails the preregistered 0.40 gate. Atlas finds the right document
97% of the time and the right value 24% of the time. Those are different capabilities and the
release decision treats them as such.
