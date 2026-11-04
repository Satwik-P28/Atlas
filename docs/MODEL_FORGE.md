# Model Forge

Studio (`/studio`) exposes progressive depth without adding many permanent navigation
sections.

## Authoring paths

1. **Equations** — allowlisted mathematical expressions, named inputs, type errors and
   dependency diagnostics. Compiled to the canonical graph.
2. **Visual graph** — draggable node cards, connections, operator selector, validation
   and execution. The canvas is presentation only; the compiler owns semantics.
3. **Python SDK** — `ModelBuilder` emits the same `atlas.model.v1` graph.

For the supported `price × shares` case, all three produce `Money[USD] = 100` in the
backend tests. Additional capabilities must be documented explicitly; the current
equation grammar cannot call `terminal_value`, while the graph/SDK paths can.

## Valuation lab

- Evidence-linked defaults for revenue, margin, capex, cash, debt and shares.
- Explicit assumptions for growth, tax, D&A, working capital, WACC, terminal growth.
- DCF outputs, FCFF series, trace, audit and evidence links.
- Base/bull/bear scenarios, WACC × growth sensitivity and reverse DCF.
- Save model + application as research objects; reopen with exact issuer, assumptions
  and information cutoff; fork, compare and export from the saved list.
- Historical information cutoff and public-available/Atlas-ingested mode controls flow
  through defaults and model execution, not merely the display.
- Default the company selector to the issuer with the deepest evidence coverage, so a
  company without revenue does not masquerade as a valuation-ready model.

## UI status

The React production build passes. The Studio browser journey verifies historical and
current DCF runs, scenarios/sensitivity, reverse DCF, save/reopen, fork/compare, export,
invalid-equation diagnostics, equation execution, visual-graph validation and the 390 px
responsive layout. Screenshots are stored in `artifacts/13-studio-valuation.png` through
`artifacts/21-studio-error.png`. The journey is not an exhaustive separate automation of
every A–N item; incremental recomputation remains a unit/API test.
