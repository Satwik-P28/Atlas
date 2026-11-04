# ADR 0017: Scoped reference simulator for Quant Lab

**Status:** accepted for Phase 4.

## Context

Phase 4 needs chronological strategy execution with next-open fills, costs, corporate
actions and an independent cash ledger. LEAN and NautilusTrader are credible engines, but
integrating either here requires a custom Atlas bar adapter and an unvalidated execution
path. An impressive feature list is not evidence that the integration works.

## Decision

Implement `atlas.quant.reference.v1`: one instrument, long-only, raw daily bars, decisions at
close, market target fills at the next open, bps commission and slippage, explicit splits
and cash dividends, and a separate `Portfolio` ledger. Publish the accounting identity and
result fingerprint with every run. Reject unsupported universes, shorts, non-next-open
fills and intraday signals in `atlas.strategy.v1` validation.

The simulator is normative for Quant Lab results. The vectorized preview is triage only and
is labelled `not_a_fill_simulation`.

## Consequences

- Timing and accounting are small enough to validate by hand and adversarially.
- No new runtime dependency or hidden data conversion.
- Capabilities are deliberately narrower than production engines; partial fills, market
  impact, borrow, multi-asset and order-book semantics are absent.
- An external engine can later implement the same result contract, but only after passing
  the ledger and timing tests.

## Rejected alternatives

- Integrate LEAN/Nautilus without a verified adapter: unverifiable and hard to audit.
- Use adjusted prices plus explicit dividends: double-counting risk.
- Fill at the same close: look-ahead unless a pre-close auction model exists.
- Treat the vectorized preview as a backtest: no orders, cash or corporate actions.
