# ADR 0024 — Put institutional research inside the existing Lab

**Status:** accepted (Phase 5)

## Context

Atlas has four established spaces: Explore, Studio, Lab, Monitor. Adding a permanent
navigation item for every pricing engine would fragment the product and make advanced
mathematics look like a separate application.

## Decision

Add `/lab/institutional`, linked contextually from the Quant Lab. Use three tabs — fixed
income, portfolio risk, out-of-sample validation — with progressive disclosure of cash
flows, shocks, Greeks, contributions, diagnostics and provenance. All calculations come
from typed API/FEC operators; React only formats values. Reuse the existing research-object
registry for save, reopen, fork, compare and export.

## Consequences

The primary Lab remains approachable while advanced capabilities are discoverable in
context. The page is one route, not a new navigation section. It is not a decorative
dashboard: every control invokes persisted server-side mathematics and shows assumptions.
