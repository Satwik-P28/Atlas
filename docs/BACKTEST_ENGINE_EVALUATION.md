# Backtesting engine evaluation

## Decision

Use a **narrow, tested reference simulator** for Phase 4 rather than integrating LEAN or
NautilusTrader. The simulator is an explicit implementation with documented accounting
and timing; it is not a wrapper around an unfinished external engine and does not claim
institutional execution fidelity.

## Bake-off

| Criterion | LEAN | NautilusTrader | Atlas reference simulator |
|---|---|---|---|
| License | Apache-2.0 | Apache-2.0 | project license |
| Python integration | C# engine + Python API | native Python/Rust | native Python |
| Atlas bar compatibility | requires custom data converter | requires custom data adapter | reads stored bars directly |
| Event sequencing | complete engine clock | complete engine clock | session clock, explicit ordering |
| Order lifecycle | full | full | one target order per decision; market next-open |
| Fill model | configurable | configurable | next open, no partials |
| Commission/slippage | models included | models included | bps commission + bps slippage |
| Splits/dividends | models included | models included | stored actions, economically ordered |
| Calendar | exchange calendars | exchange calendars | stored sessions; no invented holidays |
| Determinism | generally deterministic | generally deterministic | SHA-256 result fingerprint |
| Test surface | broad | broad | small and independently asserted |
| Install/maintenance | heavy runtime, data conversion | compiled dependency, data adapter | no new runtime |
| License/runtime risk in this env | material | material | none beyond Python stdlib |

Neither external engine could be integrated **reliably and verifiably** within this
environment without a data-conversion layer and an unvalidated adapter. Installing a
large engine to obtain a chart would be exactly the decorative breadth this phase
rejects. The architecture keeps an adapter seam: an engine can later implement the same
`Strategy`/result contract, and its fills must pass the independent ledger tests before
being exposed.

## Reference semantics

* Decisions at session close; fills at the next session open.
* No same-close fill unless a valid pre-close decision and executable auction model are
  modeled. Neither is claimed here.
* One long-only instrument, target weight 0 or 1, no leverage, no shorting.
* Commission and slippage are charged on traded notional at fill.
* Splits adjust quantity and per-share basis before the open print; dividends credit cash
  before the close mark on their effective date.
* Equity = cash + quantity × close; the ledger independently reconciles beginning cash,
  trades, commissions, dividends, realized and unrealized P&L.
* Missing open/close means no fill/mark for that session; the run reports the gap rather
  than borrowing a neighboring price.

## Vectorized mode

`src/atlas/quant/vectorized.py` computes a close-to-close weight series for quick
hypothesis triage. It excludes dividends and splits, performs no order fill and has no
cash ledger. Its result is labeled `not_a_fill_simulation`. On IBM buy-and-hold it reports
54.18% versus the event-driven 108.60% because those semantics differ; this gap is
expected and must not be presented as two estimates of the same quantity.

## Not implemented

Partial fills, order books, market impact, borrow/short, options, futures, multi-asset
portfolios, intraday auctions, exchange holiday generation and live routing.
