# Engineering defense

Answers correspond to the Priority 0 implementation. Where a topic is incomplete, say so.

## Why build a financial compiler?

Arithmetic in spreadsheets is cheap; preserving financial types, operator versions, and execution fingerprints is not. FEC makes the plan inspectable and comparable to an independent verifier. Evidence: `src/atlas/fec/`, `FinancialAnswerEngine._run`.

## Why does source identity matter?

A correct number from the wrong statement is a wrong research answer. Segment “Sales (millions)” and consolidated “Net sales” both contain sales language. Evidence: concept scoring and companion-row filters in `financial_concepts.py`; 3M case study.

## Why use SQLite?

Local, inspectable, transactional storage for evidence and availability metadata without a service dependency for the FOCUS demo. It is not a claim about multi-tenant production scale. Evidence: `src/atlas/storage/db.py`, `var/focus_demo.db` (untracked).

## What are the limitations of financial XBRL?

XBRL tags can disagree with HTML presentation, omit management views, and still require entity/scope interpretation. Atlas currently has **no XBRL fact table** in the FOCUS corpus; concept identity is lexical plus statement context. This is an explicit limitation, not a feature claim.

## What does a hash establish?

Recomputable integrity of bytes already in hand. A hash alone does not authenticate a remote filing without a trusted acquisition path. Certificate verification reports this limitation when source bytes are unavailable.

## How is source availability established?

Ingestion records SEC acceptance time plus a configured publication lag. Queries compare `availability_time` to the cutoff. Evidence: `KnowledgeEngine.ingest_document`, binding `future_evidence` checks.

## Difference between financial and arithmetic correctness?

Arithmetic correctness: FEC and Fraction verifier agree on the bound inputs. Financial correctness: those inputs are the intended concept, statement, period, currency, and scale. Atlas can be arithmetically right and financially wrong if binding is wrong—which is why binding revalidation and concept resolution exist.

## How does Atlas prevent lookahead?

Cutoff filters on document/cell availability; bindings with later availability abstain. The FOCUS demo refuses a 2017 cutoff for FY2022 evidence.

## Cash-flow vs balance-sheet quantities?

Concepts declare expected statement families (`income`, `balance`, `cash_flow`). Mismatched families are down-scored or filtered. Companion rows further constrain primary statements.

## What happens when evidence conflicts?

Same concept/period/statement with disagreeing values across vintages → `vintage_conflict` refusal. Weak or multi-value matches → `ambiguous`.

## What is independently verified?

Printed raw values recomputed with Fraction math; certificate fingerprint; optional trusted source hash comparison. Not independently verified: economic truth beyond the selected cells, XBRL equality, or market data.

## What did the benchmarks show?

Controlled case studies: 10/13 answered, 3 abstained as designed. FinanceBench population metrics: unavailable without licensed rows (evaluator exit 2). No new leaderboard claim.

## Which optimization failed?

Priority 0 did not pursue performance optimization. Earlier phase notes retain negative findings; they are not re-litigated here as FOCUS wins.

## What would break at much larger scale?

Full-corpus cell extraction in memory, SEC rate limits, and SQLite single-node throughput. Content-addressed incremental recomputation is Priority 2 work, not demonstrated here.

## What is genuinely novel about the integration?

Not a new theorem. The defensible claim is the integration: point-in-time evidence + concept binding + typed compiler + independent verifier + adversarial certificates, with refusals preserved.

## Strongest criticism of Atlas?

Without XBRL and with inferred HTML geometry, concept resolution can still pick the wrong cell in hard layouts; certificates then faithfully verify the wrong binding. The system reduces silent failure but does not eliminate semantic risk.
